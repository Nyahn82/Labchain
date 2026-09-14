from datetime import datetime
from decimal import Decimal
from io import StringIO
import re

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa

from app.models import Base
from test_phase_2a_migration import config, revision, REVISION, PHASE_2B, PHASE_2C as HEAD, HEAD as CURRENT_HEAD
from test_phase_2c_models import TABLES, UNIQUES, PHASE_2A_TABLES, PHASE_2B_TABLES

ORDER = [
    "lab_order", "order_panel", "lab_order_item", "lab_payment", "specimen",
    "specimen_order_item", "rejection_reason", "specimen_rejection", "lab_result_item",
]
NOW = datetime(2026, 9, 14, 12, 0)
ROWS = {
    "lab_order": dict(order_id=1, order_code="SYNTH-1", patient_id=1, order_date=NOW,
                      priority="ROUTINE", status="REQUESTED"),
    "order_panel": dict(order_panel_id=1, order_id=1, panel_id=1, status="REQUESTED"),
    "lab_order_item": dict(order_item_id=1, order_id=1, test_id=1, order_panel_id=1, status="REQUESTED"),
    "lab_payment": dict(payment_id=1, order_id=1, payment_status="PAID", amount=Decimal("12.25"), recorded_at=NOW),
    "specimen": dict(specimen_id=1, specimen_code="SYNTH-S1", order_id=1, sample_type_id=1, specimen_status="PENDING"),
    "specimen_order_item": dict(specimen_order_item_id=1, specimen_id=1, order_item_id=1),
    "rejection_reason": dict(rejection_reason_id=1, reason_code="SYNTH", reason_name="Synthetic reason"),
    "specimen_rejection": dict(specimen_rejection_id=1, specimen_id=1, rejection_reason_id=1,
                               rejected_by_user_id=1, rejected_at=NOW, recollection_required=False),
    "lab_result_item": dict(result_item_id=1, order_item_id=1, specimen_id=1, reference_range_id=1,
                            result_value="1.125", numeric_value=Decimal("1.125"), status="DRAFT",
                            encoded_by_user_id=1, encoded_at=NOW),
}


def test_single_head_parent_and_offline_mysql_migration(monkeypatch):
    from app.database import engine

    def no_connection():
        pytest.fail("Offline migration connected to a database")

    monkeypatch.setattr(engine, "connect", no_connection)
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PHASE_2B
    assert [r.revision for r in scripts.walk_revisions(head=HEAD)] == [HEAD, PHASE_2B, REVISION]
    upgrade = StringIO()
    command.upgrade(config(upgrade), f"{PHASE_2B}:{HEAD}", sql=True)
    sql = upgrade.getvalue()
    assert re.findall(r"CREATE TABLE `?([a-z_]+)`? \(", sql) == ORDER
    assert sql.count("AUTO_INCREMENT") == 9
    assert sql.count("ENGINE=InnoDB") == 9
    assert sql.count("CHARSET=utf8mb4") == 9
    assert sql.count("FOREIGN KEY") == 26
    assert sql.count("CREATE INDEX") == 23
    assert "FOREIGN KEY(order_panel_id, order_id) REFERENCES order_panel (order_panel_id, order_id)" in sql
    assert "NUMERIC(12, 2)" in sql and "NUMERIC(12, 3)" in sql
    assert "INSERT INTO" not in sql and "DELETE FROM" not in sql
    assert "ALTER TABLE" not in sql and "synthetic-test-only" not in sql
    for name in ORDER:
        for fk in Base.metadata.tables[name].foreign_keys:
            if fk.column.table.name in TABLES:
                assert ORDER.index(fk.column.table.name) < ORDER.index(name)
    downgrade = StringIO()
    command.downgrade(config(downgrade), f"{HEAD}:{PHASE_2B}", sql=True)
    assert re.findall(r"DROP TABLE `?([a-z_]+)`?;", downgrade.getvalue()) == list(reversed(ORDER))
    assert "DROP INDEX" not in downgrade.getvalue()


@pytest.fixture
def workflow_connection():
    engine = sa.create_engine("sqlite://")
    t = Base.metadata.tables
    previous = PHASE_2A_TABLES | PHASE_2B_TABLES
    try:
        with engine.connect() as c:
            c.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Operations.context(MigrationContext.configure(c)):
                revision(REVISION).upgrade()
                revision(PHASE_2B).upgrade()
            c.execute(t["patient"].insert().values(patient_id=1, patient_code="SYNTH", first_name="Test", last_name="Only"))
            c.execute(t["user_account"].insert().values(user_id=1, username="synthetic", password_hash="synthetic-only", account_status="ACTIVE"))
            c.execute(t["lab_department"].insert().values(department_id=1, department_code="SYNTH", department_name="Synthetic"))
            c.execute(t["sample_type"].insert().values(sample_type_id=1, sample_name="Synthetic"))
            c.execute(t["test_catalog"].insert().values(test_id=1, test_code="SYNTH", test_name="Synthetic", department_id=1, result_type="NUMERIC"))
            c.execute(t["test_panel"].insert().values(panel_id=1, panel_code="SYNTH", panel_name="Synthetic"))
            c.execute(t["reference_range"].insert().values(range_id=1, test_id=1, sex="ANY"))
            before = {name: c.execute(sa.select(t[name])).all() for name in previous}
            c.commit()
            with Operations.context(MigrationContext.configure(c)):
                revision(HEAD).upgrade()
            assert set(sa.inspect(c).get_table_names()) == previous | TABLES
            for name in ORDER:
                assert c.scalar(sa.select(sa.func.count()).select_from(t[name])) == 0
                c.execute(t[name].insert().values(**ROWS[name]))
            yield c
            with Operations.context(MigrationContext.configure(c)):
                revision(HEAD).downgrade()
            assert set(sa.inspect(c).get_table_names()) == previous
            assert {name: c.execute(sa.select(t[name])).all() for name in previous} == before
            with Operations.context(MigrationContext.configure(c)):
                revision(PHASE_2B).downgrade()
                revision(REVISION).downgrade()
            assert sa.inspect(c).get_table_names() == []
    finally:
        engine.dispose()


def test_every_foreign_key_and_required_column_rejects_invalid_values(workflow_connection):
    c = workflow_connection
    for name in ORDER:
        table = Base.metadata.tables[name]
        for fk in table.foreign_key_constraints:
            with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                c.execute(table.update().values(**{column.name: 999 for column in fk.columns}))
        for column in table.c:
            if column.nullable or column.primary_key:
                continue
            with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                c.execute(table.update().values(**{column.name: None}))
    # History remains protected if a referenced parent is deleted.
    for name in ("patient", "user_account", "lab_order", "order_panel", "lab_order_item",
                 "specimen", "rejection_reason", "test_catalog", "sample_type", "reference_range"):
        with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            c.execute(Base.metadata.tables[name].delete())


def test_uniqueness_and_workflow_multiplicity(workflow_connection):
    c = workflow_connection
    t = Base.metadata.tables
    for name in UNIQUES:
        table = t[name]
        pk = next(iter(table.primary_key.columns)).name
        with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            c.execute(table.insert().values(**{**ROWS[name], pk: 2}))
    for name in ("lab_order_item", "lab_payment", "specimen_rejection", "lab_result_item"):
        table = t[name]
        pk = next(iter(table.primary_key.columns)).name
        c.execute(table.insert().values(**{**ROWS[name], pk: 2}))
        assert c.scalar(sa.select(sa.func.count()).select_from(table)) == 2
    # Multiple specimens per order; an order may have no payment at all.
    c.execute(t["specimen"].insert().values(**{**ROWS["specimen"], "specimen_id": 2, "specimen_code": "SYNTH-S2"}))
    c.execute(t["lab_order"].insert().values(**{**ROWS["lab_order"], "order_id": 2, "order_code": "SYNTH-2"}))
    assert c.scalar(sa.select(sa.func.count()).select_from(t["lab_payment"]).where(t["lab_payment"].c.order_id == 2)) == 0
    # Bridge supports multiple specimens per item and multiple items per specimen.
    c.execute(t["specimen_order_item"].insert(), [
        dict(specimen_order_item_id=2, specimen_id=2, order_item_id=1),
        dict(specimen_order_item_id=3, specimen_id=1, order_item_id=2),
    ])


def test_same_order_panel_constraint_on_inserts_and_updates(workflow_connection):
    c = workflow_connection
    t = Base.metadata.tables
    c.execute(t["lab_order"].insert().values(**{**ROWS["lab_order"], "order_id": 2, "order_code": "SYNTH-2"}))
    c.execute(t["order_panel"].insert().values(**{**ROWS["order_panel"], "order_panel_id": 2, "order_id": 2}))
    invalid = [
        t["lab_order_item"].insert().values(**{**ROWS["lab_order_item"], "order_item_id": 2, "order_panel_id": 2}),
        t["lab_order_item"].update().values(order_panel_id=2),
        t["lab_order_item"].update().values(order_id=2),
        # Use a third order to ensure rejection is due to the FK, not pair uniqueness.
    ]
    c.execute(t["lab_order"].insert().values(**{**ROWS["lab_order"], "order_id": 3, "order_code": "SYNTH-3"}))
    invalid.append(t["order_panel"].update().where(t["order_panel"].c.order_panel_id == 1).values(order_id=3))
    for statement in invalid:
        with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            c.execute(statement)
    c.execute(t["lab_order_item"].update().values(order_panel_id=None))
    c.execute(t["lab_order_item"].update().values(order_id=2, order_panel_id=2))


def test_display_numeric_values_optional_links_and_defaults(workflow_connection):
    c = workflow_connection
    t = Base.metadata.tables
    assert c.scalar(sa.select(t["lab_payment"].c.amount)) == Decimal("12.25")
    assert c.scalar(sa.select(t["lab_result_item"].c.numeric_value)) == Decimal("1.125")
    for name in ("lab_order", "lab_order_item", "specimen"):
        assert c.scalar(sa.select(t[name].c.created_at)) is not None
    assert c.scalar(sa.select(t["rejection_reason"].c.is_active)) is True
    for result_id, value in enumerate(["15", "Negative", "Positive", "No growth", "Normal"], start=2):
        c.execute(t["lab_result_item"].insert().values(
            result_item_id=result_id, order_item_id=1, result_value=value,
            encoded_by_user_id=1, encoded_at=NOW, status="DRAFT",
        ))
        row = c.execute(sa.select(t["lab_result_item"]).where(t["lab_result_item"].c.result_item_id == result_id)).one()
        assert row.result_value == value
        assert row.numeric_value is None and row.flag is None
        assert row.specimen_id is None and row.reference_range_id is None
        assert row.reviewed_by_user_id is None and row.verified_by_user_id is None
