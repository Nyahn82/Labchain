"""Standalone synthetic MySQL probe; never reads application DB credentials."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import stat
import sys
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.models import (
    AuditLog, Base, FacilityProfile, LabDepartment, LabOrder, LabOrderItem, LabReport,
    LabResultItem, Patient, ReferenceRange, ReportPatientSnapshot, ReportResultItem,
    ReportSignatory, ReportTemplate, ReportVerification, Signatory, Staff, StaffAccountLink,
    TestCatalog, UserAccount,
)
from app.schemas import reporting as s
from app.services import reporting_service as service


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'generate', 'assign', 'sign', 'approve', 'facility', 'template_approve',
                        'stale_snapshots', 'stale_template', 'stale_signatory', 'rollback'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db:
        db.execute(text('CREATE DATABASE phase5a_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase5a_synthetic', isolation_level='REPEATABLE READ', **options)
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        Base.metadata.create_all(engine)
        now = datetime(2026, 9, 16, 12)
        with factory.begin() as db:
            db.add(UserAccount(user_id=1, username='synthetic', password_hash='not-a-login-hash', account_status='ACTIVE'))
            db.add(Staff(staff_id=1, staff_code='SYNTH', first_name='Synthetic', last_name='Signer'))
            db.add(Patient(patient_id=1, patient_code='SYNTH', first_name='Synthetic', last_name='Patient', birth_date=date(2000, 1, 1)))
            db.add(LabDepartment(department_id=1, department_code='SYNTH', department_name='Synthetic'))
            db.add(FacilityProfile(facility_id=1, facility_name='Synthetic RHU'))
            db.add(ReportTemplate(template_id=1, template_code='SYNTH', template_name='Synthetic'))
            db.flush()
            db.add(StaffAccountLink(staff_id=1, user_id=1))
            db.add(Signatory(signatory_id=1, staff_id=1, license_number_snapshot='SYNTH'))
            db.add(TestCatalog(test_id=1, test_code='SYNTH', test_name='Synthetic Test', department_id=1, result_type='NUMERIC'))
            db.add(LabOrder(order_id=1, order_code='SYNTH', patient_id=1, order_date=now, priority='ROUTINE', status='COMPLETED'))
            db.flush()
            db.add(ReferenceRange(range_id=1, test_id=1, sex='ANY', normal_low=Decimal('12.5'), normal_high=Decimal('16.5')))
            db.add(LabOrderItem(order_item_id=1, order_id=1, test_id=1, status='COMPLETED'))
            db.flush()
            db.add(LabResultItem(result_item_id=1, order_item_id=1, result_value='12.60', numeric_value=Decimal('12.600'),
                reference_range_id=1, flag='NORMAL', status='VERIFIED', encoded_by_user_id=1, encoded_at=now,
                reviewed_by_user_id=1, reviewed_at=now, verified_by_user_id=1, verified_at=now))
        generate = lambda db: service.generate_report(db, 1, s.GenerateRequest(template_id=1), 1, None)
        assign = lambda db: service.assign_signatory(db, 1, s.AssignRequest(signatory_id=1, signatory_type='PATHOLOGIST'), 1, None)
        sign = lambda db: service.sign_report(db, 1, s.SignRequest(report_signatory_id=1), 1, None)
        approve = lambda db: service.approve_report(db, 1, 1, None)
        operations = {'generate': generate, 'assign': assign, 'sign': sign, 'approve': approve,
            'facility': lambda db: service.save_facility(db, s.FacilityCreate(facility_name='Synthetic'), 1, None, create=True)}
        if scenario in {'assign', 'sign', 'approve', 'template_approve', 'stale_template', 'stale_signatory'}:
            with factory() as db:
                generate(db)
        if scenario in {'sign', 'approve', 'template_approve', 'stale_template', 'stale_signatory'}:
            with factory() as db:
                assign(db)
        if scenario in {'approve', 'template_approve', 'stale_template', 'stale_signatory'}:
            with factory() as db:
                sign(db)
        if scenario == 'facility':
            with factory.begin() as db:
                db.execute(delete(FacilityProfile))
        if scenario == 'stale_snapshots':
            with factory() as stale:
                # Keep ORM identities as well as the old repeatable-read snapshot.
                old_patient = stale.get(Patient, 1)
                old_test = stale.get(TestCatalog, 1)
                old_range = stale.get(ReferenceRange, 1)
                with factory.begin() as editor:
                    editor.get(Patient, 1).first_name = 'Current'
                    editor.get(TestCatalog, 1).test_name = 'Current test'
                    editor.get(ReferenceRange, 1).normal_high = Decimal('20.5')
                row = generate(stale)
                assert row.patient_snapshot.patient_name == 'Current Patient'
                assert row.result_snapshots[0].test_name_snapshot == 'Current test'
                assert row.result_snapshots[0].reference_range_snapshot == '12.5 - 20.5'
                assert row.result_snapshots[0].result_value_snapshot == '12.60'
        elif scenario in {'stale_template', 'stale_signatory'}:
            with factory() as stale:
                old_report = stale.get(LabReport, 1)
                list(stale.scalars(select(ReportSignatory)))
                with factory() as db:
                    approve(db)
                try:
                    if scenario == 'stale_template':
                        service.save_configuration(stale, ReportTemplate, s.TemplatePatch(header_title='Rewrite'), 1, None, record_id=1)
                    else:
                        service.save_configuration(stale, Signatory, s.SignatoryPatch(license_number_snapshot='Rewrite'), 1, None, record_id=1)
                    raise AssertionError('Expected historical protection')
                except HTTPException as exc:
                    assert exc.status_code == 409
        elif scenario == 'rollback':
            def fail_audit(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '):
                    raise SQLAlchemyError('Synthetic failure')
            for operation in (generate, assign, sign, approve):
                with factory() as db:
                    before = {model.__tablename__: [service.fields(row) for row in db.scalars(select(model))]
                              for model in (LabReport, ReportPatientSnapshot, ReportResultItem, ReportSignatory, AuditLog)}
                event.listen(engine, 'before_cursor_execute', fail_audit)
                try:
                    with factory() as db:
                        try:
                            operation(db)
                            raise AssertionError('Expected failure')
                        except SQLAlchemyError:
                            pass
                finally:
                    event.remove(engine, 'before_cursor_execute', fail_audit)
                with factory() as db:
                    after = {model.__tablename__: [service.fields(row) for row in db.scalars(select(model))]
                             for model in (LabReport, ReportPatientSnapshot, ReportResultItem, ReportSignatory, AuditLog)}
                    assert before == after
                # Rolled-back AUTO_INCREMENT values are consumed on MySQL.
                if operation is generate:
                    with engine.begin() as db:
                        db.execute(text('ALTER TABLE lab_report AUTO_INCREMENT = 1'))
                elif operation is assign:
                    with engine.begin() as db:
                        db.execute(text('ALTER TABLE report_signatory AUTO_INCREMENT = 1'))
                with factory() as db:
                    operation(db)
        else:
            barrier = Barrier(2)
            def mutate(number):
                with factory() as db:
                    # Establish old snapshots before contending on row locks.
                    list(db.scalars(select(LabReport)))
                    list(db.scalars(select(ReportSignatory)))
                    barrier.wait(timeout=10)
                    try:
                        if scenario == 'template_approve':
                            if number == 1:
                                approve(db)
                            else:
                                service.save_configuration(db, ReportTemplate, s.TemplatePatch(header_title='Current'), 1, None, record_id=1)
                        else:
                            operations[scenario](db)
                        return 200
                    except HTTPException as exc:
                        return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(mutate, (1, 2)))
            assert statuses in ([[200, 200], [200, 409]] if scenario == 'template_approve' else [[200, 409]]), statuses
            with factory() as db:
                if scenario == 'facility':
                    assert db.scalar(select(func.count()).select_from(FacilityProfile)) == 1
                else:
                    assert db.scalar(select(func.count()).select_from(LabReport)) == 1
                    assert db.scalar(select(func.count()).select_from(ReportPatientSnapshot)) == 1
                    assert db.scalar(select(func.count()).select_from(ReportResultItem)) == 1
                    if scenario in {'assign', 'sign', 'approve', 'template_approve'}:
                        assert db.scalar(select(func.count()).select_from(ReportSignatory)) == 1
                    if scenario in {'approve', 'template_approve'}:
                        assert db.get(LabReport, 1).report_status == 'APPROVED'
                    action = {'generate': 'REPORT_GENERATE', 'assign': 'REPORT_SIGNATORY_ASSIGN', 'sign': 'REPORT_SIGN',
                              'approve': 'REPORT_APPROVE', 'template_approve': 'REPORT_APPROVE'}[scenario]
                    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == action)) == 1
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ReportVerification)) == 0
            for report in db.scalars(select(LabReport)):
                assert report.released_at is report.pdf_path is None
        print('report integrity checks passed')
    finally:
        with engine.begin() as db:
            db.execute(text('DROP DATABASE phase5a_synthetic'))
        engine.dispose()


if __name__ == '__main__':
    main(*sys.argv[1:])
