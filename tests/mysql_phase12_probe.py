"""Never use application DB credentials: disposable Unix socket only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
import sys
from threading import Barrier

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Base, RolePermission
from app.services.permission_catalog import ensure_permissions
from app.services.rbac_service import ensure_core_roles
from app.services.role_permission_matrix import MatrixError, execute_matrix, preflight


def main(socket, scenario):
    socket = Path(socket).resolve()
    assert socket.parent.parent == Path('/tmp') and socket.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket.stat().st_mode)
    assert scenario in {'uniqueness', 'locking', 'concurrent', 'rollback', 'idempotency'}
    database = 'phase12_synthetic_' + scenario
    options = {'connect_args': {'unix_socket': str(socket), 'connect_timeout': 5}, 'hide_parameters': True}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db:
        db.execute(text(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/' + database, isolation_level='REPEATABLE READ', **options)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False)
        with factory.begin() as db:
            ensure_core_roles(db)
            ensure_permissions(db)
        plan = preflight(factory)
        if scenario == 'concurrent':
            barrier = Barrier(2)
            def contender(_):
                observed = preflight(factory)
                barrier.wait(timeout=15)
                try:
                    return len(execute_matrix(factory, observed))
                except MatrixError as exc:
                    assert 'State changed' in str(exc)
                    return 'STALE_PLAN'
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(contender, (1, 2)))
            assert outcomes.count(50) == 1 and outcomes.count('STALE_PLAN') == 1, outcomes
        elif scenario == 'rollback':
            def fail(rows):
                assert len(rows) == 50
                raise RuntimeError('Synthetic precommit failure')
            try:
                execute_matrix(factory, plan, record_prepared=fail)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Failure was not injected')
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(RolePermission)) == 0
            assert len(execute_matrix(factory, preflight(factory))) == 50
        elif scenario == 'locking':
            statements = []
            def trace(connection, cursor, statement, parameters, context, executemany):
                statements.append((statement, parameters))
            event.listen(engine, 'before_cursor_execute', trace)
            try:
                assert len(execute_matrix(factory, plan)) == 50
            finally:
                event.remove(engine, 'before_cursor_execute', trace)
            locks = [(s.replace('`', ''), p) for s, p in statements if 'FOR UPDATE' in s]
            assert 'SYSTEM_ADMIN' in locks[0][1].values()
            assert 'ORDER BY role.role_code' in locks[1][0]
            assert set(locks[1][1].values()) == {'LAB_SIGNER', 'LAB_STAFF', 'LAB_SUPERVISOR'}
            assert any('ORDER BY permission.permission_id' in s for s, _ in locks)
            assert any('ORDER BY role_permission.permission_id' in s for s, _ in locks)
            assert all(s.lstrip().startswith(('SELECT', 'INSERT INTO role_permission')) for s, _ in statements)
        else:
            assert len(execute_matrix(factory, plan)) == 50
        if scenario == 'uniqueness':
            with factory() as db:
                row = db.scalar(select(RolePermission))
                rid, pid = row.role_id, row.permission_id
            try:
                with factory.begin() as db:
                    db.add(RolePermission(role_id=rid, permission_id=pid))
                    db.flush()
            except IntegrityError:
                pass
            else:
                raise AssertionError('Actual MySQL uniqueness constraint did not reject duplicate')
        assert execute_matrix(factory, preflight(factory)) == []
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(RolePermission)) == 50
        print('phase12 checks passed:', scenario)
    finally:
        engine.dispose()
        cleanup = create_engine('mysql+pymysql://root@localhost/', **options)
        with cleanup.begin() as db:
            db.execute(text(f'DROP DATABASE `{database}`'))
        cleanup.dispose()


if __name__ == '__main__':
    main(*sys.argv[1:])
