"""Phase 2B laboratory setup models; no catalog data or result evaluation."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Date, Enum, ForeignKey, ForeignKeyConstraint, Index,
    Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LabDepartment(Base):
    __tablename__ = "lab_department"

    department_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    department_code: Mapped[str] = mapped_column(String(30), unique=True)
    department_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class SampleType(Base):
    __tablename__ = "sample_type"

    sample_type_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sample_name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class TestCatalog(Base):
    __tablename__ = "test_catalog"

    test_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    test_code: Mapped[str] = mapped_column(String(30), unique=True)
    test_name: Mapped[str] = mapped_column(String(150))
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_department.department_id"), index=True
    )
    default_unit: Mapped[str | None] = mapped_column(String(50))
    result_type: Mapped[str] = mapped_column(
        Enum("NUMERIC", "TEXT", "POS_NEG", name="test_result_type")
    )
    methodology: Mapped[str | None] = mapped_column(String(150))
    default_sort_order: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class TestSampleType(Base):
    __tablename__ = "test_sample_type"
    __table_args__ = (UniqueConstraint("test_id", "sample_type_id"), Base.__table_args__)

    test_sample_type_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_catalog.test_id"))
    sample_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sample_type.sample_type_id"), index=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean)


class TestPanel(Base):
    __tablename__ = "test_panel"

    panel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    panel_code: Mapped[str] = mapped_column(String(30), unique=True)
    panel_name: Mapped[str] = mapped_column(String(120))
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("lab_department.department_id"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class PanelSection(Base):
    __tablename__ = "panel_section"
    __table_args__ = (
        # Supporting key for the same-panel FK; section_id is already unique.
        UniqueConstraint("section_id", "panel_id"),
        Base.__table_args__,
    )

    section_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    panel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_panel.panel_id"), index=True)
    section_name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class PanelTest(Base):
    __tablename__ = "panel_test"
    __table_args__ = (
        UniqueConstraint("panel_id", "test_id"),
        ForeignKeyConstraint(
            ["section_id", "panel_id"],
            ["panel_section.section_id", "panel_section.panel_id"],
            name="fk_panel_test_section_id_panel_id_panel_section",
        ),
        Index("ix_panel_test_section_id_panel_id", "section_id", "panel_id"),
        Base.__table_args__,
    )

    panel_test_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    panel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_panel.panel_id"))
    section_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("panel_section.section_id"))
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_catalog.test_id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean)


class ReferenceRange(Base):
    __tablename__ = "reference_range"

    range_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_catalog.test_id"), index=True)
    sex: Mapped[str] = mapped_column(Enum("M", "F", "ANY", name="reference_range_sex"))
    age_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    age_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    normal_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    normal_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    critical_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    critical_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    qualitative_normal: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str | None] = mapped_column(String(50))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class TestInterpretationRule(Base):
    """Approved general explanations only, never diagnoses or treatment plans."""

    __tablename__ = "test_interpretation_rule"
    __table_args__ = (UniqueConstraint("test_id", "flag"), Base.__table_args__)

    rule_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test_catalog.test_id"))
    flag: Mapped[str] = mapped_column(Enum(
        "NORMAL", "LOW", "HIGH", "CRITICAL_LOW", "CRITICAL_HIGH", "ABNORMAL",
        name="interpretation_flag",
    ))
    interpretation_text: Mapped[str | None] = mapped_column(Text)
    possible_causes: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
