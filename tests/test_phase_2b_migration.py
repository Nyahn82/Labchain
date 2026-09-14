from datetime import date
from decimal import Decimal
from io import StringIO
import re

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

from app.models import Base
from test_phase_2a_migration import config, revision, REVISION as PARENT, HEAD
from test_phase_2a_models import TABLES as PHASE_2A_TABLES
from test_phase_2b_models import TABLES

ORDER = [
    "lab_department", "sample_type", "test_catalog", "test_sample_type", "test_panel",
    "panel_section", "panel_test", "reference_range", "test_interpretation_rule",
]


def test_phase_2b_revision_and_offline_mysql_round_trip(monkeypatch):
    from app.database import engine

    def no_connection():
        pytest.fail("Offline SQL must not connect to MySQL")

    monkeypatch.setattr(engine, "connect", no_connection)
    migration = revision(HEAD)
    assert migration.down_revision == PARENT
    upgrade = StringIO()
    command.upgrade(config(upgrade), f"{PARENT}:{HEAD}", sql=True)
    sql = upgrade.getvalue()
    assert re.findall(r"CREATE TABLE `?([a-z_]+)`? \(", sql) == ORDER
    assert sql.count("AUTO_INCREMENT") == 9
    assert sql.count("ENGINE=InnoDB") == 9
    assert sql.count("CHARSET=utf8mb4") == 9
    assert sql.count("FOREIGN KEY") == 11
    assert sql.count("CREATE INDEX") == 7
    assert "FOREIGN KEY(section_id, panel_id) REFERENCES panel_section (section_id, panel_id)" in sql
    assert "UNIQUE (section_id, panel_id)" in sql
    assert "ENUM('NUMERIC','TEXT','POS_NEG')" in sql
    assert "ENUM('M','F','ANY')" in sql
    assert "ENUM('NORMAL','LOW','HIGH','CRITICAL_LOW','CRITICAL_HIGH','ABNORMAL')" in sql
    assert "NUMERIC(6, 2)" in sql and "NUMERIC(12, 3)" in sql
    assert "INSERT INTO" not in sql
    assert "DELETE FROM" not in sql
    assert "ALTER TABLE" not in sql
    assert "synthetic-test-only" not in sql
    for name in ORDER:
        for fk in Base.metadata.tables[name].foreign_keys:
            assert ORDER.index(fk.column.table.name) < ORDER.index(name)
    downgrade = StringIO()
    command.downgrade(config(downgrade), f"{HEAD}:{PARENT}", sql=True)
    assert re.findall(r"DROP TABLE `?([a-z_]+)`?;", downgrade.getvalue()) == list(reversed(ORDER))
    assert "DROP INDEX" not in downgrade.getvalue()


@pytest.fixture
def laboratory_connection():
    # Execute the real frozen migrations against an isolated, in-memory database.
    # Explicit synthetic BIGINT IDs; native ENUM and AUTO_INCREMENT covered offline.
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Operations.context(MigrationContext.configure(connection)):
                revision(PARENT).upgrade()
            patient = Base.metadata.tables["patient"]
            connection.execute(patient.insert().values(
                patient_id=1, patient_code="SYNTHETIC", first_name="Test", last_name="Only"
            ))
            connection.commit()
            with Operations.context(MigrationContext.configure(connection)):
                revision(HEAD).upgrade()
            assert set(sa.inspect(connection).get_table_names()) == PHASE_2A_TABLES | TABLES
            for name in TABLES:
                assert connection.scalar(sa.select(sa.func.count()).select_from(Base.metadata.tables[name])) == 0
            yield connection
            with Operations.context(MigrationContext.configure(connection)):
                revision(HEAD).downgrade()
            assert set(sa.inspect(connection).get_table_names()) == PHASE_2A_TABLES
            assert connection.scalar(sa.select(patient.c.patient_code)) == "SYNTHETIC"
            with Operations.context(MigrationContext.configure(connection)):
                revision(PARENT).downgrade()
            assert sa.inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_constraints_same_panel_rule_and_round_trip(laboratory_connection):
    c = laboratory_connection
    t = Base.metadata.tables
    c.execute(t["lab_department"].insert().values(
        department_id=1, department_code="SYNTH", department_name="Synthetic"
    ))
    c.execute(t["sample_type"].insert(), [dict(sample_type_id=i, sample_name=f"Synthetic {i}") for i in (1, 2)])
    c.execute(t["test_catalog"].insert(), [dict(
        test_id=i, test_code=f"SYNTH-{i}", test_name="Synthetic", department_id=1, result_type="NUMERIC"
    ) for i in (1, 2, 3)])
    c.execute(t["test_panel"].insert(), [dict(
        panel_id=i, panel_code=f"SYNTH-{i}", panel_name="Synthetic", department_id=None
    ) for i in (1, 2)])
    c.execute(t["panel_section"].insert(), [dict(
        section_id=i, panel_id=i, section_name="Synthetic section", sort_order=1
    ) for i in (1, 2)])
    # Nullable sections and same-panel sections are both supported.
    c.execute(t["panel_test"].insert(), [
        dict(panel_test_id=1, panel_id=1, section_id=1, test_id=1, sort_order=1, is_required=True),
        dict(panel_test_id=2, panel_id=1, section_id=None, test_id=2, sort_order=2, is_required=False),
    ])
    c.execute(t["test_sample_type"].insert(), [dict(
        test_sample_type_id=i, test_id=1, sample_type_id=i, is_default=True
    ) for i in (1, 2)])
    c.execute(t["test_interpretation_rule"].insert().values(rule_id=1, test_id=1, flag="NORMAL"))
    c.execute(t["reference_range"].insert().values(
        range_id=1, test_id=1, sex="ANY", age_min=Decimal("1.25"), age_max=Decimal("2.50"),
        normal_low=Decimal("1.125"), normal_high=Decimal("2.250"),
        critical_low=Decimal("0.125"), critical_high=Decimal("3.875"),
        effective_from=date(2026, 1, 1),
    ))
    c.execute(t["reference_range"].insert().values(
        range_id=2, test_id=2, sex="F", qualitative_normal="Synthetic qualitative value"
    ))
    stored = c.execute(sa.select(t["reference_range"]).where(t["reference_range"].c.range_id == 1)).one()
    assert stored.age_min == Decimal("1.25")
    assert stored.normal_low == Decimal("1.125")
    assert stored.effective_from == date(2026, 1, 1)
    assert stored.effective_to is None
    assert stored.is_active is True
    assert c.scalar(sa.select(t["lab_department"].c.is_active)) is True
    # Invalid inserts exercise every FK target, each business unique constraint,
    # and required booleans. Updates cover both ends of the same-panel invariant.
    invalid = [
        ("lab_department", dict(department_id=2, department_code="SYNTH", department_name="Duplicate")),
        ("sample_type", dict(sample_type_id=3, sample_name="Synthetic 1")),
        ("test_catalog", dict(test_id=4, test_code="SYNTH-1", test_name="Duplicate", department_id=1, result_type="TEXT")),
        ("test_catalog", dict(test_id=4, test_code="NEW", test_name="Orphan", department_id=99, result_type="TEXT")),
        ("test_panel", dict(panel_id=3, panel_code="SYNTH-1", panel_name="Duplicate")),
        ("test_panel", dict(panel_id=3, panel_code="NEW", panel_name="Orphan", department_id=99)),
        ("panel_section", dict(section_id=3, panel_id=99, section_name="Orphan", sort_order=1)),
        ("test_sample_type", dict(test_sample_type_id=3, test_id=1, sample_type_id=1, is_default=False)),
        ("test_sample_type", dict(test_sample_type_id=3, test_id=99, sample_type_id=1, is_default=False)),
        ("test_sample_type", dict(test_sample_type_id=3, test_id=1, sample_type_id=99, is_default=False)),
        ("test_sample_type", dict(test_sample_type_id=3, test_id=2, sample_type_id=1)),
        ("panel_test", dict(panel_test_id=3, panel_id=1, test_id=1, sort_order=3, is_required=True)),
        ("panel_test", dict(panel_test_id=3, panel_id=99, test_id=3, sort_order=3, is_required=True)),
        ("panel_test", dict(panel_test_id=3, panel_id=1, test_id=99, sort_order=3, is_required=True)),
        ("panel_test", dict(panel_test_id=3, panel_id=1, section_id=99, test_id=3, sort_order=3, is_required=True)),
        ("panel_test", dict(panel_test_id=3, panel_id=1, section_id=2, test_id=3, sort_order=3, is_required=True)),
        ("panel_test", dict(panel_test_id=3, panel_id=1, test_id=3, sort_order=3)),
        ("reference_range", dict(range_id=3, test_id=99, sex="ANY")),
        ("test_interpretation_rule", dict(rule_id=2, test_id=1, flag="NORMAL")),
        ("test_interpretation_rule", dict(rule_id=2, test_id=99, flag="NORMAL")),
    ]
    statements = [t[name].insert().values(**values) for name, values in invalid]
    statements += [
        t["panel_test"].update().where(t["panel_test"].c.panel_test_id == 1).values(section_id=2),
        t["panel_test"].update().where(t["panel_test"].c.panel_test_id == 1).values(panel_id=2),
        t["panel_section"].update().where(t["panel_section"].c.section_id == 1).values(panel_id=2),
        t["panel_section"].delete().where(t["panel_section"].c.section_id == 1),
        t["test_panel"].delete().where(t["test_panel"].c.panel_id == 1),
        t["test_catalog"].delete().where(t["test_catalog"].c.test_id == 1),
        t["sample_type"].delete().where(t["sample_type"].c.sample_type_id == 1),
        t["lab_department"].delete().where(t["lab_department"].c.department_id == 1),
    ]
    for statement in statements:
        with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            c.execute(statement)
    # Removing the section is legal; both child IDs may be changed together.
    c.execute(t["panel_test"].update().where(t["panel_test"].c.panel_test_id == 1).values(section_id=None))
    c.execute(t["panel_test"].update().where(t["panel_test"].c.panel_test_id == 1).values(panel_id=2, section_id=2))
