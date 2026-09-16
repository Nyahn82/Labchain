"""Never uses production credentials or sockets; launched by the test harness."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import stat
import sys
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.models import (
    AuditLog, Base, LabDepartment, LabOrder, LabOrderItem, LabResultItem, OrderPanel,
    PanelTest, Patient, ReferenceRange, RejectionReason, SampleType, Specimen,
    SpecimenOrderItem, SpecimenRejection, TestCatalog, TestPanel, TestSampleType, UserAccount,
)
from app.schemas import results as s
from app.schemas import workflow as w
from app.services import result_service as service
from app.services import workflow_service as workflow


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'duplicate_create', 'review', 'verify', 'parallel_verify', 'create_cancel', 'verify_cancel',
                        'create_reject', 'patch_review', 'range_snapshot', 'rollback_decimal'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db:
        db.execute(text('CREATE DATABASE phase4b_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase4b_synthetic', isolation_level='REPEATABLE READ', **options)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False)
        with factory.begin() as db:
            db.add(UserAccount(user_id=1, username='synthetic', password_hash='not-a-login-hash', account_status='ACTIVE'))
            db.add(Patient(patient_id=1, patient_code='SYNTH', first_name='Synthetic', last_name='Patient',
                           birth_date=date(2000, 1, 1), sex='M'))
            db.add(LabDepartment(department_id=1, department_code='SYNTH', department_name='Synthetic'))
            db.add(SampleType(sample_type_id=1, sample_name='Synthetic'))
            db.add(RejectionReason(rejection_reason_id=1, reason_code='SYNTH', reason_name='Synthetic'))
            db.flush()
            db.add_all(TestCatalog(test_id=i, test_code=f'SYNTH{i}', test_name=f'Synthetic {i}',
                                   department_id=1, result_type='NUMERIC') for i in (1, 2))
            db.add(TestPanel(panel_id=1, panel_code='SYNTH', panel_name='Synthetic'))
            db.flush()
            for test_id in (1, 2):
                db.add(PanelTest(panel_id=1, test_id=test_id, sort_order=test_id, is_required=True))
                db.add(TestSampleType(test_id=test_id, sample_type_id=1, is_default=True))
            db.add(ReferenceRange(range_id=1, test_id=1, sex='ANY', normal_low=Decimal('12'), normal_high=Decimal('16'),
                                  critical_low=Decimal('10'), critical_high=Decimal('20')))
        with factory() as db:
            order = workflow.create_order(db, w.OrderCreate(patient_id=1, priority='ROUTINE', panel_ids=[1]), 1, None)
        item_ids = [item.order_item_id for item in order.items]
        with factory() as db:
            specimen = workflow.register_specimen(db, order.order_id,
                                                  w.SpecimenCreate(sample_type_id=1, order_item_ids=item_ids), 1, None)
        with factory() as db:
            workflow.transition_specimen(db, specimen.specimen_id, 'COLLECT', 1, None)
        with factory() as db:
            workflow.transition_specimen(db, specimen.specimen_id, 'RECEIVE', 1, None)
        payload = s.ResultCreate(result_value='12.60', specimen_id=specimen.specimen_id)
        result_ids = []
        if scenario in {'review', 'verify', 'parallel_verify', 'verify_cancel', 'patch_review'}:
            for item_id in (item_ids if scenario == 'parallel_verify' else item_ids[:1]):
                with factory() as db:
                    record = service.create_result(db, item_id, payload, 1, None)
                    result_ids.append(record.result_item_id)
                if scenario in {'verify', 'parallel_verify', 'verify_cancel'}:
                    with factory() as db:
                        service.transition_result(db, record.result_item_id, 'REVIEW', 1, None)
        if scenario == 'range_snapshot':
            with factory() as old:
                old.get(Patient, 1)
                list(old.scalars(select(ReferenceRange)))
                with factory.begin() as editor:
                    editor.get(ReferenceRange, 1).is_active = False
                    editor.get(Patient, 1).birth_date = None
                    editor.get(Patient, 1).sex = None
                    editor.get(LabOrder, order.order_id).order_date = datetime(2010, 1, 1)
                    editor.add(ReferenceRange(range_id=2, test_id=1, sex='ANY', normal_low=Decimal('20'), normal_high=Decimal('30'),
                                              effective_from=date(2010, 1, 1), effective_to=date(2010, 1, 1)))
                record = service.create_result(old, item_ids[0], payload, 1, None)
                assert record.reference_range_id == 2 and record.flag == 'LOW'
                assert record.numeric_value == Decimal('12.600')
        elif scenario == 'rollback_decimal':
            def fail_audit(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '):
                    raise SQLAlchemyError('synthetic private failure')
            # Fail each stage after writes, then prove all rows/statuses/audits match.
            for action in ('create', 'patch', 'review', 'verify'):
                with factory() as db:
                    before = workflow.order_detail(db, order.order_id).model_dump()
                    prior_results = service.list_results(db, order.order_id, page=1, page_size=100)
                    prior = [row.model_dump() for row in prior_results['items']]
                    audit_count = db.scalar(select(func.count()).select_from(AuditLog))
                event.listen(engine, 'before_cursor_execute', fail_audit)
                try:
                    with factory() as db:
                        try:
                            if action == 'create':
                                service.create_result(db, item_ids[0], payload, 1, None)
                            elif action == 'patch':
                                service.update_result(db, result_ids[0], s.ResultPatch(result_value='999999999.999'), 1, None)
                            else:
                                service.transition_result(db, result_ids[0], action.upper(), 1, None)
                            raise AssertionError('Expected audit failure')
                        except SQLAlchemyError:
                            pass
                finally:
                    event.remove(engine, 'before_cursor_execute', fail_audit)
                with factory() as db:
                    assert workflow.order_detail(db, order.order_id).model_dump() == before
                    actual = service.list_results(db, order.order_id, page=1, page_size=100)['items']
                    assert [row.model_dump() for row in actual] == prior
                    assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_count
                # Prepare the next stage with a successful operation.
                with factory() as db:
                    if action == 'create':
                        record = service.create_result(db, item_ids[0], s.ResultCreate(
                            result_value='-999999999.999', specimen_id=specimen.specimen_id), 1, None)
                        result_ids.append(record.result_item_id)
                        assert record.numeric_value == Decimal('-999999999.999')
                    elif action == 'patch':
                        record = service.update_result(db, result_ids[0], s.ResultPatch(result_value='999999999.999'), 1, None)
                        assert record.numeric_value == Decimal('999999999.999')
                    else:
                        service.transition_result(db, result_ids[0], action.upper(), 1, None)
        else:
            barrier = Barrier(2)
            def mutate(number):
                with factory() as db:
                    for model in (LabOrder, LabOrderItem, OrderPanel, LabResultItem, Specimen):
                        list(db.scalars(select(model)))
                    barrier.wait(timeout=10)
                    try:
                        if scenario.endswith('_cancel') and number == 2:
                            workflow.cancel_order(db, order.order_id, w.CancelRequest(reason='Synthetic withdrawal'), 1, None)
                        elif scenario == 'create_reject' and number == 2:
                            workflow.transition_specimen(db, specimen.specimen_id, 'REJECT', 1, None,
                                w.RejectRequest(rejection_reason_id=1, recollection_required=True))
                        elif scenario in {'duplicate_create', 'create_cancel', 'create_reject'}:
                            service.create_result(db, item_ids[0], payload, 1, None)
                        elif scenario == 'patch_review' and number == 1:
                            service.update_result(db, result_ids[0], s.ResultPatch(result_value='22'), 1, None)
                        else:
                            action = 'REVIEW' if scenario in {'review', 'patch_review'} else 'VERIFY'
                            identifier = result_ids[number - 1] if scenario == 'parallel_verify' else result_ids[0]
                            service.transition_result(db, identifier, action, 1, None)
                        return 200
                    except HTTPException as exc:
                        return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(mutate, (1, 2)))
            if scenario.endswith('_cancel') or scenario == 'patch_review':
                assert statuses in ([200, 200], [200, 409]), statuses
            else:
                assert statuses == ([200, 200] if scenario == 'parallel_verify' else [200, 409]), statuses
            with factory() as db:
                final = workflow.order_detail(db, order.order_id)
                records = list(db.scalars(select(LabResultItem).order_by(LabResultItem.result_item_id)))
                if scenario == 'parallel_verify':
                    assert len(records) == 2 and all(row.status == 'VERIFIED' for row in records)
                    assert final.status == final.panels[0].status == 'COMPLETED'
                    assert all(item.status == 'COMPLETED' for item in final.items)
                elif scenario.endswith('_cancel'):
                    assert final.status == final.panels[0].status == 'CANCELLED'
                    if records and records[0].status == 'VERIFIED':
                        assert final.items[0].status == 'COMPLETED'
                    else:
                        assert all(item.status == 'CANCELLED' for item in final.items)
                elif scenario == 'create_reject':
                    if records:
                        assert len(records) == 1 and final.specimens[0].specimen_status == 'PROCESSED'
                        assert db.scalar(select(func.count()).select_from(SpecimenRejection)) == 0
                    else:
                        assert final.specimens[0].specimen_status == 'REJECTED'
                        assert db.scalar(select(func.count()).select_from(SpecimenRejection)) == 1
                    assert len(final.specimens[0].mappings) == 2
                elif scenario == 'patch_review':
                    assert records[0].status == 'REVIEWED'
                    assert (records[0].numeric_value, records[0].flag) in [
                        (Decimal('12.600'), 'NORMAL'), (Decimal('22.000'), 'CRITICAL_HIGH')]
                else:
                    assert len(records) == 1
                    expected = {'duplicate_create': 'DRAFT', 'review': 'REVIEWED', 'verify': 'VERIFIED'}[scenario]
                    assert records[0].status == expected
                    action = {'duplicate_create': 'CREATE', 'review': 'REVIEW', 'verify': 'VERIFY'}[scenario]
                    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'LAB_RESULT_' + action)) == 1
        print('result integrity checks passed')
    finally:
        with engine.begin() as db:
            db.execute(text('DROP DATABASE phase4b_synthetic'))
        engine.dispose()


if __name__ == '__main__':
    main(*sys.argv[1:])
