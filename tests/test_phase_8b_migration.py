"""Migration syntax, online guard, schema and real isolated MySQL validation."""
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys

from alembic import command
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy.dialects import mysql
from app.models import Base
from test_phase_2a_migration import config, revision, HEAD, PHASE_6B
from test_phase_3b_mysql import disposable_mysql
from phase8b_schema import EVENT_ADDITIONS, STATUSES


def test_revision_import_schema_types_and_head():
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [HEAD] == ['20260924_01']
    migration = revision(HEAD)
    assert migration.down_revision == PHASE_6B == '20260920_01'
    assert set(migration.NEW_COLUMNS) == EVENT_ADDITIONS
    table = Base.metadata.tables['blockchain_event']
    assert table.c.event_status.type.enums == STATUSES
    assert str(table.c.occurred_at.type.compile(dialect=mysql.dialect())) == 'DATETIME(6)'
    assert str(table.c.attempt_count.type.compile(dialect=mysql.dialect())) == 'INTEGER UNSIGNED'
    assert str(table.c.fabric_block_number.type.compile(dialect=mysql.dialect())) == 'BIGINT UNSIGNED'
    assert 'ascii_bin' in str(Base.metadata.tables['lab_report'].c.blockchain_entity_uuid.type.compile(dialect=mysql.dialect()))
    assert {str(c.name) for c in table.constraints if c.__class__.__name__ == 'CheckConstraint'} == {'ck_blockchain_event_' + name for name in migration.CHECKS}


def test_offline_guard_cannot_be_bypassed():
    output = StringIO()
    with pytest.raises(RuntimeError, match='online empty-table check'):
        command.upgrade(config(output), f'{PHASE_6B}:{HEAD}', sql=True)
    assert 'ALTER TABLE' not in output.getvalue()


def test_mysql_migration_and_constraints(disposable_mysql):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root/'tests/mysql_phase8b_probe.py'), disposable_mysql],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Phase 8B MySQL migration checks passed' in result.stdout
