"""Execute Alembic only on a disposable Unix-socket MySQL instance."""
from datetime import datetime
from pathlib import Path
import stat
import sys
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from app import database
from app.models import Base, BlockchainEvent
from app.cli.bootstrap_blockchain_nodes import ensure_blockchain_nodes


def assert_outbox_schema(engine):
    # Scope parity to the changed tables. An existing MFA nonce is reflected as
    # TINYBLOB vs LargeBinary(12); that unrelated legacy difference is not Phase 8B.
    def include_object(obj, name, kind, reflected, compare_to):
        return kind != 'table' or name in {'lab_report', 'blockchain_event'}
    with engine.connect() as db:
        context = MigrationContext.configure(db, opts={'compare_type': True,
            'compare_server_default': True, 'include_object': include_object})
        assert compare_metadata(context, Base.metadata) == []


def main(socket):
    socket = Path(socket).resolve()
    assert socket.parent.parent == Path('/tmp') and socket.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket.stat().st_mode)
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket), 'connect_timeout': 5}}
    admin = sa.create_engine('mysql+pymysql://root@localhost/', **options)
    with admin.begin() as db:
        db.exec_driver_sql('CREATE DATABASE phase8b_synthetic CHARACTER SET utf8mb4')
    engine = sa.create_engine('mysql+pymysql://root@localhost/phase8b_synthetic', **options)
    # Real env.py uses ONLY this substituted disposable engine.
    database.engine = engine
    cfg = Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    try:
        command.upgrade(cfg, '20260920_01')
        with engine.begin() as db:
            db.exec_driver_sql("INSERT INTO blockchain_node (node_code,port,node_role) VALUES ('node1',7051,'Org1MSP peer1')")
        for status in ('PENDING', 'ACCEPTED', 'REJECTED'):
            with engine.begin() as db:
                db.execute(sa.text("INSERT INTO blockchain_event (event_uuid,origin_node_id,entity_type,entity_id,event_type,record_hash,event_status) VALUES (:uuid,1,'REPORT',1,'REPORT_RELEASED',:hash,:status)"), {'uuid':str(uuid4()), 'hash':'a'*64, 'status':status})
            try:
                command.upgrade(cfg, 'head')
                raise AssertionError('Nonempty migration should abort')
            except RuntimeError as exc:
                assert 'Manual review' in str(exc)
            with engine.begin() as db:
                assert db.scalar(sa.text('SELECT event_status FROM blockchain_event')) == status
                assert 'blockchain_entity_uuid' not in {c['name'] for c in sa.inspect(db).get_columns('lab_report')}
                assert db.scalar(sa.text('SELECT version_num FROM alembic_version')) == '20260920_01'
                db.exec_driver_sql('DELETE FROM blockchain_event')  # Disposable synthetic fixture only.
        # Historical reports exist before the migration, and must remain unassigned.
        with engine.begin() as db:
            db.exec_driver_sql("INSERT INTO user_account (username,password_hash,account_status) VALUES ('synthetic','not-a-login','ACTIVE')")
            db.exec_driver_sql("INSERT INTO facility_profile (facility_name) VALUES ('Synthetic')")
            db.exec_driver_sql("INSERT INTO patient (patient_code,first_name,last_name,birth_date) VALUES ('SYNTH','Synthetic','Only','2000-01-01')")
            db.exec_driver_sql("INSERT INTO lab_order (order_code,patient_id,order_date,priority,status) VALUES ('SYNTH',1,NOW(),'ROUTINE','REQUESTED')")
            for number in (1, 2):
                db.execute(sa.text("INSERT INTO lab_report (report_code,order_id,facility_id,version_no,report_status,generated_by_user_id,generated_at) VALUES (:code,1,1,:version,'RELEASED',1,NOW())"), {'code':f'SYNTH-{number}', 'version':number})
        command.upgrade(cfg, 'head')
        assert_outbox_schema(engine)
        with engine.connect() as db:
            inspector = sa.inspect(db)
            assert db.scalar(sa.text('SELECT version_num FROM alembic_version')) == '20260924_01'
            assert db.execute(sa.text('SELECT blockchain_entity_uuid FROM lab_report')).scalars().all() == [None, None]
            # Full columns/defaults/indexes/FKs of both changed tables are compared above.
            cols = {c['name']: c for c in inspector.get_columns('blockchain_event')}
            assert cols['event_status']['type'].enums == ['PENDING','PROCESSING','CONFIRMED','FAILED','DEAD']
            assert cols['occurred_at']['type'].fsp == cols['updated_at']['type'].fsp == 6
            assert cols['attempt_count']['type'].unsigned and cols['fabric_block_number']['type'].unsigned
            assert any(fk['constrained_columns'] == ['predecessor_event_id'] and fk['referred_table'] == 'blockchain_event' for fk in inspector.get_foreign_keys('blockchain_event'))
            assert len(inspector.get_check_constraints('blockchain_event')) == 4
        factory = sessionmaker(bind=engine)
        with factory.begin() as db:
            assert ensure_blockchain_nodes(db) == ['node2','node3','node4']
            assert ensure_blockchain_nodes(db) == []
        now = datetime(2026,9,24,12,34,56,123456)
        table = BlockchainEvent.__table__
        base = dict(event_uuid=str(uuid4()), origin_node_id=1, entity_type='REPORT', entity_id=1,
            event_type='REPORT_RELEASED', record_hash='a'*64, deduplication_key='REPORT_RELEASED:1',
            entity_reference='11111111-1111-4111-8111-111111111111', canonical_payload='{}',
            occurred_at=now, next_attempt_at=now)
        with engine.begin() as db:
            event_id = db.execute(table.insert().values(**base)).inserted_primary_key[0]
            stored = db.execute(sa.select(table).where(table.c.event_id == event_id)).mappings().one()
            assert stored['occurred_at'] == now and stored['next_attempt_at'] == now
            assert stored['event_status'] == 'PENDING' and stored['attempt_count'] == 0
            assert stored['updated_at'] is not None
            invalid = [
                {'event_status':'ACCEPTED'}, {'attempt_count':-1}, {'fabric_block_number':-1},
                {'event_status':'PROCESSING'},
                {'event_status':'PROCESSING','processing_started_at':now,'lease_token':str(uuid4())},
                {'event_status':'CONFIRMED'},
                {'event_status':'CONFIRMED','fabric_transaction_id':'b'*64,'confirmed_at':now,'fabric_validation_code':None},
                {'event_status':'CONFIRMED','fabric_transaction_id':'b'*64,'confirmed_at':now,'fabric_validation_code':1},
                {'event_type':'REPORT_REVOKED'}, {'event_type':'REPORT_SUPERSEDED'},
                {'predecessor_event_id':999999},
            ]
            for change in invalid:
                savepoint = db.begin_nested()
                try:
                    db.execute(table.update().where(table.c.event_id == event_id).values(**change))
                except sa.exc.DBAPIError:
                    savepoint.rollback()
                else:
                    savepoint.rollback()
                    raise AssertionError(f'Database accepted invalid fields: {list(change)}')
            db.execute(table.update().where(table.c.event_id == event_id).values(event_status='CONFIRMED',
                fabric_transaction_id='b'*64, confirmed_at=now, fabric_validation_code=0))
            assert db.scalar(sa.select(table.c.fabric_block_number)) is None
            db.execute(table.update().values(fabric_block_number=18446744073709551615))
            assert db.scalar(sa.select(table.c.fabric_block_number)) == 18446744073709551615
            for change in ({'event_uuid':str(uuid4())}, {'deduplication_key':'other'}):
                savepoint = db.begin_nested()
                try:
                    db.execute(table.insert().values(**{**base, **change}))
                except sa.exc.IntegrityError: savepoint.rollback()
                else: raise AssertionError('Missing event uniqueness')
            entity = '11111111-1111-4111-8111-111111111111'
            db.execute(sa.text('UPDATE lab_report SET blockchain_entity_uuid=:uuid WHERE report_id=1'), {'uuid':entity})
            savepoint = db.begin_nested()
            try:
                db.execute(sa.text('UPDATE lab_report SET blockchain_entity_uuid=:uuid WHERE report_id=2'), {'uuid':entity})
            except sa.exc.IntegrityError: savepoint.rollback()
            else: raise AssertionError('Missing report UUID uniqueness')
        try:
            command.downgrade(cfg, '20260920_01')
            raise AssertionError('Downgrade must preserve captured data')
        except RuntimeError as exc: assert 'contains rows' in str(exc)
        with engine.begin() as db: db.execute(table.delete())
        try:
            command.downgrade(cfg, '20260920_01')
            raise AssertionError('Downgrade must preserve report identities')
        except RuntimeError as exc: assert 'identities exist' in str(exc)
        with engine.begin() as db: db.exec_driver_sql('UPDATE lab_report SET blockchain_entity_uuid=NULL')
        command.downgrade(cfg, '20260920_01')
        command.upgrade(cfg, 'head')
        assert_outbox_schema(engine)
        print('Phase 8B MySQL migration checks passed')
    finally:
        engine.dispose()
        with admin.begin() as db: db.exec_driver_sql('DROP DATABASE phase8b_synthetic')
        admin.dispose()


if __name__ == '__main__': main(sys.argv[1])
