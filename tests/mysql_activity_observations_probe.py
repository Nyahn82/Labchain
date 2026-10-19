"""Socket-only disposable migration probe; never reads application database settings."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from scripts.mysql_migration_rehearsal import ENVIRONMENT
from mysql_release_rehearsal_probe import validated_socket, rows_snapshot


def main(value):
    socket = validated_socket(value)
    options = dict(hide_parameters=True, connect_args={'unix_socket': str(socket), 'connect_timeout': 5})
    admin = sa.create_engine('mysql+pymysql://root@localhost', **options)
    with admin.connect() as c:
        identity = c.exec_driver_sql('SELECT @@socket, @@datadir, @@skip_networking').one()
        assert Path(identity[0]).resolve() == socket
        assert Path(identity[1]).resolve() == socket.parent/'data' and identity[2] == 1
    with admin.begin() as c:
        c.exec_driver_sql('CREATE DATABASE rhu_activity_synthetic CHARACTER SET utf8mb4')
    engine = sa.create_engine('mysql+pymysql://root@localhost/rhu_activity_synthetic', **options)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=socket.parent) as directory:
        folder = Path(directory)
        (folder/'env.py').write_text(ENVIRONMENT)
        shutil.copytree(root/'migrations/versions', folder/'versions', ignore=shutil.ignore_patterns('__pycache__'))
        cfg = Config()
        cfg.set_main_option('script_location', str(folder))
        # This newly created private server has no application or import writers.
        os.environ['RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED'] = '1'
        with engine.connect() as c:
            cfg.attributes['verified_connection'] = c
            command.upgrade(cfg, '20261018_01')
            c.exec_driver_sql("INSERT INTO user_account(user_id,username,password_hash,account_status) VALUES (1,'synthetic','synthetic-hash','ACTIVE')")
            c.exec_driver_sql("INSERT INTO role(role_id,role_code,role_name,is_active) VALUES (1,'SYSTEM_ADMIN','Synthetic admin',1)")
            c.exec_driver_sql("INSERT INTO user_role(user_role_id,user_id,role_id,assigned_at) VALUES (1,1,1,UTC_TIMESTAMP())")
            c.exec_driver_sql("INSERT INTO staff(staff_id,staff_code,first_name,last_name,is_active) VALUES (1,'SYNTH-1','Synthetic','Staff',1)")
            c.exec_driver_sql('INSERT INTO staff_account_link(staff_id,user_id) VALUES (1,1)')
            now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
            c.execute(sa.text('INSERT INTO auth_session(session_id,user_id,token_hash,csrf_token_hash,created_at,expires_at) VALUES (1,1,:token,:csrf,:now,:expiry)'),
                      dict(token='a'*64, csrf='b'*64, now=now, expiry=now+timedelta(hours=1)))
            c.exec_driver_sql("INSERT INTO patient(patient_id,patient_code,first_name,last_name) VALUES (1,'SYNTH-P','Synthetic','Patient')")
            c.exec_driver_sql("INSERT INTO user_account(user_id,username,password_hash,account_status) VALUES (2,'synthetic-patient','synthetic-hash','ACTIVE')")
            for identifier in range(2, 7):
                c.execute(sa.text('INSERT INTO patient(patient_id,patient_code,first_name,last_name) VALUES (:id,:code,:first,:last)'),
                          dict(id=identifier, code=f'SYNTH-P-{identifier}', first='Synthetic', last='Patient'))
                c.execute(sa.text('INSERT INTO patient_activation_token(activation_token_id,patient_id,token_hash,created_at,expires_at,issued_by_user_id,used_at,revoked_at) VALUES (:id,:id,:token,:now,:expiry,1,:used,:revoked)'),
                          dict(id=identifier, token=str(identifier)*64, now=now,
                               expiry=now if identifier == 3 else now+timedelta(hours=1),
                               used=now if identifier in {5, 6} else None, revoked=now if identifier == 4 else None))
            c.exec_driver_sql('INSERT INTO patient_account_link(patient_id,user_id) VALUES (6,2)')
            c.commit()
            before = rows_snapshot(c)
            old_session = c.exec_driver_sql('SELECT * FROM auth_session').one()
            c.rollback()
            command.upgrade(cfg, '20261019_01')
            after = rows_snapshot(c)
            assert set(after) == set(before) | {'service_observation'}
            for table in before:
                if table not in {'auth_session', 'alembic_version'}:
                    assert after[table] == before[table], table
            new_session = c.exec_driver_sql('SELECT * FROM auth_session').one()
            assert tuple(new_session[:-1]) == tuple(old_session) and new_session[-1] is None
            assert after['service_observation'] == []
            assert 'ix_auth_session_last_activity_at' in {index['name'] for index in sa.inspect(c).get_indexes('auth_session')}
            c.rollback()
            command.upgrade(cfg, '20261019_01')
            assert rows_snapshot(c) == after
            c.rollback()
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            with Operations.context(MigrationContext.configure(c)):
                try:
                    ScriptDirectory.from_config(cfg).get_revision('20261019_01').module.downgrade()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Destructive downgrade was not refused')
        from app.models import AuthSession, Patient
        from app.models.service_observation import ServiceObservation
        from app.services.activity_observation_service import eligible_staff, observe_authenticated_activity, record_worker
        from app.services.patient_activation_service import activation_state_expression, patient_directory
        sessions = sessionmaker(bind=engine, autoflush=False)
        with sessions() as db:
            session = db.get(AuthSession, 1)
            observe_authenticated_activity(db, session, now.replace(microsecond=999999))
            assert db.get(AuthSession, 1).last_activity_at == now
            assert db.scalar(sa.select(sa.func.count()).select_from(AuthSession).where(*eligible_staff(AuthSession.user_id))) == 1
            expected = {1: 'NOT_ACTIVATED', 2: 'TOKEN_ACTIVE', 3: 'TOKEN_EXPIRED', 4: 'TOKEN_REVOKED', 5: 'REVIEW_REQUIRED', 6: 'ACTIVATED'}
            assert dict(db.execute(sa.select(Patient.patient_id, activation_state_expression(now))).all()) == expected
            assert patient_directory(db, page=1, page_size=1, activation_group='NOT_ACTIVATED', sort_by='name')['total'] == 5
            for state in expected.values():
                filtered = patient_directory(db, page=1, page_size=1, activation_state=state, sort_by='activation')
                assert filtered['total'] == 1
        observed_at = datetime.now(timezone.utc).replace(microsecond=999999)
        with patch('app.services.activity_observation_service.datetime') as clock:
            clock.now.return_value = observed_at
            record_worker(sessions)
        with sessions() as db:
            from app.services.dashboard_service import overview
            body = overview(db, 1)
            assert body['activation'] == {'not_activated': 5, 'review_required': 1}
            assert body['presence']['recently_active'] == 1
            assert body['signing'] == {'unassigned': 0, 'awaiting_signature': 0, 'awaiting_approval': 0}
            assert body['services'][-1]['status'] == 'HEALTHY'
            assert db.get(ServiceObservation, 'blockchain_worker').status == 'HEALTHY'
            assert db.get(ServiceObservation, 'blockchain_worker').checked_at == observed_at.replace(tzinfo=None, microsecond=0)
            db.get(ServiceObservation, 'blockchain_worker').status = 'UNHEALTHY'
            db.flush()
            db.rollback()
            assert db.get(ServiceObservation, 'blockchain_worker').status == 'HEALTHY'
        with engine.connect() as c:
            final = rows_snapshot(c)
            for table in before:
                if table not in {'auth_session', 'alembic_version'}:
                    assert final[table] == before[table], table
    engine.dispose()
    admin.dispose()
    print('PASS activity migration, historical preservation, native queries and rollback')


if __name__ == '__main__':
    main(sys.argv[1])
