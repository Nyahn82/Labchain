import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers

from app.models import Base
from workbook_helpers import workbook_definitions
from test_phase_2a_models import TABLES as PHASE_2A_TABLES
from test_phase_2b_models import TABLES as PHASE_2B_TABLES

TABLES = {
    "lab_order", "order_panel", "lab_order_item", "lab_payment", "specimen",
    "specimen_order_item", "rejection_reason", "specimen_rejection", "lab_result_item",
}
UNIQUES = {
    "lab_order": {("order_code",)},
    "order_panel": {("order_id", "panel_id"), ("order_panel_id", "order_id")},
    "specimen": {("specimen_code",)},
    "specimen_order_item": {("specimen_id", "order_item_id")},
    "rejection_reason": {("reason_code",)},
}
ORDER_STATUS = ["REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
ENUMS = [
    ("lab_order", "priority", ["ROUTINE", "STAT", "URGENT"]),
    ("lab_order", "status", ORDER_STATUS),
    ("order_panel", "status", ORDER_STATUS),
    ("lab_order_item", "status", ORDER_STATUS),
    ("lab_payment", "payment_status", ["PENDING", "PAID", "FREE", "WAIVED", "SUBSIDIZED"]),
    ("specimen", "specimen_status", ["PENDING", "COLLECTED", "RECEIVED", "REJECTED", "PROCESSED"]),
    ("lab_result_item", "status", ["DRAFT", "REVIEWED", "VERIFIED"]),
    ("lab_result_item", "flag", ["NORMAL", "LOW", "HIGH", "CRITICAL_LOW", "CRITICAL_HIGH", "ABNORMAL"]),
]


@pytest.fixture(scope="module")
def contract():
    return workbook_definitions(TABLES)


def test_exact_phase_2a_2b_2c_metadata_and_result_anchor():
    configure_mappers()
    assert PHASE_2A_TABLES | PHASE_2B_TABLES | TABLES <= set(Base.metadata.tables)
    assert len([m for m in Base.registry.mappers if m.local_table.name in PHASE_2A_TABLES | PHASE_2B_TABLES | TABLES]) == 30
    for name in ("lab_order_item", "lab_result_item"):
        assert "report_id" not in Base.metadata.tables[name].c
        assert all("report" not in fk.target_fullname for fk in Base.metadata.tables[name].foreign_keys)
    assert "order_item_id" in Base.metadata.tables["lab_result_item"].c
    assert "order_item_id" in Base.metadata.tables["specimen_order_item"].c


@pytest.mark.parametrize("name", sorted(TABLES))
def test_columns_types_defaults_and_foreign_keys_match_workbook(name, contract):
    table = Base.metadata.tables[name]
    assert list(table.c.keys()) == [row[0] for row in contract[name]]
    expected_fks = set()
    types = {"BIGINT": sa.BigInteger, "VARCHAR": sa.String, "TEXT": sa.Text,
             "DATETIME": sa.DateTime, "ENUM": sa.Enum, "DECIMAL": sa.Numeric, "BOOLEAN": sa.Boolean}
    for column_name, kind, size, nullable, key, target in contract[name]:
        column = table.c[column_name]
        assert type(column.type) is types[kind], (name, column_name)
        assert column.nullable is (nullable == "Yes"), (name, column_name)
        assert column.primary_key is (key == "PK")
        if key == "PK":
            assert column.autoincrement is True
        if key == "FK":
            expected_fks.add(((column_name, target.lower()),))
        if key == "UQ":
            assert (column_name,) in UNIQUES[name]
        if kind == "VARCHAR":
            assert column.type.length == int(size)
        elif kind == "DECIMAL":
            assert (column.type.precision, column.type.scale) == tuple(map(int, size.split(",")))
            assert column.type.asdecimal
        elif kind == "ENUM":
            assert column.type.enums == size.split(",")
        default = "CURRENT_TIMESTAMP" if column_name == "created_at" else "1" if column_name == "is_active" else None
        assert (str(column.server_default.arg) if column.server_default is not None else None) == default
        assert column.default is None
        assert column.onupdate is None
        assert column.server_onupdate is None
    if name == "lab_order_item":
        expected_fks.add((("order_panel_id", "order_panel.order_panel_id"), ("order_id", "order_panel.order_id")))
    assert {tuple((e.parent.name, e.target_fullname) for e in fk.elements)
            for fk in table.foreign_key_constraints} == expected_fks
    assert {tuple(c.columns.keys()) for c in table.constraints
            if isinstance(c, sa.UniqueConstraint)} == UNIQUES.get(name, set())
    assert len(table.primary_key.columns) == 1


@pytest.mark.parametrize("name", sorted(TABLES))
def test_mysql_storage_fk_indexes_and_no_cascades(name):
    table = Base.metadata.tables[name]
    assert table.dialect_options["mysql"]["engine"] == "InnoDB"
    assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
    assert all(c.name and len(c.name) <= 64 for c in table.constraints)
    assert all(i.name and len(i.name) <= 64 for i in table.indexes)
    keys = [tuple(i.columns.keys()) for i in table.indexes]
    keys += [tuple(c.columns.keys()) for c in table.constraints
             if isinstance(c, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))]
    for fk in table.foreign_key_constraints:
        columns = tuple(fk.columns.keys())
        assert any(key[:len(columns)] == columns for key in keys)
        assert fk.ondelete is None and fk.onupdate is None
        assert tuple(e.column.name for e in fk.elements) in {
            tuple(c.columns.keys()) for c in fk.referred_table.constraints
            if isinstance(c, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
        }
    mapper = next(m for m in Base.registry.mappers if m.local_table is table)
    assert all(not r.cascade.delete and not r.cascade.delete_orphan for r in mapper.relationships)


@pytest.mark.parametrize("table,column,values", ENUMS)
def test_canonical_native_mysql_enums(table, column, values):
    enum = Base.metadata.tables[table].c[column].type
    assert enum.enums == values
    assert str(enum.compile(dialect=mysql.dialect())) == "ENUM(" + ",".join(repr(v) for v in values) + ")"
