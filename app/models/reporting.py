"""Report versions and historical snapshots; generation and release rules are later services."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, CHAR, CheckConstraint, Date, DateTime, Enum, ForeignKey,
    Integer, String, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReportTemplate(Base):
    __tablename__ = "report_template"

    template_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_code: Mapped[str] = mapped_column(String(40), unique=True)
    template_name: Mapped[str] = mapped_column(String(100))
    panel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("test_panel.panel_id"), index=True)
    header_title: Mapped[str | None] = mapped_column(String(150))
    section_title: Mapped[str | None] = mapped_column(String(150))
    clinical_note: Mapped[str | None] = mapped_column(Text)
    footer_note: Mapped[str | None] = mapped_column(Text)
    medico_legal_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class LabReport(Base):
    __tablename__ = "lab_report"

    report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_code: Mapped[str] = mapped_column(String(30), unique=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_order.order_id"), index=True)
    facility_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("facility_profile.facility_id"), index=True
    )
    template_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("report_template.template_id"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer)
    supersedes_report_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("lab_report.report_id"), index=True
    )
    report_status: Mapped[str] = mapped_column(
        Enum('GENERATED', 'APPROVED', 'RELEASED', 'REVOKED', name="lab_report_report_status")
    )
    generated_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    released_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(String(255))
    remarks: Mapped[str | None] = mapped_column(Text)


class ReportResultItem(Base):
    __tablename__ = "report_result_item"

    report_result_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_report.report_id"), index=True)
    result_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_result_item.result_item_id"), index=True
    )
    panel_id_snapshot: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("test_panel.panel_id"), index=True
    )
    section_name_snapshot: Mapped[str | None] = mapped_column(String(120))
    test_name_snapshot: Mapped[str] = mapped_column(String(150))
    result_value_snapshot: Mapped[str] = mapped_column(String(100))
    unit_snapshot: Mapped[str | None] = mapped_column(String(50))
    reference_range_snapshot: Mapped[str | None] = mapped_column(String(120))
    flag_snapshot: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(Integer)


class ReportPatientSnapshot(Base):
    __tablename__ = "report_patient_snapshot"

    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_report.report_id"), primary_key=True, autoincrement=False
    )
    patient_code: Mapped[str] = mapped_column(String(20))
    patient_name: Mapped[str] = mapped_column(String(220))
    birth_date: Mapped[date | None] = mapped_column(Date)
    age_at_report: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(20))
    physician_name: Mapped[str | None] = mapped_column(String(220))


class Signatory(Base):
    __tablename__ = "signatory"

    signatory_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    staff_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("staff.staff_id"), index=True)
    signature_image_path: Mapped[str | None] = mapped_column(String(255))
    license_number_snapshot: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class ReportSignatory(Base):
    __tablename__ = "report_signatory"

    report_signatory_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_report.report_id"), index=True)
    signatory_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("signatory.signatory_id"), index=True)
    signatory_type: Mapped[str] = mapped_column(
        Enum('LAB_IN_CHARGE', 'MEDICAL_TECHNOLOGIST', 'PATHOLOGIST', name="report_signatory_signatory_type")
    )
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)
    sort_order: Mapped[int] = mapped_column(Integer)


class ReportVerification(Base):
    __tablename__ = "report_verification"

    verification_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_report.report_id"), index=True)
    verification_token: Mapped[str] = mapped_column(String(120), unique=True)
    report_hash: Mapped[str] = mapped_column(CHAR(64))
    verification_status: Mapped[str] = mapped_column(
        Enum('AUTHENTIC', 'REVOKED', name="report_verification_verification_status")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint("order_id IS NOT NULL OR report_id IS NOT NULL", name="parent_required"),
        Base.__table_args__,
    )

    attachment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lab_order.order_id"), index=True)
    report_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lab_report.report_id"), index=True)
    file_name: Mapped[str] = mapped_column(String(180))
    file_path: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(80))
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime)
