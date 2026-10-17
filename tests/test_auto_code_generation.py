"""Automatic code-generation foundation tests.

These tests use only an isolated in-memory SQLite database.
They do not connect to production services.
"""

import pytest

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.code_sequence import CodeSequence
from app.models.identity import Patient, Staff
from app.models.laboratory import LabDepartment, TestCatalog as LabTestCatalog, TestPanel as LabTestPanel
from app.models.workflow import RejectionReason
from app.models.reporting import ReportTemplate
from app.schemas.identity import (
    PatientCreate,
    PatientPatch,
    StaffCreate,
    StaffPatch,
)
from app.services.code_generation_service import (
    MAX_COUNTER,
    allocate_code,
)


@pytest.fixture(params=[True, False], ids=["autoflush-on", "autoflush-off"])
def database(request):
    engine = create_engine("sqlite+pysqlite:///:memory:")

    CodeSequence.__table__.create(engine)

    with Session(engine, autoflush=request.param) as db:
        db.add_all([
            CodeSequence(
                sequence_key="PATIENT",
                prefix="PAT",
                current_value=0,
                padding=6,
            ),
            CodeSequence(
                sequence_key="STAFF",
                prefix="STF",
                current_value=0,
                padding=6,
            ),
        ])
        db.commit()

        yield db

    engine.dispose()


def test_patient_code_sequence(database):
    assert allocate_code(database, "PATIENT") == "PAT-000001"
    assert allocate_code(database, "PATIENT") == "PAT-000002"
    assert allocate_code(database, "PATIENT") == "PAT-000003"

    database.commit()

    row = database.get(CodeSequence, "PATIENT")
    assert row.current_value == 3


def test_staff_code_sequence(database):
    assert allocate_code(database, "STAFF") == "STF-000001"
    assert allocate_code(database, "STAFF") == "STF-000002"

    database.commit()

    row = database.get(CodeSequence, "STAFF")
    assert row.current_value == 2


def test_sequences_are_independent(database):
    patient = allocate_code(database, "PATIENT")
    staff = allocate_code(database, "STAFF")

    assert patient == "PAT-000001"
    assert staff == "STF-000001"

    database.commit()

    assert allocate_code(database, "PATIENT") == "PAT-000002"
    assert allocate_code(database, "STAFF") == "STF-000002"


def test_rollback_reuses_uncommitted_number(database):
    first = allocate_code(database, "PATIENT")

    assert first == "PAT-000001"

    database.rollback()

    again = allocate_code(database, "PATIENT")

    assert again == "PAT-000001"

    database.commit()


def test_committed_number_is_persistent(database):
    assert allocate_code(database, "PATIENT") == "PAT-000001"

    database.commit()
    database.expire_all()

    assert allocate_code(database, "PATIENT") == "PAT-000002"

    database.commit()


def test_missing_sequence_is_rejected(database):
    with pytest.raises(
        RuntimeError,
        match="Code sequence is not configured",
    ):
        allocate_code(database, "UNKNOWN")


def test_exhausted_sequence_is_rejected(database):
    sequence = database.get(CodeSequence, "PATIENT")
    sequence.current_value = MAX_COUNTER

    database.commit()

    with pytest.raises(
        RuntimeError,
        match="Code sequence exhausted",
    ):
        allocate_code(database, "PATIENT")


@pytest.mark.parametrize(
    "schema,code_field",
    [
        (PatientCreate, "patient_code"),
        (StaffCreate, "staff_code"),
    ],
)
def test_create_generates_code_server_side(schema, code_field):
    payload = schema.model_validate({
        "first_name": "Synthetic",
        "last_name": "Patient",
    })

    assert code_field not in payload.model_dump()


@pytest.mark.parametrize(
    "schema,code_field",
    [
        (PatientCreate, "patient_code"),
        (StaffCreate, "staff_code"),
    ],
)
def test_create_rejects_manual_code(schema, code_field):
    with pytest.raises(ValidationError) as exc:
        schema.model_validate({
            code_field: "MANUAL-001",
            "first_name": "Synthetic",
            "last_name": "Example",
        })

    assert any(
        error["type"] == "extra_forbidden"
        for error in exc.value.errors()
    )


@pytest.mark.parametrize(
    "schema,code_field",
    [
        (PatientPatch, "patient_code"),
        (StaffPatch, "staff_code"),
    ],
)
def test_patch_rejects_code_changes(schema, code_field):
    with pytest.raises(ValidationError) as exc:
        schema.model_validate({
            code_field: "CHANGED-001",
        })

    assert any(
        error["type"] == "extra_forbidden"
        for error in exc.value.errors()
    )


def test_multiple_allocations_rollback_together(database):
    codes = [allocate_code(database, "PATIENT") for _ in range(3)]
    assert codes == ["PAT-000001", "PAT-000002", "PAT-000003"]
    assert len(set(codes)) == 3
    database.rollback()

    assert database.get(CodeSequence, "PATIENT").current_value == 0
    assert allocate_code(database, "PATIENT") == "PAT-000001"
    database.commit()
    with Session(database.get_bind()) as observer:
        assert observer.get(CodeSequence, "PATIENT").current_value == 1


def test_allocation_flushes_only_its_sequence(database):
    staff = database.get(CodeSequence, "STAFF")
    staff.current_value = 41
    # A full flush would fail this unrelated, incomplete pending record.
    pending = CodeSequence(sequence_key="PENDING", current_value=0, padding=6)
    database.add(pending)

    assert allocate_code(database, "PATIENT") == "PAT-000001"
    assert allocate_code(database, "PATIENT") == "PAT-000002"
    assert staff in database.dirty
    assert pending in database.new
    values = dict(database.connection().execute(
        select(CodeSequence.sequence_key, CodeSequence.current_value)
    ).all())
    assert values == {"PATIENT": 2, "STAFF": 0}
    database.rollback()
    assert database.get(CodeSequence, "PATIENT").current_value == 0
    assert database.get(CodeSequence, "STAFF").current_value == 0


def test_repeated_allocations_at_exhaustion_roll_back(database):
    database.add(CodeSequence(
        sequence_key="DEPARTMENT", prefix="DEP", padding=3,
        current_value=MAX_COUNTER - 2,
    ))
    database.commit()

    assert allocate_code(database, "DEPARTMENT") == f"DEP-{MAX_COUNTER - 1}"
    assert allocate_code(database, "DEPARTMENT") == f"DEP-{MAX_COUNTER}"
    with pytest.raises(RuntimeError, match=r"^Code sequence exhausted\.$"):
        allocate_code(database, "DEPARTMENT")
    assert database.get(CodeSequence, "DEPARTMENT").current_value == MAX_COUNTER
    database.rollback()
    assert database.get(CodeSequence, "DEPARTMENT").current_value == MAX_COUNTER - 2


CAPACITY_CASES = [
    ("PATIENT", "PAT", 6, Patient.__table__.c.patient_code, 20, 9_999_999_999_999_999),
    ("STAFF", "STF", 6, Staff.__table__.c.staff_code, 20, 9_999_999_999_999_999),
    ("DEPARTMENT", "DEP", 3, LabDepartment.__table__.c.department_code, 30, MAX_COUNTER),
    ("TEST", "TST", 4, LabTestCatalog.__table__.c.test_code, 30, MAX_COUNTER),
    ("PANEL", "PNL", 4, LabTestPanel.__table__.c.panel_code, 30, MAX_COUNTER),
    ("REJECTION_REASON", "REJ", 3, RejectionReason.__table__.c.reason_code, 40, MAX_COUNTER),
    ("REPORT_TEMPLATE", "TMP", 3, ReportTemplate.__table__.c.template_code, 40, MAX_COUNTER),
]


@pytest.mark.parametrize("key,prefix,padding,column,length,limit", CAPACITY_CASES)
def test_capacity_boundary_and_next_value(database, key, prefix, padding, column, length, limit):
    assert column.type.length == length
    assert limit == min(MAX_COUNTER, 10 ** (length - len(prefix) - 1) - 1)
    sequence = database.get(CodeSequence, key)
    if sequence is None:
        sequence = CodeSequence(sequence_key=key, prefix=prefix, padding=padding)
        database.add(sequence)
    sequence.current_value = limit - 1
    database.commit()

    code = allocate_code(database, key)
    assert code == f"{prefix}-{limit}"
    assert len(code) <= length
    database.commit()
    timestamp = sequence.updated_at

    with pytest.raises(RuntimeError, match="Code sequence exhausted"):
        allocate_code(database, key)
    assert sequence.current_value == limit
    assert sequence.updated_at == timestamp
    assert sequence not in database.dirty
    # Even if the caller commits after catching the error, no increment leaked.
    database.commit()
    with Session(database.get_bind()) as observer:
        persisted = observer.get(CodeSequence, key)
        assert persisted.current_value == limit
        assert persisted.updated_at == timestamp


@pytest.mark.parametrize("key,prefix", [("PATIENT", "PAT"), ("STAFF", "STF")])
def test_capacity_failure_rolls_back_prior_valid_allocation(database, key, prefix):
    limit = 9_999_999_999_999_999
    database.get(CodeSequence, key).current_value = limit - 1
    database.commit()
    with pytest.raises(RuntimeError, match="capacity"):
        with database.begin():
            assert allocate_code(database, key) == f"{prefix}-{limit}"
            allocate_code(database, key)
    assert database.get(CodeSequence, key).current_value == limit - 1
    assert allocate_code(database, key) == f"{prefix}-{limit}"
    database.rollback()


@pytest.mark.parametrize("prefix,padding,current", [
    ("LONGPREFIX", 6, 999_999_999),  # 10-character prefix leaves nine digits.
    ("LONGPREFIX", 16, 0),         # Padding alone makes the code too long.
])
def test_capacity_guard_uses_actual_prefix_and_padding(database, prefix, padding, current):
    sequence = database.get(CodeSequence, "PATIENT")
    sequence.prefix = prefix
    sequence.padding = padding
    sequence.current_value = current
    database.commit()
    with pytest.raises(RuntimeError, match="capacity"):
        allocate_code(database, "PATIENT")
    assert sequence.current_value == current
    assert sequence.updated_at is None
    assert sequence not in database.dirty
    database.commit()
    database.expire_all()
    assert database.get(CodeSequence, "PATIENT").current_value == current


def test_unmapped_sequence_cannot_bypass_capacity_guard(database):
    database.add(CodeSequence(sequence_key="UNMAPPED", prefix="NEW", padding=3, current_value=0))
    database.commit()
    with pytest.raises(RuntimeError, match="Code sequence has no identifier column: UNMAPPED"):
        allocate_code(database, "UNMAPPED")
    database.commit()
    assert database.get(CodeSequence, "UNMAPPED").current_value == 0
