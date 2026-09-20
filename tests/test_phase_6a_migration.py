"""Exactly one approved security table, reversible DDL and preserved history."""
from datetime import datetime, timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.models import Base
from test_phase_2a_migration import config, revision, PHASE_6A as HEAD, PHASE_3A, HEAD as CURRENT_HEAD
from test_phase_2d_models import TABLES, PREVIOUS_TABLES


def test_activation_model_and_exact_infrastructure_scope():
    assert set(Base.metadata.tables) == TABLES | PREVIOUS_TABLES | {'auth_session', 'patient_activation_token', 'user_totp_mfa', 'mfa_recovery_code', 'mfa_challenge'}
    table = Base.metadata.tables['patient_activation_token']
    assert set(table.c.keys()) == {'activation_token_id', 'patient_id', 'token_hash', 'issued_by_user_id',
        'created_at', 'expires_at', 'used_at', 'revoked_at'}
    assert str(table.c.token_hash.type.compile(dialect=mysql.dialect())) == 'CHAR(64)'
    for name in ('activation_token_id', 'patient_id', 'issued_by_user_id'):
        assert str(table.c[name].type.compile(dialect=mysql.dialect())) == 'BIGINT'
    assert table.c.activation_token_id.primary_key and table.c.activation_token_id.autoincrement
    assert {c.name for c in table.c if c.nullable} == {'used_at', 'revoked_at'}
    assert {fk.target_fullname for fk in table.foreign_keys} == {'patient.patient_id', 'user_account.user_id'}
    assert all(fk.ondelete is None for fk in table.foreign_keys)
    assert {tuple(index.columns.keys()) for index in table.indexes} == {('patient_id',), ('issued_by_user_id',), ('expires_at',)}
    assert any(isinstance(c, sa.UniqueConstraint) and tuple(c.columns.keys()) == ('token_hash',) for c in table.constraints)


def test_one_new_head_and_offline_mysql_scope():
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert HEAD == '20260916_01'
    assert scripts.get_revision(HEAD).down_revision == PHASE_3A == '20260915_01'
    assert len(list(scripts.walk_revisions(head=HEAD))) == 6
    output = StringIO()
    command.upgrade(config(output), f'{PHASE_3A}:{HEAD}', sql=True)
    sql = output.getvalue()
    assert re.findall(r'CREATE TABLE `?([a-z_]+)`? \(', sql) == ['patient_activation_token']
    assert sql.count('AUTO_INCREMENT') == 1 and sql.count('FOREIGN KEY') == 2
    assert 'CHAR(64) NOT NULL' in sql and 'UNIQUE (token_hash)' in sql
    assert 'ENGINE=InnoDB' in sql and 'CHARSET=utf8mb4' in sql
    assert sql.count('CREATE INDEX') == 3
    for forbidden in ('CASCADE', 'ALTER TABLE', 'INSERT INTO', 'password', 'activation_token VARCHAR'):
        assert forbidden not in sql
    output = StringIO()
    command.downgrade(config(output), f'{HEAD}:{PHASE_3A}', sql=True)
    assert re.findall(r'DROP TABLE `?([a-z_]+)`?;', output.getvalue()) == ['patient_activation_token']


def test_activation_constraints_and_downgrade_preserve_existing_data():
    engine = sa.create_engine('sqlite://')
    tables = Base.metadata.tables
    with engine.connect() as db:
        db.exec_driver_sql('PRAGMA foreign_keys=ON')
        scripts = ScriptDirectory.from_config(config())
        with Operations.context(MigrationContext.configure(db)):
            for rev in reversed(list(scripts.walk_revisions(head=PHASE_3A))): rev.module.upgrade()
        db.execute(tables['user_account'].insert().values(user_id=1, username='synthetic', password_hash='synthetic', account_status='ACTIVE'))
        db.execute(tables['patient'].insert().values(patient_id=1, patient_code='SYNTH', first_name='Synthetic', last_name='Patient'))
        previous = set(sa.inspect(db).get_table_names())
        historical = sa.MetaData()
        historical.reflect(bind=db)
        before = {name: db.execute(sa.select(historical.tables[name])).all() for name in previous}
        with Operations.context(MigrationContext.configure(db)): revision(HEAD).upgrade()
        now = datetime(2026, 9, 16)
        table = tables['patient_activation_token']
        values = dict(activation_token_id=1, patient_id=1, issued_by_user_id=1, token_hash='a'*64,
                      created_at=now, expires_at=now+timedelta(minutes=30))
        db.execute(table.insert().values(**values))
        for changes in ({'patient_id': 999}, {'issued_by_user_id': 999}, {'token_hash': 'a'*64},
                        *({name: None} for name in ('patient_id', 'issued_by_user_id', 'token_hash', 'created_at', 'expires_at'))):
            with db.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                db.execute(table.insert().values(**{**values, 'activation_token_id': 2, 'token_hash': 'b'*64, **changes}))
        for name in ('patient', 'user_account'):
            with db.begin_nested(), pytest.raises(sa.exc.IntegrityError): db.execute(tables[name].delete())
        with Operations.context(MigrationContext.configure(db)): revision(HEAD).downgrade()
        assert set(sa.inspect(db).get_table_names()) == previous
        assert {name: db.execute(sa.select(historical.tables[name])).all() for name in previous} == before
    engine.dispose()


def test_prior_session_migration_unchanged():
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20260915_01_phase_3a_auth_session.py'
    assert sha256(path.read_bytes()).hexdigest() == 'd4145114aa54e23fb233b00290d3d9c98a8f853f8811549101ebcb4a29dcd754'
