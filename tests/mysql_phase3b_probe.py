"""Subprocess helper restricted to a disposable local MySQL socket."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
import sys
from threading import Barrier, Event

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from app.models import AuthSession, Base, Role, Staff, StaffAccountLink, UserAccount, UserRole
from app.schemas.administration import RoleReplacement, StaffAccountCreate, StatusUpdate
from app.security.passwords import hash_password
from app.services.administration_service import create_staff_account, replace_roles, update_status
from app.services.auth_service import authenticate, utc_now


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'disable', 'roles', 'mixed', 'account', 'login_disable'}
    engine = create_engine('mysql+pymysql://root@localhost/', hide_parameters=True,
                           connect_args={'unix_socket': str(socket_path), 'connect_timeout': 5})
    with engine.begin() as db:
        db.execute(text('CREATE DATABASE phase3b_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase3b_synthetic', hide_parameters=True,
                           connect_args={'unix_socket': str(socket_path), 'connect_timeout': 5},
                           isolation_level='REPEATABLE READ')
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False)
        password = 'Synthetic-mysql-password-123!'
        with factory.begin() as db:
            db.add(Role(role_id=1, role_code='SYSTEM_ADMIN', role_name='Synthetic administrator', is_active=True))
            for number in (1, 2):
                db.add(UserAccount(user_id=number, username=f'synthetic-{number}',
                                   password_hash=hash_password(password), account_status='ACTIVE'))
            db.add(Staff(staff_id=1, staff_code='SYNTHETIC', first_name='Synthetic', last_name='Example'))
            db.flush()
            for number in (1, 2):
                db.add(UserRole(user_id=number, role_id=1, assigned_at=utc_now()))
        barrier = Barrier(2)

        def mutate(number):
            with factory() as db:
                # Reproduce the snapshot opened by Phase 3A authentication before
                # both contenders acquire the shared administrative row lock.
                assert len(list(db.scalars(select(UserAccount)))) == 2
                barrier.wait(timeout=10)
                try:
                    if scenario == 'account':
                        create_staff_account(db, 1, StaffAccountCreate(
                            username=f'new-{number}', password=password, role_codes=[]), number, None)
                    elif scenario == 'roles' or (scenario == 'mixed' and number == 2):
                        replace_roles(db, number, RoleReplacement(role_codes=[]), number, None)
                    else:
                        update_status(db, number, StatusUpdate(account_status='INACTIVE'), number, None)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        if scenario != 'login_disable':
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(mutate, (1, 2)))
            assert sorted(results) == [200, 409], results
            with factory() as db:
                if scenario == 'account':
                    assert db.scalar(select(func.count()).select_from(UserAccount)) == 3
                    assert db.scalar(select(func.count()).select_from(StaffAccountLink)) == 1
                else:
                    remaining = db.scalar(select(func.count()).select_from(UserAccount)
                                          .join(UserRole, UserRole.user_id == UserAccount.user_id)
                                          .where(UserRole.role_id == 1, UserAccount.account_status == 'ACTIVE'))
                    assert remaining == 1
        else:
            # Hold login just after acquiring its account lock, then start a
            # disabling transaction. Disable must wait and revoke that session.
            locked, release, attempted = Event(), Event(), Event()
            def pause_login(connection, cursor, statement, params, context, executemany):
                if 'user_account.username =' in statement and 'FOR UPDATE' in statement:
                    locked.set()
                    assert release.wait(timeout=20)
                elif 'role_code' in statement and 'FOR UPDATE' in statement:
                    attempted.set()
            event.listen(engine, 'after_cursor_execute', pause_login)
            def login():
                with factory() as db:
                    return authenticate(db, 'synthetic-2', password, ip_address=None, user_agent=None)
            def disable():
                with factory() as db:
                    return update_status(db, 2, StatusUpdate(account_status='LOCKED'), 1, None)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    login_future = pool.submit(login)
                    assert locked.wait(timeout=10)
                    disable_future = pool.submit(disable)
                    assert attempted.wait(timeout=10)
                    release.set()
                    assert login_future.result(timeout=15) is not None
                    disable_future.result(timeout=15)
            finally:
                release.set()
                event.remove(engine, 'after_cursor_execute', pause_login)
            with factory() as db:
                assert db.get(UserAccount, 2).account_status == 'LOCKED'
                sessions = list(db.scalars(select(AuthSession).where(AuthSession.user_id == 2)))
                assert len(sessions) == 1 and all(row.revoked_at for row in sessions)
            # Reverse order: an already locked account cannot issue another session.
            with factory() as db:
                assert authenticate(db, 'synthetic-2', password, ip_address=None, user_agent=None) is None
        print('concurrency checks passed')
    finally:
        with engine.begin() as db:
            db.execute(text('DROP DATABASE phase3b_synthetic'))
        engine.dispose()


if __name__ == '__main__':
    main(*sys.argv[1:])
