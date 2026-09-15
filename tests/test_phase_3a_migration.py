"""Session infrastructure DDL, relational constraints, and deployed history checks."""

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
from test_phase_2a_migration import config, revision, HEAD, PHASE_2D
from test_phase_2d_models import TABLES, PREVIOUS_TABLES


def test_session_schema_and_only_one_new_infrastructure_table():
    assert set(Base.metadata.tables) == TABLES | PREVIOUS_TABLES | {"auth_session"}
    table = Base.metadata.tables["auth_session"]
    assert set(table.c.keys()) == {
        "session_id", "user_id", "token_hash", "csrf_token_hash", "created_at",
        "expires_at", "revoked_at", "ip_address", "user_agent",
    }
    assert str(table.c.session_id.type.compile(dialect=mysql.dialect())) == "BIGINT"
    assert table.c.session_id.primary_key and table.c.session_id.autoincrement
    assert {fk.target_fullname for fk in table.c.user_id.foreign_keys} == {"user_account.user_id"}
    for column in ("token_hash", "csrf_token_hash"):
        assert str(table.c[column].type.compile(dialect=mysql.dialect())) == "CHAR(64)"
        assert not table.c[column].nullable
    assert any(isinstance(c, sa.UniqueConstraint) and tuple(c.columns.keys()) == ("token_hash",)
               for c in table.constraints)
    assert {tuple(i.columns.keys()) for i in table.indexes} == {("user_id",), ("expires_at",), ("revoked_at",)}
    assert all(fk.ondelete is None for fk in table.foreign_keys)


def test_new_head_offline_mysql_upgrade_and_downgrade():
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [HEAD] == ["20260915_01"]
    assert scripts.get_revision(HEAD).down_revision == PHASE_2D == "20260914_04"
    assert len(list(scripts.walk_revisions())) == 5
    output = StringIO()
    command.upgrade(config(output), f"{PHASE_2D}:{HEAD}", sql=True)
    sql = output.getvalue()
    assert re.findall(r"CREATE TABLE `?([a-z_]+)`? \(", sql) == ["auth_session"]
    assert "ENGINE=InnoDB" in sql and "CHARSET=utf8mb4" in sql
    assert sql.count("AUTO_INCREMENT") == 1
    assert "FOREIGN KEY(user_id) REFERENCES user_account (user_id)" in sql
    assert "UNIQUE (token_hash)" in sql
    assert sql.count("CHAR(64) NOT NULL") == 2
    assert sql.count("CREATE INDEX") == 3
    assert "CASCADE" not in sql and "ALTER TABLE" not in sql and "INSERT INTO" not in sql
    output = StringIO()
    command.downgrade(config(output), f"{HEAD}:{PHASE_2D}", sql=True)
    assert re.findall(r"DROP TABLE `?([a-z_]+)`?;", output.getvalue()) == ["auth_session"]


def test_upgrade_constraints_and_downgrade_preserve_previous_data():
    engine = sa.create_engine("sqlite://")
    tables = Base.metadata.tables
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        scripts = ScriptDirectory.from_config(config())
        with Operations.context(MigrationContext.configure(connection)):
            for rev in reversed(list(scripts.walk_revisions(head=PHASE_2D))):
                rev.module.upgrade()
        connection.execute(tables["user_account"].insert().values(
            user_id=1, username="synthetic", password_hash="synthetic-only", account_status="ACTIVE",
        ))
        before = {name: connection.execute(sa.select(tables[name])).all() for name in TABLES | PREVIOUS_TABLES}
        with Operations.context(MigrationContext.configure(connection)):
            revision(HEAD).upgrade()
        from datetime import datetime, timedelta
        now = datetime(2026, 9, 15)
        values = dict(session_id=1, user_id=1, token_hash="a" * 64, csrf_token_hash="b" * 64,
                      created_at=now, expires_at=now + timedelta(hours=8))
        connection.execute(tables["auth_session"].insert().values(**values))
        for changes in ({"session_id": 2}, {"session_id": 2, "token_hash": "c" * 64, "user_id": 999},
                        {"session_id": 2, "token_hash": None}, {"session_id": 2, "csrf_token_hash": None}):
            with connection.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                connection.execute(tables["auth_session"].insert().values(**{**values, **changes}))
        with connection.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            connection.execute(tables["user_account"].delete())
        with Operations.context(MigrationContext.configure(connection)):
            revision(HEAD).downgrade()
        assert set(sa.inspect(connection).get_table_names()) == TABLES | PREVIOUS_TABLES
        assert {name: connection.execute(sa.select(tables[name])).all() for name in before} == before
    engine.dispose()


def test_phase_2d_migration_is_byte_for_byte_unchanged():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20260914_04_phase_2d_reporting_audit_blockchain_support.py"
    assert sha256(path.read_bytes()).hexdigest() == "ea8d20a39a99cb639c2680bfa09475e334866567020d01949368cf257506bc34"
