"""Additive security schema, historical sessions and immutable prior revisions."""
from datetime import datetime, timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from app.models import Base
from test_phase_2a_migration import config, revision, HEAD, PHASE_6A

NEW_TABLES = {'user_totp_mfa', 'mfa_recovery_code', 'mfa_challenge'}


def test_mfa_head_and_offline_scope():
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [HEAD] == ['20260920_01']
    assert scripts.get_revision(HEAD).down_revision == PHASE_6A == '20260916_01'
    output = StringIO()
    command.upgrade(config(output), f'{PHASE_6A}:{HEAD}', sql=True)
    sql = output.getvalue()
    assert set(re.findall(r'CREATE TABLE ([a-z_]+) \(', sql)) == NEW_TABLES
    assert 'ALTER TABLE auth_session ADD COLUMN mfa_verified_at DATETIME' in sql
    assert 'CASCADE' not in sql and sql.count('FOREIGN KEY') == 3
    assert sql.count('CREATE INDEX') == 3
    assert sql.count('CHAR(64) NOT NULL') == 2
    output = StringIO()
    command.downgrade(config(output), f'{HEAD}:{PHASE_6A}', sql=True)
    assert set(re.findall(r'DROP TABLE ([a-z_]+);', output.getvalue())) == NEW_TABLES


def test_mfa_constraints_and_session_assurance():
    tables = Base.metadata.tables
    for name in NEW_TABLES:
        table = tables[name]
        assert all(fk.ondelete is None for fk in table.foreign_keys)
        assert not {'secret', 'recovery_code', 'challenge_token'} & set(table.c.keys())
    assert tables['auth_session'].c.mfa_verified_at.nullable
    assert any(isinstance(c, sa.UniqueConstraint) and tuple(c.columns.keys()) == ('user_id',)
        for c in tables['user_totp_mfa'].constraints)
    for name, column in [('mfa_recovery_code', 'code_hash'), ('mfa_challenge', 'token_hash')]:
        assert any(isinstance(c, sa.UniqueConstraint) and tuple(c.columns.keys()) == (column,)
            for c in tables[name].constraints)


def test_upgrade_preserves_password_sessions_and_downgrade():
    engine = sa.create_engine('sqlite://')
    now = datetime(2026, 9, 20)
    with engine.begin() as db:
        db.exec_driver_sql('PRAGMA foreign_keys=ON')
        scripts = ScriptDirectory.from_config(config())
        with Operations.context(MigrationContext.configure(db)):
            for rev in reversed(list(scripts.walk_revisions(head=PHASE_6A))): rev.module.upgrade()
        tables = Base.metadata.tables
        db.execute(tables['user_account'].insert().values(user_id=1, username='synthetic', password_hash='synthetic', account_status='ACTIVE'))
        db.execute(tables['auth_session'].insert().values(session_id=1, user_id=1, token_hash='a'*64, csrf_token_hash='b'*64,
            created_at=now, expires_at=now+timedelta(hours=1)))
        before_tables = set(sa.inspect(db).get_table_names())
        before_session = db.exec_driver_sql('SELECT * FROM auth_session').one()
        with Operations.context(MigrationContext.configure(db)): revision(HEAD).upgrade()
        assert set(sa.inspect(db).get_table_names()) == before_tables | NEW_TABLES
        row = db.exec_driver_sql('SELECT * FROM auth_session').one()
        assert tuple(row[:-1]) == tuple(before_session) and row[-1] is None
        with Operations.context(MigrationContext.configure(db)): revision(HEAD).downgrade()
        assert set(sa.inspect(db).get_table_names()) == before_tables
        assert db.exec_driver_sql('SELECT * FROM auth_session').one() == before_session
    engine.dispose()


def test_all_prior_migrations_are_unchanged():
    hashes = {'20260916_01_phase_6a_patient_activation.py': '36b46f93385949c2c4dcdeb139653f5732db25e251e220a70634874bedfbdc23', '20260914_04_phase_2d_reporting_audit_blockchain_support.py': 'ea8d20a39a99cb639c2680bfa09475e334866567020d01949368cf257506bc34', '20260915_01_phase_3a_auth_session.py': 'd4145114aa54e23fb233b00290d3d9c98a8f853f8811549101ebcb4a29dcd754', '20260914_01_phase_2a_identity_auth.py': 'ad3f34d73c20c01fb810c056c28a95a0b5d44e930466020a80f09d9241e433ff', '20260914_02_phase_2b_laboratory_master_data.py': 'f31c42a50e766ee8f4e438c629bdd733f59df97e844805198b2e81806e1dfb32', '20260914_03_phase_2c_laboratory_workflow.py': '03e84df36ace7aa3d8216486bd6013dd7849b5ddae1a6453dc72e1a06eab2b26'}
    root = Path(__file__).resolve().parents[1]/"migrations/versions"
    for name, expected in hashes.items():
        assert sha256((root/name).read_bytes()).hexdigest() == expected
