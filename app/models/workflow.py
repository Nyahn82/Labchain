"""Phase 2C transactional backbone; LAB_ORDER_ITEM is the requested-test anchor.

Cross-entity service rules and lifecycle validation are documented in
docs/PHASE_2C_LAB_WORKFLOW.md. No state transitions or clinical logic run here.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey, ForeignKeyConstraint,
    Index, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LabOrder(Base):
    __tablename__ = "lab_order"

    order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(30), unique=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patient.patient_id"), index=True)
    physician_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("requesting_physician.physician_id"), index=True
    )
    ordered_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    order_date: Mapped[datetime] = mapped_column(DateTime)
    priority: Mapped[str] = mapped_column(Enum("ROUTINE", "STAT", "URGENT", name="order_priority"))
    request_reason: Mapped[str | None] = mapped_column(String(150))
    clinical_notes: Mapped[str | None] = mapped_column(Text)
    # Working diagnosis supplied by an authorized healthcare professional only.
    diagnosis: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Enum(
        "REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="lab_order_status"
    ))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class OrderPanel(Base):
    __tablename__ = "order_panel"
    __table_args__ = (
        UniqueConstraint("order_id", "panel_id"),
        # Supporting key only: order_panel_id is already globally unique.
        UniqueConstraint("order_panel_id", "order_id"),
        Base.__table_args__,
    )

    order_panel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_order.order_id"))
    panel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_panel.panel_id"), index=True)
    status: Mapped[str] = mapped_column(Enum(
        "REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="order_panel_status"
    ))


class LabOrderItem(Base):
    __tablename__ = "lab_order_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_panel_id", "order_id"],
            ["order_panel.order_panel_id", "order_panel.order_id"],
            name="fk_lab_order_item_order_panel_id_order_id_order_panel",
        ),
        Index("ix_lab_order_item_order_panel_id_order_id", "order_panel_id", "order_id"),
        Base.__table_args__,
    )

    order_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_order.order_id"), index=True)
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_catalog.test_id"), index=True)
    order_panel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("order_panel.order_panel_id"))
    status: Mapped[str] = mapped_column(Enum(
        "REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="lab_order_item_status"
    ))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class LabPayment(Base):
    __tablename__ = "lab_payment"

    payment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_order.order_id"), index=True)
    payment_status: Mapped[str] = mapped_column(Enum(
        "PENDING", "PAID", "FREE", "WAIVED", "SUBSIDIZED", name="payment_status"
    ))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str | None] = mapped_column(String(50))
    reference_number: Mapped[str | None] = mapped_column(String(80))
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime)


class Specimen(Base):
    __tablename__ = "specimen"

    specimen_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    specimen_code: Mapped[str] = mapped_column(String(30), unique=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_order.order_id"), index=True)
    sample_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sample_type.sample_type_id"), index=True
    )
    collected_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    collected_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    specimen_status: Mapped[str] = mapped_column(Enum(
        "PENDING", "COLLECTED", "RECEIVED", "REJECTED", "PROCESSED", name="specimen_status"
    ))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class SpecimenOrderItem(Base):
    __tablename__ = "specimen_order_item"
    __table_args__ = (UniqueConstraint("specimen_id", "order_item_id"), Base.__table_args__)

    specimen_order_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    specimen_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("specimen.specimen_id"))
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_order_item.order_item_id"), index=True
    )


class RejectionReason(Base):
    __tablename__ = "rejection_reason"

    rejection_reason_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reason_code: Mapped[str] = mapped_column(String(40), unique=True)
    reason_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class SpecimenRejection(Base):
    __tablename__ = "specimen_rejection"

    specimen_rejection_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    specimen_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("specimen.specimen_id"), index=True)
    rejection_reason_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rejection_reason.rejection_reason_id"), index=True
    )
    details: Mapped[str | None] = mapped_column(Text)
    rejected_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    rejected_at: Mapped[datetime] = mapped_column(DateTime)
    recollection_required: Mapped[bool] = mapped_column(Boolean)


class LabResultItem(Base):
    """Display/numeric result and review provenance, independent of any report."""

    __tablename__ = "lab_result_item"

    result_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_order_item.order_item_id"), index=True
    )
    specimen_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("specimen.specimen_id"), index=True
    )
    reference_range_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reference_range.range_id"), index=True
    )
    result_value: Mapped[str] = mapped_column(String(100))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    flag: Mapped[str | None] = mapped_column(Enum(
        "NORMAL", "LOW", "HIGH", "CRITICAL_LOW", "CRITICAL_HIGH", "ABNORMAL", name="result_flag"
    ))
    status: Mapped[str] = mapped_column(Enum("DRAFT", "REVIEWED", "VERIFIED", name="result_status"))
    remarks: Mapped[str | None] = mapped_column(Text)
    encoded_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    encoded_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
