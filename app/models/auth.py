"""Phase 2A auth models from the authoritative normalized workbook."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.identity import Patient, Staff


class UserAccount(Base):
    __tablename__ = "user_account"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    account_status: Mapped[str] = mapped_column(
        Enum('ACTIVE', 'INACTIVE', 'LOCKED', name="account_status")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    staff_link: Mapped[StaffAccountLink | None] = relationship(back_populates="user")
    patient_link: Mapped[PatientAccountLink | None] = relationship(back_populates="user")
    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", foreign_keys="UserRole.user_id"
    )
    role_assignments: Mapped[list[UserRole]] = relationship(
        back_populates="assigner", foreign_keys="UserRole.assigned_by"
    )


class StaffAccountLink(Base):
    __tablename__ = "staff_account_link"

    staff_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("staff.staff_id"), primary_key=True, autoincrement=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), unique=True
    )

    staff: Mapped[Staff] = relationship(back_populates="account_link")
    user: Mapped[UserAccount] = relationship(back_populates="staff_link")


class PatientAccountLink(Base):
    __tablename__ = "patient_account_link"

    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patient.patient_id"), primary_key=True, autoincrement=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), unique=True
    )

    patient: Mapped[Patient] = relationship(back_populates="account_link")
    user: Mapped[UserAccount] = relationship(back_populates="patient_link")


class Role(Base):
    __tablename__ = "role"

    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(40), unique=True)
    role_name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))

    user_roles: Mapped[list[UserRole]] = relationship(back_populates="role")
    role_permissions: Mapped[list[RolePermission]] = relationship(back_populates="role")


class Permission(Base):
    __tablename__ = "permission"

    permission_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(80), unique=True)
    permission_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    role_permissions: Mapped[list[RolePermission]] = relationship(back_populates="permission")


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id"), Base.__table_args__)

    user_role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.user_id"))
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("role.role_id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime)
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )

    user: Mapped[UserAccount] = relationship(back_populates="user_roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(back_populates="user_roles")
    assigner: Mapped[UserAccount | None] = relationship(
        back_populates="role_assignments", foreign_keys=[assigned_by]
    )


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"), Base.__table_args__)

    role_permission_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("role.role_id"))
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permission.permission_id"), index=True
    )

    role: Mapped[Role] = relationship(back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_permissions")
