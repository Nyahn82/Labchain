"""Run only against the explicit isolated socket supplied by the pytest harness."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import stat
import sys
from threading import Barrier, local

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.models import (
    AuditLog, Base, LabDepartment, PanelSection, PanelTest, ReferenceRange,
    SampleType, TestCatalog, TestPanel, TestSampleType, UserAccount,
)
from app.schemas import laboratory as s
from app.services import laboratory_service as service


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'overlap_create', 'overlap_activate', 'overlap_patch', 'samples',
                        'panels', 'shared_samples', 'shared_tests', 'decimal_rollback', 'retry_exhausted', 'connection_error'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db:
        db.execute(text('CREATE DATABASE phase3c_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase3c_synthetic', isolation_level='REPEATABLE READ', **options)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False)
        with factory.begin() as db:
            db.add(UserAccount(user_id=1, username='synthetic', password_hash='not-a-login-hash', account_status='ACTIVE'))
            db.add(LabDepartment(department_id=1, department_code='SYNTH', department_name='Synthetic'))
            db.add_all(SampleType(sample_type_id=i, sample_name=f'Synthetic {i}') for i in (1, 2))
            db.flush()
            db.add_all(TestCatalog(test_id=i, test_code=f'SYNTH{i}', test_name=f'Synthetic {i}',
                                   department_id=1, result_type='NUMERIC') for i in (1, 2))
            db.add_all(TestPanel(panel_id=i, panel_code=f'SYNTH{i}', panel_name=f'Synthetic {i}') for i in (1, 2))
            db.flush()
            db.add_all(PanelSection(section_id=i, panel_id=i, section_name='Synthetic', sort_order=1) for i in (1, 2))
            if scenario == 'overlap_activate':
                db.add_all(ReferenceRange(range_id=i, test_id=1, sex='M', is_active=False) for i in (1, 2))
            elif scenario == 'overlap_patch':
                db.add(ReferenceRange(range_id=1, test_id=1, sex='M', age_min=Decimal('0'), age_max=Decimal('9')))
                db.add(ReferenceRange(range_id=2, test_id=1, sex='M', age_min=Decimal('20'), age_max=Decimal('29')))
        barrier = Barrier(2)
        # Deterministically reproduce the shared empty-index-gap deadlock. Each
        # worker waits only on its first attempt so the victim can replay safely.
        if scenario == 'shared_tests':
            deleted = Barrier(2)
            worker = local()
            def align_empty_deletes(connection, cursor, statement, params, context, executemany):
                if statement.startswith('DELETE FROM panel_test ') and not getattr(worker, 'aligned', False):
                    worker.aligned = True
                    deleted.wait(timeout=10)
            event.listen(engine, 'after_cursor_execute', align_empty_deletes)
        samples = {
            1: s.SampleReplacement(sample_types=[{'sample_type_id': 1, 'is_default': True}, {'sample_type_id': 2, 'is_default': False}]),
            2: s.SampleReplacement(sample_types=[{'sample_type_id': 2, 'is_default': True}]),
        }
        panels = {
            1: s.PanelReplacement(tests=[{'test_id': 1, 'section_id': 1, 'sort_order': 1, 'is_required': True},
                                        {'test_id': 2, 'section_id': None, 'sort_order': 2, 'is_required': False}]),
            2: s.PanelReplacement(tests=[{'test_id': 2, 'section_id': 1, 'sort_order': 0, 'is_required': True}]),
        }

        def mutate(number):
            with factory() as db:
                # Open an old consistent snapshot before either contender writes.
                list(db.scalars(select(ReferenceRange)))
                list(db.scalars(select(TestSampleType)))
                list(db.scalars(select(PanelTest)))
                barrier.wait(timeout=10)
                try:
                    if scenario == 'overlap_create':
                        service.save_record(db, ReferenceRange, s.RangeCreate(sex='M'), s.RangeResponse,
                                            1, None, 'REFERENCE_RANGE_CREATE', parent_id=1)
                    elif scenario in {'overlap_activate', 'overlap_patch'}:
                        payload = s.RangePatch(is_active=True) if scenario == 'overlap_activate' else s.RangePatch(age_min='10', age_max='19')
                        service.save_record(db, ReferenceRange, payload, s.RangeResponse,
                                            1, None, 'REFERENCE_RANGE_UPDATE', record_id=number)
                    elif scenario in {'samples', 'shared_samples'}:
                        service.replace_sample_types(db, number if scenario == 'shared_samples' else 1, samples[number], 1, None)
                    else:
                        payload = panels[number]
                        if scenario == 'shared_tests':
                            payload = s.PanelReplacement(tests=[{'test_id': 1, 'section_id': number, 'sort_order': 1, 'is_required': True}])
                        service.replace_panel_tests(db, number if scenario == 'shared_tests' else 1, payload, 1, None)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        if scenario in {'retry_exhausted', 'connection_error'}:
            with factory() as db:
                service.replace_sample_types(db, 1, samples[1], 1, None)
            attempts = []
            def fail_after_replacement(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '):
                    attempts.append(1)
                    code = 1213 if scenario == 'retry_exhausted' else 2006
                    raise OperationalError('synthetic', {}, Exception(code, 'synthetic failure'))
            event.listen(engine, 'before_cursor_execute', fail_after_replacement)
            try:
                with factory() as db:
                    try:
                        service.replace_sample_types(db, 1, samples[2], 1, None)
                        raise AssertionError('Expected injected failure')
                    except OperationalError:
                        pass
            finally:
                event.remove(engine, 'before_cursor_execute', fail_after_replacement)
            assert len(attempts) == (3 if scenario == 'retry_exhausted' else 1)
            with factory() as db:
                assert [(row.sample_type_id, row.is_default) for row in service.sample_assignments(db, 1)] == [(1, True), (2, False)]
                assert len(list(db.scalars(select(AuditLog)))) == 1
        elif scenario == 'decimal_rollback':
            with factory() as db:
                row = service.save_record(db, ReferenceRange, s.RangeCreate(
                    sex='ANY', age_max='9999.99', normal_low='-999999999.999', normal_high='999999999.999'),
                    s.RangeResponse, 1, None, 'REFERENCE_RANGE_CREATE', parent_id=1)
            with factory() as db:
                stored = db.get(ReferenceRange, row.range_id)
                assert stored.normal_low == Decimal('-999999999.999')
                assert stored.normal_high == Decimal('999999999.999') and stored.age_max == Decimal('9999.99')
                service.replace_sample_types(db, 1, samples[1], 1, None)
            def fail_audit(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '):
                    raise SQLAlchemyError('synthetic failure')
            event.listen(engine, 'before_cursor_execute', fail_audit)
            try:
                with factory() as db:
                    try:
                        service.replace_sample_types(db, 1, samples[2], 1, None)
                        raise AssertionError('Expected injected failure')
                    except SQLAlchemyError:
                        pass
            finally:
                event.remove(engine, 'before_cursor_execute', fail_audit)
            with factory() as db:
                assert [(row.sample_type_id, row.is_default) for row in service.sample_assignments(db, 1)] == [(1, True), (2, False)]
                assert len(list(db.scalars(select(AuditLog)))) == 2
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(mutate, (1, 2)))
            assert sorted(results) == ([200, 409] if scenario.startswith('overlap_') else [200, 200]), results
            with factory() as db:
                if scenario.startswith('overlap_'):
                    rows = list(db.scalars(select(ReferenceRange).where(ReferenceRange.is_active.is_(True))))
                    if scenario == 'overlap_patch':
                        assert len(rows) == 2 and sum(row.age_min == Decimal('10') for row in rows) == 1
                    else:
                        assert len(rows) == 1
                    assert len(list(db.scalars(select(AuditLog)))) == 1
                elif scenario in {'samples', 'shared_samples'}:
                    assert len(list(db.scalars(select(AuditLog)))) == 2
                    for test_id in ((1, 2) if scenario == 'shared_samples' else (1,)):
                        actual = [(row.sample_type_id, row.is_default) for row in service.sample_assignments(db, test_id)]
                        assert actual in [[(1, True), (2, False)], [(2, True)]]
                elif scenario == 'panels':
                    actual = sorted((row.test_id, row.section_id, row.sort_order, row.is_required) for row in service.panel_assignments(db, 1))
                    assert actual in [[(1, 1, 1, True), (2, None, 2, False)], [(2, 1, 0, True)]]
                else:
                    assert len(list(db.scalars(select(AuditLog)))) == 2
                    for panel_id in (1, 2):
                        rows = service.panel_assignments(db, panel_id)
                        assert len(rows) == 1 and rows[0].section_id == panel_id
        print('laboratory integrity checks passed')
    finally:
        with engine.begin() as db:
            db.execute(text('DROP DATABASE phase3c_synthetic'))
        engine.dispose()


if __name__ == '__main__':
    main(*sys.argv[1:])
