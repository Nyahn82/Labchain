"""Standalone synthetic MySQL probe; never reads application DB credentials."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import stat
import sys
from threading import Barrier
from tempfile import TemporaryDirectory

from app.config import settings
from app.services import report_release_service as release

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
    assert scenario in {'release', 'revise', 'supersede', 'rollback', 'stale', 'token_case', 'branches'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db:
        db.execute(text('CREATE DATABASE phase5b_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase5b_synthetic', isolation_level='REPEATABLE READ', **options)
    factory = sessionmaker(bind=engine, autoflush=False)
    storage = TemporaryDirectory(prefix='rhu-phase5b-reports-', dir='/tmp')
    settings.report_storage_dir = Path(storage.name)
    settings.public_base_url = 'https://synthetic.example.test'
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

        def approve(report_id):
            with factory() as db:
                link = service.assign_signatory(db, report_id, s.AssignRequest(signatory_id=1, signatory_type='PATHOLOGIST'), 1, None)
                service.sign_report(db, report_id, s.SignRequest(report_signatory_id=link.report_signatory_id), 1, None)
                service.approve_report(db, report_id, 1, None)
        with factory() as db:
            service.generate_report(db, 1, s.GenerateRequest(template_id=1), 1, None)
        approve(1)
        if scenario != 'release':
            with factory() as db:
                release.release_report(db, 1, 1, None)
        if scenario in {'supersede', 'rollback', 'branches'}:
            with factory() as db:
                revised = release.revise_report(db, 1, s.GenerateRequest(), 1, None)
            approve(revised.report_id)
        if scenario in {'release', 'revise', 'supersede'}:
            barrier = Barrier(2)
            def contend(number):
                with factory() as db:
                    # Hold stale repeatable-read snapshots before acquiring the parent lock.
                    list(db.scalars(select(LabReport)))
                    list(db.scalars(select(ReportVerification)))
                    barrier.wait(timeout=10)
                    try:
                        if scenario == 'revise': release.revise_report(db, 1, s.GenerateRequest(), 1, None)
                        else: release.release_report(db, 2 if scenario == 'supersede' else 1, 1, None)
                        return 200
                    except HTTPException as exc:
                        return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(contend, (1, 2)))
            assert statuses == ([200, 200] if scenario == 'revise' else [200, 409]), statuses
            with factory() as db:
                rows = list(db.scalars(select(LabReport).order_by(LabReport.version_no)))
                if scenario == 'revise':
                    assert [row.version_no for row in rows] == [1, 2, 3]
                    assert rows[0].report_status == 'RELEASED'
                    assert [row.supersedes_report_id for row in rows[1:]] == [1, 1]
                if scenario == 'supersede':
                    assert [row.report_status for row in rows] == ['REVOKED', 'RELEASED']
                    assert rows[0].revoked_at == rows[1].released_at
                assert db.scalar(select(func.count()).select_from(ReportVerification)) == (2 if scenario == 'supersede' else 1)
            assert len(list(Path(storage.name).rglob('*.pdf'))) == (2 if scenario == 'supersede' else 1)
        elif scenario == 'rollback':
            def fail_audit(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic audit failure')
            event.listen(engine, 'before_cursor_execute', fail_audit)
            try:
                with factory() as db:
                    try:
                        release.release_report(db, 2, 1, None)
                        raise AssertionError('Expected rollback')
                    except SQLAlchemyError:
                        pass
            finally:
                event.remove(engine, 'before_cursor_execute', fail_audit)
            with factory() as db:
                assert db.get(LabReport, 1).report_status == 'RELEASED'
                assert db.get(LabReport, 2).report_status == 'APPROVED'
                assert db.scalar(select(func.count()).select_from(ReportVerification)) == 1
            assert len(list(Path(storage.name).rglob('*.pdf'))) == 1
        elif scenario == 'stale':
            with factory() as stale:
                verification = stale.scalar(select(ReportVerification))
                token = verification.verification_token
                stale.get(LabReport, 1)
                with factory() as db:
                    release.revoke_report(db, 1, s.RevokeRequest(reason='Synthetic'), 1, None)
                assert release.public_verification(stale, token, None).status == 'REVOKED'
        elif scenario == 'token_case':
            with factory() as db:
                token = db.scalar(select(ReportVerification.verification_token))
                assert release.public_verification(db, token.swapcase(), None).status == 'NOT_FOUND'
                assert release.public_verification(db, token, None).status == 'VERIFIED'
        elif scenario == 'branches':
            with factory() as db:
                third = release.revise_report(db, 1, s.GenerateRequest(), 1, None)
            approve(third.report_id)
            with factory() as db:
                release.release_report(db, third.report_id, 1, None)
                try:
                    release.release_report(db, 2, 1, None)
                    raise AssertionError('An older branch must not supersede the current version')
                except HTTPException as exc:
                    assert exc.status_code == 409
        print('release integrity checks passed')
    finally:
        with engine.begin() as db:
            db.execute(text('DROP DATABASE phase5b_synthetic'))
        engine.dispose()
        storage.cleanup()


if __name__ == '__main__':
    main(*sys.argv[1:])
