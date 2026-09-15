from datetime import datetime
from io import StringIO
from pathlib import Path
import re

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.models import Base
from test_phase_2a_models import TABLES
from test_phase_2b_models import TABLES as PHASE_2B_TABLES
from test_phase_2c_models import TABLES as PHASE_2C_TABLES
from test_phase_2d_models import TABLES as PHASE_2D_TABLES

ROOT = Path(__file__).resolve().parents[1]
REVISION = "20260914_01"
PHASE_2B = "20260914_02"
PHASE_2C = "20260914_03"
PHASE_2D = "20260914_04"
HEAD = "20260915_01"


def config(buffer=None):
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def revision(revision_id=REVISION):
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [HEAD]
    return scripts.get_revision(revision_id).module


def test_offline_mysql_upgrade_and_downgrade(monkeypatch):
    from app.database import engine

    def no_connection():
        pytest.fail("Offline migration attempted to connect to MySQL")

    monkeypatch.setattr(engine, "connect", no_connection)
    upgrade = StringIO()
    command.upgrade(config(upgrade), REVISION, sql=True)
    sql = upgrade.getvalue()
    created = re.findall(r"CREATE TABLE `?([a-z_]+)`? \(", sql)
    assert set(created) == TABLES | {"alembic_version"}
    assert "ENUM('M','F','Other')" in sql
    assert "ENUM('ACTIVE','INACTIVE','LOCKED')" in sql
    assert sql.count("AUTO_INCREMENT") == 10
    assert sql.count("ENGINE=InnoDB") == 12
    assert "synthetic-test-only" not in sql
    assert "CURRENT_TIMESTAMP" in sql
    for name in TABLES:
        table = Base.metadata.tables[name]
        for fk in table.foreign_keys:
            assert created.index(fk.column.table.name) < created.index(table.name)
    downgrade = StringIO()
    command.downgrade(config(downgrade), f"{REVISION}:base", sql=True)
    dropped = re.findall(r"DROP TABLE `?([a-z_]+)`?;", downgrade.getvalue())
    assert dropped == list(reversed([name for name in created if name != "alembic_version"]))
    # MySQL can reject dropping an index while an FK still depends on it.
    # Dropping the table itself removes its indexes and constraints together.
    assert "DROP INDEX" not in downgrade.getvalue()


@pytest.mark.parametrize("revision_id", [REVISION, PHASE_2B, PHASE_2C, PHASE_2D, HEAD])
def test_frozen_migration_matches_model_metadata(monkeypatch, revision_id):
    class Recorder:
        def __init__(self):
            self.metadata = sa.MetaData()

        @staticmethod
        def f(name):
            return name

        def create_table(self, name, *elements, **options):
            sa.Table(name, self.metadata, *elements, **options)

        def create_index(self, name, table_name, columns, **options):
            table = self.metadata.tables[table_name]
            sa.Index(name, *(table.c[c] for c in columns), **options)

    migration = revision(revision_id)
    recorder = Recorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()
    expected = {REVISION: TABLES, PHASE_2B: PHASE_2B_TABLES, PHASE_2C: PHASE_2C_TABLES, PHASE_2D: PHASE_2D_TABLES, HEAD: {"auth_session"}}[revision_id]
    assert set(recorder.metadata.tables) == expected

    def signature(table):
        def column(c):
            return (c.name, str(c.type.compile(dialect=mysql.dialect())), c.nullable,
                    c.autoincrement if c.primary_key else None,
                    str(c.server_default.arg) if c.server_default is not None else None)

        return (
            [column(c) for c in table.columns],
            {(type(c).__name__, str(c.name), tuple(c.columns.keys())) for c in table.constraints},
            {(str(fk.name), tuple((e.parent.name, e.target_fullname) for e in fk.elements),
              fk.ondelete, fk.onupdate) for fk in table.foreign_key_constraints},
            {(str(i.name), tuple(i.columns.keys()), i.unique) for i in table.indexes},
            dict(table.dialect_kwargs),
            {(str(c.name), str(c.sqltext)) for c in table.constraints if isinstance(c, sa.CheckConstraint)},
        )

    for name in expected:
        model = Base.metadata.tables[name]
        assert signature(recorder.metadata.tables[name]) == signature(model), name


@pytest.fixture
def migrated_connection():
    # SQLite checks relational behavior with synthetic explicit BIGINT IDs only.
    # MySQL-native ENUM and AUTO_INCREMENT are checked by offline MySQL DDL above.
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        with Operations.context(MigrationContext.configure(connection)):
            revision().upgrade()
        yield connection
        with Operations.context(MigrationContext.configure(connection)):
            revision().downgrade()
        assert sa.inspect(connection).get_table_names() == []
    engine.dispose()


def test_relational_constraints_and_round_trip(migrated_connection):
    c = migrated_connection
    tables = Base.metadata.tables
    assert set(sa.inspect(c).get_table_names()) == TABLES
    c.execute(tables["user_account"].insert(), [
        dict(user_id=i, username=f"test{i}", password_hash="synthetic-hash", account_status="ACTIVE")
        for i in (1, 2)
    ])
    for table, key, code in [("staff", "staff_id", "staff_code"),
                             ("patient", "patient_id", "patient_code")]:
        c.execute(tables[table].insert(), [
            {key: i, code: f"TEST-{i}", "first_name": "Test", "last_name": "Person"}
            for i in (1, 2)
        ])
        link = tables[f"{table}_account_link"]
        c.execute(link.insert().values(**{key: 1, "user_id": 1}))
        for values in [{key: 1, "user_id": 2}, {key: 2, "user_id": 1},
                       {key: 99, "user_id": 2}, {key: 2, "user_id": 99}]:
            with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                c.execute(link.insert().values(**values))
    c.execute(tables["role"].insert().values(role_id=1, role_code="TEST", role_name="Test"))
    c.execute(tables["permission"].insert().values(
        permission_id=1, permission_code="TEST", permission_name="Test"
    ))
    assignment = dict(user_id=1, role_id=1, assigned_at=datetime(2026, 1, 1), assigned_by=2)
    c.execute(tables["user_role"].insert().values(user_role_id=1, **assignment))
    c.execute(tables["role_permission"].insert().values(
        role_permission_id=1, role_id=1, permission_id=1
    ))
    invalid = [
        tables["user_role"].insert().values(user_role_id=2, **assignment),
        tables["user_role"].insert().values(user_role_id=3, **{**assignment, "user_id": 2, "assigned_by": 99}),
        tables["role_permission"].insert().values(role_permission_id=2, role_id=1, permission_id=1),
        tables["user_account"].delete().where(tables["user_account"].c.user_id == 2),
    ]
    for statement in invalid:
        with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            c.execute(statement)
    stored = c.execute(sa.select(tables["staff"])).first()
    assert stored.is_active is True
    assert stored.created_at is not None


def test_alembic_online_environment_reuses_application_engine(monkeypatch):
    from app import database

    # Substitute only the existing app engine, so the real env.py path runs safely.
    engine = sa.create_engine("sqlite://")
    monkeypatch.setattr(database, "engine", engine)
    try:
        command.upgrade(config(), "head")
        with engine.connect() as connection:
            assert set(sa.inspect(connection).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
            assert MigrationContext.configure(connection).get_current_revision() == HEAD
        command.check(config())
        command.downgrade(config(), "base")
        with engine.connect() as connection:
            assert sa.inspect(connection).get_table_names() == ["alembic_version"]
            assert MigrationContext.configure(connection).get_current_revision() is None
    finally:
        engine.dispose()
