"""Rejection Reason automatic-code service integration tests.

Uses an isolated SQLite database, never production MySQL.
"""

import pytest

from fastapi import HTTPException
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, func, select
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import Session

from app.models import AuditLog, RejectionReason
from app.models.code_sequence import CodeSequence

from app.schemas.workflow import ReasonCreate, ReasonResponse
from app.services.laboratory_service import save_record


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    CodeSequence.__table__.create(engine)

    # SQLite requires INTEGER PRIMARY KEY for automatic row IDs.
    # Clone only the test DDL. Production models retain BIGINT.
    with engine.begin() as connection:
        for original in (
            RejectionReason.__table__,
            AuditLog.__table__,
        ):
            table = original.to_metadata(MetaData())

            for column in table.primary_key.columns:
                if isinstance(column.type, BigInteger):
                    column.type = Integer()

            # These focused tests do not create user_account.
            # Omit foreign keys only from the isolated SQLite DDL.
            connection.execute(
                CreateTable(
                    table,
                    include_foreign_key_constraints=[],
                )
            )

    with Session(engine) as session:
        session.add(
            CodeSequence(
                sequence_key="REJECTION_REASON",
                prefix="REJ",
                current_value=0,
                padding=3,
            )
        )
        session.commit()

        yield session

    engine.dispose()


def create_reason(db, name):
    return save_record(
        db,
        RejectionReason,
        ReasonCreate(reason_name=name),
        ReasonResponse,
        1,
        "127.0.0.1",
        "REJECTION_REASON_CREATE",
    )


def test_creation_generates_code_and_audit(db):
    first = create_reason(db, "Synthetic Clotted")
    second = create_reason(db, "Synthetic Hemolyzed")

    assert first.reason_code == "REJ-001"
    assert second.reason_code == "REJ-002"
    assert first.rejection_reason_id != second.rejection_reason_id

    rows = db.scalars(
        select(RejectionReason)
        .order_by(RejectionReason.rejection_reason_id)
    ).all()

    assert [row.reason_code for row in rows] == [
        "REJ-001",
        "REJ-002",
    ]

    counter = db.get(CodeSequence, "REJECTION_REASON")

    assert counter.current_value == 2

    audits = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "rejection_reason")
    ).all()

    assert len(audits) == 2

    assert all(
        event.action == "REJECTION_REASON_CREATE"
        for event in audits
    )


def test_collision_rolls_back_allocation(db):
    # Simulate an existing legacy record that already owns
    # the next sequence value.
    db.add(
        RejectionReason(
            reason_code="REJ-001",
            reason_name="Existing reason",
            is_active=True,
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as exc:
        create_reason(db, "Conflicting new reason")

    assert exc.value.status_code == 409

    db.expire_all()

    counter = db.get(CodeSequence, "REJECTION_REASON")

    # Failed creation must not consume the sequence.
    assert counter.current_value == 0

    reason_count = db.scalar(
        select(func.count()).select_from(RejectionReason)
    )

    audit_count = db.scalar(
        select(func.count()).select_from(AuditLog)
    )

    assert reason_count == 1
    assert audit_count == 0
