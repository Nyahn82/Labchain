"""Allocate unique display codes within the caller's transaction."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.code_sequence import CodeSequence
from app.models.identity import Patient, Staff
from app.models.laboratory import LabDepartment, TestCatalog, TestPanel
from app.models.reporting import ReportTemplate
from app.models.workflow import RejectionReason


MAX_COUNTER = 9223372036854775807

# Read capacities from the destination models, never from a database connection.
_CODE_COLUMNS = {
    "PATIENT": Patient.__table__.c.patient_code,
    "STAFF": Staff.__table__.c.staff_code,
    "DEPARTMENT": LabDepartment.__table__.c.department_code,
    "TEST": TestCatalog.__table__.c.test_code,
    "PANEL": TestPanel.__table__.c.panel_code,
    "REJECTION_REASON": RejectionReason.__table__.c.reason_code,
    "REPORT_TEMPLATE": ReportTemplate.__table__.c.template_code,
}


def allocate_code(db: Session, sequence_key: str) -> str:
    """Allocate a code without committing the caller's transaction.

    On MySQL/InnoDB, SELECT FOR UPDATE serializes allocations
    for the same sequence.

    Only the selected sequence is flushed; unrelated pending changes are
    left to the caller. No transaction is committed here.

    The caller must commit or roll back the record creation,
    sequence increment, and audit event together.
    """

    statement = (
        select(CodeSequence)
        .where(CodeSequence.sequence_key == sequence_key)
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )

    sequence = db.scalar(statement)

    if sequence is None:
        raise RuntimeError(
            f"Code sequence is not configured: {sequence_key}"
        )

    if sequence.current_value >= MAX_COUNTER:
        raise RuntimeError("Code sequence exhausted.")

    column = _CODE_COLUMNS.get(sequence_key)
    if column is None:
        raise RuntimeError(f"Code sequence has no identifier column: {sequence_key}")

    next_value = sequence.current_value + 1
    code = f"{sequence.prefix}-{next_value:0{sequence.padding}d}"
    # Padding is a minimum width, not a limit. Check the full candidate before
    # changing either the counter or timestamp; failure must consume nothing.
    if len(code) > column.type.length:
        raise RuntimeError(
            f"Code sequence exhausted: {sequence_key} exceeds "
            f"{column.table.name}.{column.name} capacity ({column.type.length} characters)."
        )

    sequence.current_value = next_value

    sequence.updated_at = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
    )

    # Persist only this counter inside the caller's transaction so the next
    # locking refresh sees our increment even when autoflush is disabled.
    db.flush([sequence])

    return code
