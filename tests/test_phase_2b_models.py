import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers

from app.models import Base
from test_phase_2a_models import TABLES as PHASE_2A_TABLES

TABLES = {
    "lab_department", "sample_type", "test_catalog", "test_sample_type", "test_panel",
    "panel_section", "panel_test", "reference_range", "test_interpretation_rule",
}
UNIQUES = {
    "lab_department": {("department_code",)},
    "sample_type": {("sample_name",)},
    "test_catalog": {("test_code",)},
    "test_sample_type": {("test_id", "sample_type_id")},
    "test_panel": {("panel_code",)},
    "panel_section": {("section_id", "panel_id")},
    "panel_test": {("panel_id", "test_id")},
    "reference_range": set(),
    "test_interpretation_rule": {("test_id", "flag")},
}
FOREIGN_KEYS = {
    "test_catalog": {(("department_id", "lab_department.department_id"),)},
    "test_sample_type": {
        (("test_id", "test_catalog.test_id"),),
        (("sample_type_id", "sample_type.sample_type_id"),),
    },
    "test_panel": {(("department_id", "lab_department.department_id"),)},
    "panel_section": {(("panel_id", "test_panel.panel_id"),)},
    "panel_test": {
        (("panel_id", "test_panel.panel_id"),),
        (("section_id", "panel_section.section_id"),),
        (("test_id", "test_catalog.test_id"),),
        (("section_id", "panel_section.section_id"), ("panel_id", "panel_section.panel_id")),
    },
    "reference_range": {(("test_id", "test_catalog.test_id"),)},
    "test_interpretation_rule": {(("test_id", "test_catalog.test_id"),)},
}
# Independent workbook contract: exact column names, SQL types and optional fields.
COLUMNS = {
    "lab_department": "department_id department_code department_name description is_active",
    "sample_type": "sample_type_id sample_name description is_active",
    "test_catalog": "test_id test_code test_name department_id default_unit result_type methodology default_sort_order is_active",
    "test_sample_type": "test_sample_type_id test_id sample_type_id is_default",
    "test_panel": "panel_id panel_code panel_name department_id description is_active",
    "panel_section": "section_id panel_id section_name sort_order is_active",
    "panel_test": "panel_test_id panel_id section_id test_id sort_order is_required",
    "reference_range": "range_id test_id sex age_min age_max normal_low normal_high critical_low critical_high qualitative_normal unit effective_from effective_to is_active",
    "test_interpretation_rule": "rule_id test_id flag interpretation_text possible_causes recommendation is_active",
}
OPTIONAL = {
    "lab_department": {"description"}, "sample_type": {"description"},
    "test_catalog": {"default_unit", "methodology", "default_sort_order"},
    "test_panel": {"department_id", "description"}, "panel_test": {"section_id"},
    "reference_range": {
        "age_min", "age_max", "normal_low", "normal_high", "critical_low", "critical_high",
        "qualitative_normal", "unit", "effective_from", "effective_to",
    },
    "test_interpretation_rule": {"interpretation_text", "possible_causes", "recommendation"},
}
LENGTHS = {
    "lab_department": {"department_code": 30, "department_name": 100},
    "sample_type": {"sample_name": 80},
    "test_catalog": {"test_code": 30, "test_name": 150, "default_unit": 50, "methodology": 150},
    "test_panel": {"panel_code": 30, "panel_name": 120},
    "panel_section": {"section_name": 120},
    "reference_range": {"qualitative_normal": 80, "unit": 50},
}


def test_exact_phase_2a_and_2b_metadata():
    configure_mappers()
    assert PHASE_2A_TABLES | TABLES <= set(Base.metadata.tables)
    assert len([m for m in Base.registry.mappers if m.local_table.name in PHASE_2A_TABLES | TABLES]) == 21


@pytest.mark.parametrize("name", sorted(TABLES))
def test_workbook_columns_keys_and_storage(name):
    table = Base.metadata.tables[name]
    assert list(table.c.keys()) == COLUMNS[name].split()
    assert {c.name for c in table.c if c.nullable} == OPTIONAL.get(name, set())
    assert len(table.primary_key.columns) == 1
    pk = next(iter(table.primary_key.columns))
    assert pk.name == COLUMNS[name].split()[0]
    assert isinstance(pk.type, sa.BigInteger)
    assert pk.autoincrement is True
    assert {tuple(c.columns.keys()) for c in table.constraints
            if isinstance(c, sa.UniqueConstraint)} == UNIQUES[name]
    assert {tuple((e.parent.name, e.target_fullname) for e in fk.elements)
            for fk in table.foreign_key_constraints} == FOREIGN_KEYS.get(name, set())
    assert all(c.name and len(c.name) <= 64 for c in table.constraints)
    assert table.dialect_options["mysql"]["engine"] == "InnoDB"
    assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
    for column, length in LENGTHS.get(name, {}).items():
        assert type(table.c[column].type) is sa.String
        assert table.c[column].type.length == length
    for column in table.c:
        if column.name.endswith("_id"):
            assert isinstance(column.type, sa.BigInteger)
        if column.name in {"sort_order", "default_sort_order"}:
            assert type(column.type) is sa.Integer
        if column.name in {"description", "interpretation_text", "possible_causes", "recommendation"}:
            assert isinstance(column.type, sa.Text)
        if column.name.startswith("is_"):
            assert isinstance(column.type, sa.Boolean)
        assert column.default is None
        if column.name == "is_active":
            assert str(column.server_default.arg) == "1"
        else:
            assert column.server_default is None


@pytest.mark.parametrize("name", sorted(TABLES))
def test_foreign_keys_are_indexed_without_delete_cascades(name):
    table = Base.metadata.tables[name]
    keys = [tuple(i.columns.keys()) for i in table.indexes]
    keys += [tuple(c.columns.keys()) for c in table.constraints
             if isinstance(c, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))]
    for fk in table.foreign_key_constraints:
        columns = tuple(fk.columns.keys())
        assert any(key[:len(columns)] == columns for key in keys)
        assert fk.ondelete is None
        assert fk.onupdate is None
        # Each referenced key is explicitly unique, including the composite FK.
        parent = fk.referred_table
        target = tuple(e.column.name for e in fk.elements)
        assert target in {tuple(c.columns.keys()) for c in parent.constraints
                          if isinstance(c, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))}
    mapper = next(m for m in Base.registry.mappers if m.local_table is table)
    assert all(not r.cascade.delete and not r.cascade.delete_orphan for r in mapper.relationships)


@pytest.mark.parametrize("table,column,values", [
    ("test_catalog", "result_type", ["NUMERIC", "TEXT", "POS_NEG"]),
    ("reference_range", "sex", ["M", "F", "ANY"]),
    ("test_interpretation_rule", "flag",
     ["NORMAL", "LOW", "HIGH", "CRITICAL_LOW", "CRITICAL_HIGH", "ABNORMAL"]),
])
def test_exact_native_mysql_enums(table, column, values):
    enum = Base.metadata.tables[table].c[column].type
    assert isinstance(enum, sa.Enum)
    assert enum.enums == values
    assert str(enum.compile(dialect=mysql.dialect())) == "ENUM(" + ",".join(repr(v) for v in values) + ")"


def test_reference_range_precision_and_dates():
    columns = Base.metadata.tables["reference_range"].c
    for name in ("age_min", "age_max", "normal_low", "normal_high", "critical_low", "critical_high"):
        expected = (6, 2) if name.startswith("age_") else (12, 3)
        assert isinstance(columns[name].type, sa.Numeric)
        assert (columns[name].type.precision, columns[name].type.scale) == expected
        assert columns[name].type.asdecimal
    for name in ("effective_from", "effective_to"):
        assert isinstance(columns[name].type, sa.Date)
    assert "normal_low" not in Base.metadata.tables["test_catalog"].c
