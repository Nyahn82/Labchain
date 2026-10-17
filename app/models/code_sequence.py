"""Transactional counters for automatically generated display codes."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CodeSequence(Base):
    __tablename__ = "code_sequence"
    __table_args__ = (
        CheckConstraint(
            "current_value >= 0",
            name="nonnegative_value",
        ),
        CheckConstraint(
            "padding >= 1 AND padding <= 16",
            name="valid_padding",
        ),
        Base.__table_args__,
    )

    sequence_key: Mapped[str] = mapped_column(
        String(40), primary_key=True
    )

    prefix: Mapped[str] = mapped_column(
        String(10), nullable=False
    )

    current_value: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )

    padding: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
