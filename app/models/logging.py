"""Delivery and application history storage; no sending or authentication logic.

Audit history is append-only by application policy. Future writers must exclude
passwords, password hashes, authentication tokens and encryption keys.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EmailLog(Base):
    __tablename__ = "email_log"

    email_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lab_report.report_id"), index=True)
    patient_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("patient.patient_id"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(Enum('PENDING', 'SENT', 'FAILED', name="email_log_status"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class PrintLog(Base):
    __tablename__ = "print_log"

    print_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lab_report.report_id"), index=True)
    printed_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    printed_at: Mapped[datetime] = mapped_column(DateTime)
    copies: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_log"

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user_account.user_id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[int | None] = mapped_column(BigInteger)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class LoginLog(Base):
    __tablename__ = "login_log"

    login_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user_account.user_id"), index=True)
    username_attempted: Mapped[str | None] = mapped_column(String(60))
    login_time: Mapped[datetime] = mapped_column(DateTime)
    logout_time: Mapped[datetime | None] = mapped_column(DateTime)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    status: Mapped[str] = mapped_column(Enum('SUCCESS', 'FAILED', name="login_log_status"))
