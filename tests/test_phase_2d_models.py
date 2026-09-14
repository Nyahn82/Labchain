import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers

from app.models import Base
from test_phase_2a_models import TABLES as PHASE_2A_TABLES
from test_phase_2b_models import TABLES as PHASE_2B_TABLES
from test_phase_2c_models import TABLES as PHASE_2C_TABLES
from workbook_helpers import workbook_definitions

TABLES = {
    "report_template", "lab_report", "report_result_item", "report_patient_snapshot",
    "signatory", "report_signatory", "report_verification", "email_log", "print_log",
    "audit_log", "login_log", "attachment", "blockchain_node", "blockchain_event",
    "blockchain_verification_log", "blockchain_sync_log",
}
PREVIOUS_TABLES = PHASE_2A_TABLES | PHASE_2B_TABLES | PHASE_2C_TABLES
UNIQUES = {
    "report_template": {("template_code",)},
    "lab_report": {("report_code",)},
    "report_verification": {("verification_token",)},
    "blockchain_node": {("node_code",), ("port",)},
    "blockchain_event": {("event_uuid",)},
}
ENUMS = [
    ("lab_report", "report_status", ["GENERATED", "APPROVED", "RELEASED", "REVOKED"]),
    ("report_signatory", "signatory_type", ["LAB_IN_CHARGE", "MEDICAL_TECHNOLOGIST", "PATHOLOGIST"]),
    ("report_verification", "verification_status", ["AUTHENTIC", "REVOKED"]),
    ("email_log", "status", ["PENDING", "SENT", "FAILED"]),
    ("login_log", "status", ["SUCCESS", "FAILED"]),
    ("blockchain_event", "event_status", ["PENDING", "ACCEPTED", "REJECTED"]),
    ("blockchain_verification_log", "verification_status", ["MATCH", "MISMATCH", "NOT_FOUND"]),
    ("blockchain_sync_log", "sync_status", ["SUCCESS", "FAILED", "CONFLICT"]),
]


@pytest.fixture(scope="module")
def contract():
    return workbook_definitions(TABLES)


def test_exact_metadata_snapshots_and_existing_application():
    from app.main import app
    from fastapi import FastAPI

    configure_mappers()
    assert set(Base.metadata.tables) == PREVIOUS_TABLES | TABLES
    assert len(Base.registry.mappers) == 46
    assert isinstance(app, FastAPI)
    assert set(app.openapi()["paths"]) == {"/api/v1/", "/api/v1/health", "/api/v1/ready"}
    assert not any("age" in c.name for c in Base.metadata.tables["patient"].c)
    assert "age_at_report" in Base.metadata.tables["report_patient_snapshot"].c
    assert "report_id" not in Base.metadata.tables["lab_result_item"].c
    assert "print_count" not in Base.metadata.tables["lab_report"].c
    assert {fk.target_fullname for fk in Base.metadata.tables["report_result_item"].c.result_item_id.foreign_keys} == {"lab_result_item.result_item_id"}
    assert {fk.target_fullname for fk in Base.metadata.tables["lab_result_item"].c.order_item_id.foreign_keys} == {"lab_order_item.order_item_id"}
    for name in TABLES:
        if name.startswith("blockchain_"):
            assert not {"patient_name", "result_value", "report_content", "payload"} & set(Base.metadata.tables[name].c.keys())


@pytest.mark.parametrize("name", sorted(TABLES))
def test_exact_workbook_columns_types_nullability_keys_and_defaults(name, contract):
    table = Base.metadata.tables[name]
    assert list(table.c.keys()) == [row[0] for row in contract[name]]
    expected_fks = set()
    types = {"BIGINT": sa.BigInteger, "INT": sa.Integer, "VARCHAR": sa.String, "CHAR": sa.CHAR,
             "TEXT": sa.Text, "DATE": sa.Date, "DATETIME": sa.DateTime, "ENUM": sa.Enum,
             "JSON": sa.JSON, "BOOLEAN": sa.Boolean}
    for column_name, kind, size, nullable, key, target in contract[name]:
        column = table.c[column_name]
        assert type(column.type) is types[kind], (name, column_name)
        assert column.nullable is (nullable == "Yes"), (name, column_name)
        assert column.primary_key is ("PK" in key)
        if "PK" in key:
            assert column.autoincrement is (size == "auto increment")
        if "FK" in key:
            expected_fks.add(((column_name, target.lower()),))
        if key == "UQ":
            assert (column_name,) in UNIQUES[name]
        if kind in {"VARCHAR", "CHAR"}:
            assert column.type.length == int(size)
        elif kind == "ENUM":
            assert column.type.enums == size.split(",")
        elif kind == "JSON":
            assert column.type.none_as_null is True
        default = "CURRENT_TIMESTAMP" if column_name == "created_at" else "1" if column_name == "is_active" else None
        assert (str(column.server_default.arg) if column.server_default is not None else None) == default
        assert column.default is None and column.onupdate is None and column.server_onupdate is None
    assert {tuple((e.parent.name, e.target_fullname) for e in fk.elements)
            for fk in table.foreign_key_constraints} == expected_fks
    assert {tuple(c.columns.keys()) for c in table.constraints
            if isinstance(c, sa.UniqueConstraint)} == UNIQUES.get(name, set())
    assert len(table.primary_key.columns) == 1


@pytest.mark.parametrize("name", sorted(TABLES))
def test_mysql_storage_indexes_and_restrictive_foreign_keys(name):
    table = Base.metadata.tables[name]
    assert table.dialect_options["mysql"]["engine"] == "InnoDB"
    assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
    assert all(c.name and len(c.name) <= 64 for c in table.constraints)
    assert all(i.name and len(i.name) <= 64 for i in table.indexes)
    # Every FK gets its own index except the snapshot's existing primary key.
    indexed = {tuple(i.columns.keys()) for i in table.indexes}
    expected = {(fk.parent.name,) for fk in table.foreign_keys if not fk.parent.primary_key}
    assert indexed == expected
    assert all(not i.unique for i in table.indexes)
    for fk in table.foreign_key_constraints:
        assert fk.ondelete is None and fk.onupdate is None
    mapper = next(m for m in Base.registry.mappers if m.local_table is table)
    assert all(not r.cascade.delete and not r.cascade.delete_orphan for r in mapper.relationships)


@pytest.mark.parametrize("table,column,values", ENUMS)
def test_canonical_native_mysql_enums(table, column, values):
    enum = Base.metadata.tables[table].c[column].type
    assert enum.enums == values
    assert str(enum.compile(dialect=mysql.dialect())) == "ENUM(" + ",".join(repr(v) for v in values) + ")"


def test_attachment_inclusive_parent_check():
    checks = [(name, c) for name in TABLES for c in Base.metadata.tables[name].constraints
              if isinstance(c, sa.CheckConstraint)]
    assert len(checks) == 1
    name, check = checks[0]
    assert name == "attachment"
    assert check.name == "ck_attachment_parent_required"
    assert str(check.sqltext) == "order_id IS NOT NULL OR report_id IS NOT NULL"
