"""Standalone probe: only connects to a validated disposable Unix socket."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
import sys
from threading import Event
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from app import database
from app.models import Base, UserAccount, UserRole, Role, AuthSession
from app.schemas.administration import StatusUpdate
from app.schemas.auth_activity import ActivityFilters, SessionFilters
from app.services import auth_service
from app.services.administration_service import update_status
from app.services.auth_activity_service import activities, sessions
from app.security.passwords import hash_password


def main(socket):
    socket = Path(socket).resolve()
    assert socket.parent.parent == Path('/tmp') and socket.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket.stat().st_mode)
    options = {'hide_parameters': True, 'connect_args': {'unix_socket':str(socket), 'connect_timeout':5}}
    root = sa.create_engine('mysql+pymysql://root@localhost/', **options)
    with root.begin() as db:
        db.exec_driver_sql('CREATE DATABASE phase10_synthetic CHARACTER SET utf8mb4')
    engine = sa.create_engine('mysql+pymysql://root@localhost/phase10_synthetic', **options)
    database.engine = engine
    cfg = Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    command.upgrade(cfg, '20260924_01')
    with engine.begin() as db:
        db.execute(sa.text("INSERT INTO user_account (username,password_hash,account_status) VALUES ('legacy','synthetic','INACTIVE')"))
    command.upgrade(cfg, '20261005_01')
    with engine.connect() as db:
        assert db.scalar(sa.text('SELECT account_status FROM user_account')) == 'INACTIVE'
        col = next(c for c in sa.inspect(db).get_columns('user_account') if c['name'] == 'account_status')
        assert col['type'].enums == ['ACTIVE','INACTIVE','LOCKED','SUSPENDED','DISABLED']
        context = MigrationContext.configure(db, opts={'compare_type': True, 'include_object':
            lambda obj, name, kind, reflected, compare_to: kind != 'table' or name == 'user_account'})
        assert compare_metadata(context, Base.metadata) == []
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory.begin() as db:
        db.add(Role(role_id=1, role_code='SYSTEM_ADMIN', role_name='Synthetic Administrator', is_active=True))
        for uid, username in [(2, 'admin-synthetic'), (3, 'target-synthetic')]:
            db.add(UserAccount(user_id=uid, username=username, password_hash=hash_password('Synthetic-password-123!'), account_status='ACTIVE'))
        db.flush(); db.add(UserRole(user_id=2, role_id=1, assigned_at=auth_service.utc_now()))
    with factory() as db:
        auth_service.authenticate(db, 'admin-synthetic', 'Synthetic-password-123!', ip_address=None, user_agent='Probe')
    # Pause a login while it owns the account lock. Suspension must then revoke
    # the newly issued session as part of its own transaction.
    entered, release = Event(), Event()
    original = auth_service.verify_password
    def paused(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    auth_service.verify_password = paused
    def login():
        with factory() as db:
            return auth_service.authenticate(db, 'target-synthetic', 'Synthetic-password-123!', ip_address=None, user_agent='Probe')
    def suspend():
        with factory() as db:
            return update_status(db, 3, StatusUpdate(account_status='SUSPENDED', reason='Synthetic review'), 2, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(login); assert entered.wait(10)
        second = pool.submit(suspend)
        release.set()
        assert first.result(timeout=15) and second.result(timeout=15).account_status == 'SUSPENDED'
    auth_service.verify_password = original
    with factory() as db:
        assert db.get(UserAccount, 3).account_status == 'SUSPENDED'
        assert all(row.revoked_at for row in db.scalars(sa.select(AuthSession).where(AuthSession.user_id == 3)))
        data = activities(db, ActivityFilters(user_id=3))
        assert {r['activity_type'] for r in data['items']} == {'LOGIN_SUCCESS','ACCOUNT_SUSPENDED','SESSION_REVOKED'}
        assert sessions(db, SessionFilters(user_id=3), 0)['total'] == 0
    with factory() as db:
        assert auth_service.authenticate(db, 'target-synthetic', 'Synthetic-password-123!', ip_address=None, user_agent=None) is None
    try:
        command.downgrade(cfg, '20260924_01')
        raise AssertionError('Lossy downgrade must be refused')
    except RuntimeError as exc:
        assert 'downgrade refused' in str(exc)
    with factory() as db:
        update_status(db, 3, StatusUpdate(account_status='ACTIVE'), 2, None, expected_status='SUSPENDED')
    command.downgrade(cfg, '20260924_01')
    assert 'suspension_reason' not in {c['name'] for c in sa.inspect(engine).get_columns('user_account')}
    engine.dispose(); root.dispose()
    print('Phase 10 isolated MySQL checks passed')


if __name__ == '__main__':
    main(sys.argv[1])
