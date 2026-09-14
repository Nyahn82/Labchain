"""Phase 2A identity models from the authoritative normalized workbook."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Index,
    String, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.auth import PatientAccountLink, StaffAccountLink


class FacilityProfile(Base):
    __tablename__ = "facility_profile"

    facility_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    facility_name: Mapped[str] = mapped_column(String(150))
    facility_type: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(Text)
    contact_number: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(150))
    logo_path: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Patient(Base):
    __tablename__ = "patient"
    __table_args__ = (
        Index("ix_patient_last_name_first_name", "last_name", "first_name"),
        Base.__table_args__,
    )

    patient_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    patient_code: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(60))
    middle_name: Mapped[str | None] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    suffix: Mapped[str | None] = mapped_column(String(20))
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(Enum('M', 'F', 'Other', name="patient_sex"))
    civil_status: Mapped[str | None] = mapped_column(String(20))
    nationality: Mapped[str | None] = mapped_column(String(60))
    contact_number: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(254))
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    account_link: Mapped[PatientAccountLink | None] = relationship(back_populates="patient")


class Staff(Base):
    __tablename__ = "staff"

    staff_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    staff_code: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(60))
    middle_name: Mapped[str | None] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    suffix: Mapped[str | None] = mapped_column(String(20))
    position_title: Mapped[str | None] = mapped_column(String(100))
    license_number: Mapped[str | None] = mapped_column(String(50))
    contact_number: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(254))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    account_link: Mapped[StaffAccountLink | None] = relationship(back_populates="staff")


class ReferringFacility(Base):
    __tablename__ = "referring_facility"

    referring_facility_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    facility_name: Mapped[str] = mapped_column(String(150))
    facility_type: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(Text)
    contact_number: Mapped[str | None] = mapped_column(String(30))

    physicians: Mapped[list[RequestingPhysician]] = relationship(
        back_populates="referring_facility"
    )


class RequestingPhysician(Base):
    __tablename__ = "requesting_physician"

    physician_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(60))
    middle_name: Mapped[str | None] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    suffix: Mapped[str | None] = mapped_column(String(20))
    license_number: Mapped[str | None] = mapped_column(String(50))
    specialization: Mapped[str | None] = mapped_column(String(100))
    referring_facility_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("referring_facility.referring_facility_id"), index=True
    )
    contact_number: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))

    referring_facility: Mapped[ReferringFacility | None] = relationship(back_populates="physicians")
