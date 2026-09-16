"""Subprocess only uses the disposable socket; no production connection/config."""

from concurrent.futures import ThreadPoolExecutor
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
    AuditLog, Base, LabDepartment, LabOrder, LabOrderItem, LabPayment, OrderPanel,
    PanelTest, Patient, RejectionReason, SampleType, Specimen, SpecimenOrderItem,
    SpecimenRejection, TestCatalog, TestPanel, TestSampleType, UserAccount,
)
from app.schemas import workflow as s
from app.schemas import laboratory as lab
from app.services import workflow_service as service
from app.services import laboratory_service as master


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'collect', 'receive', 'reject', 'register_cancel', 'collect_cancel', 'register_twice',
                        'panel_snapshot', 'sample_snapshot', 'code_collisions', 'rollback_decimal'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db:
        db.execute(text('CREATE DATABASE phase4a_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase4a_synthetic', isolation_level='REPEATABLE READ', **options)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False)
        with factory.begin() as db:
            db.add(UserAccount(user_id=1, username='synthetic', password_hash='not-a-login-hash', account_status='ACTIVE'))
            db.add(Patient(patient_id=1, patient_code='SYNTH', first_name='Synthetic', last_name='Patient'))
            db.add(LabDepartment(department_id=1, department_code='SYNTH', department_name='Synthetic'))
            db.add(SampleType(sample_type_id=1, sample_name='Synthetic'))
            db.add(RejectionReason(rejection_reason_id=1, reason_code='SYNTH', reason_name='Synthetic'))
            db.flush()
            db.add_all(TestCatalog(test_id=i, test_code=f'SYNTH{i}', test_name=f'Synthetic {i}',
                                   department_id=1, result_type='NUMERIC') for i in (1, 2))
            db.add(TestPanel(panel_id=1, panel_code='SYNTH', panel_name='Synthetic'))
            db.flush()
            db.add(PanelTest(panel_id=1, test_id=1, sort_order=1, is_required=True))
            db.add_all(TestSampleType(test_id=i, sample_type_id=1, is_default=True) for i in (1, 2))
        order_input = s.OrderCreate(patient_id=1, priority='ROUTINE', panel_ids=[1], test_ids=[1])
        with factory() as db:
            order = service.create_order(db, order_input, 1, None)
        ids = [item.order_item_id for item in order.items]
        register = s.SpecimenCreate(sample_type_id=1, order_item_ids=ids)
        rejection = s.RejectRequest(rejection_reason_id=1, recollection_required=True)
        specimen = None
        if scenario in {'collect', 'receive', 'reject', 'collect_cancel', 'code_collisions', 'rollback_decimal'}:
            with factory() as db:
                specimen = service.register_specimen(db, order.order_id, register, 1, None)
            if scenario in {'receive', 'reject', 'rollback_decimal'}:
                with factory() as db:
                    service.transition_specimen(db, specimen.specimen_id, 'COLLECT', 1, None)

        if scenario in {'panel_snapshot', 'sample_snapshot'}:
            # Freeze the caller's old snapshot, commit a master-data replacement,
            # then ensure the workflow uses current configuration, not stale data.
            with factory() as old:
                list(old.scalars(select(PanelTest)))
                list(old.scalars(select(TestSampleType)))
                with factory() as editor:
                    if scenario == 'panel_snapshot':
                        master.replace_panel_tests(editor, 1, lab.PanelReplacement(tests=[{
                            'test_id': 2, 'sort_order': 1, 'is_required': False}]), 1, None)
                    else:
                        master.replace_sample_types(editor, 1, lab.SampleReplacement(sample_types=[]), 1, None)
                if scenario == 'panel_snapshot':
                    created = service.create_order(old, order_input, 1, None)
                    assert [item.test_id for item in created.items] == [2, 1]
                else:
                    try:
                        service.register_specimen(old, order.order_id, register, 1, None)
                        raise AssertionError('Stale compatibility was accepted')
                    except HTTPException as exc:
                        assert exc.status_code == 409
            with factory() as db:
                assert len(service.order_detail(db, order.order_id).items) == 2
                assert db.scalar(select(func.count()).select_from(Specimen)) == 0
        elif scenario == 'code_collisions':
            original = service.generated_code
            for kind, existing in [('order', order.order_code), ('specimen', specimen.specimen_code)]:
                for exhausted in (False, True):
                    values = iter([existing] * 3 if exhausted else [existing, original('LAB' if kind == 'order' else 'SP')])
                    service.generated_code = lambda prefix: next(values)
                    try:
                        with factory() as db:
                            if kind == 'order':
                                result = service.create_order(db, order_input, 1, None)
                            else:
                                result = service.register_specimen(db, order.order_id, register, 1, None)
                        assert not exhausted and result is not None
                    except HTTPException as exc:
                        assert exhausted and exc.status_code == 409
                    finally:
                        service.generated_code = original
            with factory() as db:
                for model in (LabOrder, OrderPanel, Specimen):
                    assert db.scalar(select(func.count()).select_from(model)) == 2
                assert db.scalar(select(func.count()).select_from(LabOrderItem)) == 4
                assert db.scalar(select(func.count()).select_from(SpecimenOrderItem)) == 4
                assert db.scalar(select(func.count()).select_from(AuditLog)) == 4
        elif scenario == 'rollback_decimal':
            with factory() as db:
                service.record_payment(db, order.order_id, s.PaymentCreate(payment_status='PAID', amount='9999999999.99'), 1, None)
            with factory() as db:
                assert db.scalar(select(LabPayment.amount)) == Decimal('9999999999.99')
                before = service.order_detail(db, order.order_id).model_dump()
                audit_count = db.scalar(select(func.count()).select_from(AuditLog))
            def fail_audit(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '):
                    raise SQLAlchemyError('synthetic failure')
            event.listen(engine, 'before_cursor_execute', fail_audit)
            try:
                for action in ('create', 'register', 'reject', 'cancel', 'payment'):
                    with factory() as db:
                        try:
                            if action == 'create':
                                service.create_order(db, order_input, 1, None)
                            elif action == 'register':
                                service.register_specimen(db, order.order_id, register, 1, None)
                            elif action == 'reject':
                                service.transition_specimen(db, specimen.specimen_id, 'REJECT', 1, None, rejection)
                            elif action == 'cancel':
                                service.cancel_order(db, order.order_id, s.CancelRequest(reason='Synthetic'), 1, None)
                            else:
                                service.record_payment(db, order.order_id, s.PaymentCreate(payment_status='WAIVED'), 1, None)
                            raise AssertionError('Expected audit failure')
                        except SQLAlchemyError:
                            pass
            finally:
                event.remove(engine, 'before_cursor_execute', fail_audit)
            with factory() as db:
                assert service.order_detail(db, order.order_id).model_dump() == before
                assert db.scalar(select(func.count()).select_from(LabOrder)) == 1
                assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_count
        else:
            barrier = Barrier(2)
            def mutate(number):
                with factory() as db:
                    # Both contenders see the same old snapshot, like authenticated
                    # requests under MySQL's default REPEATABLE READ isolation.
                    for model in (LabOrder, LabOrderItem, OrderPanel, Specimen, SpecimenOrderItem, SpecimenRejection):
                        list(db.scalars(select(model)))
                    barrier.wait(timeout=10)
                    try:
                        if number == 2 and scenario.endswith('_cancel'):
                            service.cancel_order(db, order.order_id, s.CancelRequest(reason='Synthetic'), 1, None)
                        elif scenario in {'register_cancel', 'register_twice'}:
                            service.register_specimen(db, order.order_id, register, 1, None)
                        else:
                            action = 'COLLECT' if scenario == 'collect_cancel' else scenario.upper()
                            service.transition_specimen(db, specimen.specimen_id, action, 1, None,
                                                        rejection if action == 'REJECT' else None)
                        return 200
                    except HTTPException as exc:
                        return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = sorted(pool.map(mutate, (1, 2)))
            if scenario.endswith('_cancel'):
                assert results in ([200, 200], [200, 409]), results
            else:
                assert results == ([200, 200] if scenario == 'register_twice' else [200, 409]), results
            with factory() as db:
                final = service.order_detail(db, order.order_id)
                if scenario.endswith('_cancel'):
                    assert final.status == 'CANCELLED'
                    assert all(item.status == 'CANCELLED' for item in final.items)
                    assert all(panel.status == 'CANCELLED' for panel in final.panels)
                else:
                    assert final.status == 'IN_PROGRESS'
                    assert all(item.status == 'IN_PROGRESS' for item in final.items)
                if scenario == 'register_twice':
                    assert len(final.specimens) == 2 and all(len(row.mappings) == 2 for row in final.specimens)
                    assert len({row.specimen_code for row in final.specimens}) == 2
                elif scenario == 'reject':
                    assert db.scalar(select(func.count()).select_from(SpecimenRejection)) == 1
                    assert final.specimens[0].specimen_status == 'REJECTED'
                    assert len(final.specimens[0].mappings) == 2
                elif scenario in {'collect', 'receive'}:
                    assert final.specimens[0].specimen_status == {'collect': 'COLLECTED', 'receive': 'RECEIVED'}[scenario]
                    action_count = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'SPECIMEN_' + scenario.upper()))
                    assert action_count == 1
        print('workflow integrity checks passed')
    finally:
        with engine.begin() as db:
            db.execute(text('DROP DATABASE phase4a_synthetic'))
        engine.dispose()


if __name__ == '__main__':
    main(*sys.argv[1:])
