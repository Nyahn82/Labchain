import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers

from app.models import Base, Patient, Staff, UserAccount, UserRole

TABLES = {
    "facility_profile", "patient", "staff", "referring_facility",
    "requesting_physician", "user_account", "staff_account_link",
    "patient_account_link", "role", "permission", "user_role", "role_permission",
}
UNIQUES = {
    "patient": {("patient_code",)},
    "staff": {("staff_code",)},
    "user_account": {("username",)},
    "staff_account_link": {("user_id",)},
    "patient_account_link": {("user_id",)},
    "role": {("role_code",)},
    "permission": {("permission_code",)},
    "user_role": {("user_id", "role_id")},
    "role_permission": {("role_id", "permission_id")},
}
FOREIGN_KEYS = {
    ("requesting_physician", "referring_facility_id", "referring_facility.referring_facility_id"),
    ("staff_account_link", "staff_id", "staff.staff_id"),
    ("staff_account_link", "user_id", "user_account.user_id"),
    ("patient_account_link", "patient_id", "patient.patient_id"),
    ("patient_account_link", "user_id", "user_account.user_id"),
    ("user_role", "user_id", "user_account.user_id"),
    ("user_role", "role_id", "role.role_id"),
    ("user_role", "assigned_by", "user_account.user_id"),
    ("role_permission", "role_id", "role.role_id"),
    ("role_permission", "permission_id", "permission.permission_id"),
}


def test_all_models_import_and_configure():
    configure_mappers()
    assert set(Base.metadata.tables) == TABLES
    assert len(Base.registry.mappers) == 12


@pytest.mark.parametrize("name", sorted(TABLES))
def test_keys_indexes_and_mysql_storage(name):
    table = Base.metadata.tables[name]
    assert {
        tuple(c.columns.keys()) for c in table.constraints
        if isinstance(c, sa.UniqueConstraint)
    } == UNIQUES.get(name, set())
    assert len(table.primary_key.columns) == 1
    pk = next(iter(table.primary_key.columns))
    assert isinstance(pk.type, sa.BigInteger)
    assert not pk.nullable
    assert pk.autoincrement is (not name.endswith("_account_link"))
    assert all(c.name for c in table.constraints)
    assert table.dialect_options["mysql"]["engine"] == "InnoDB"
    assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
    # Every FK has an explicit index, PK or leading unique-key column.
    indexed = {next(iter(i.columns)).name for i in table.indexes}
    indexed |= {
        next(iter(c.columns)).name for c in table.constraints
        if isinstance(c, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
    }
    assert {fk.parent.name for fk in table.foreign_keys} <= indexed


def test_exact_foreign_keys():
    assert {
        (table.name, fk.parent.name, fk.target_fullname)
        for table in Base.metadata.tables.values() for fk in table.foreign_keys
    } == FOREIGN_KEYS


def test_identity_and_credentials_remain_separate():
    assert "birth_date" in Patient.__table__.c
    assert not any("age" in c.name for c in Patient.__table__.c)
    for model in (Patient, Staff):
        assert not any("password" in c.name for c in model.__table__.c)
    account = UserAccount.__table__
    assert "password" not in account.c
    assert {c.name for c in account.c if "password" in c.name} == {"password_hash"}
    assert account.c.password_hash.type.length == 255
    assert not account.c.password_hash.nullable


def test_one_to_one_and_assignment_relationships():
    configure_mappers()
    for model, attr in [(Patient, "account_link"), (Staff, "account_link"),
                        (UserAccount, "patient_link"), (UserAccount, "staff_link")]:
        assert sa.inspect(model).relationships[attr].uselist is False
    mapper = sa.inspect(UserRole)
    assert {c.name for c in mapper.relationships.user.local_columns} == {"user_id"}
    assert {c.name for c in mapper.relationships.assigner.local_columns} == {"assigned_by"}


def test_enum_values_defaults_and_patient_name_index():
    assert Patient.__table__.c.sex.type.enums == ["M", "F", "Other"]
    assert UserAccount.__table__.c.account_status.type.enums == ["ACTIVE", "INACTIVE", "LOCKED"]
    assert Patient.__table__.c.sex.nullable
    assert not UserAccount.__table__.c.account_status.nullable
    for table in Base.metadata.tables.values():
        if "created_at" in table.c:
            assert not table.c.created_at.nullable
            assert str(table.c.created_at.server_default.arg) == "CURRENT_TIMESTAMP"
            assert table.c.updated_at.nullable
            assert table.c.updated_at.server_default is None
        if "is_active" in table.c:
            assert not table.c.is_active.nullable
            assert str(table.c.is_active.server_default.arg) == "1"
    assert UserRole.__table__.c.assigned_at.server_default is None
    assert not UserRole.__table__.c.assigned_at.nullable
    assert UserAccount.__table__.c.account_status.server_default is None
    assert ("last_name", "first_name") in {
        tuple(i.columns.keys()) for i in Patient.__table__.indexes
    }
    assert str(Patient.__table__.c.sex.type.compile(dialect=mysql.dialect())) == "ENUM('M','F','Other')"
