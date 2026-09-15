"""Server-side opaque session storage for browser authentication."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuthSession(Base):
    __tablename__ = "auth_session"

    session_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.user_id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped["UserAccount"] = relationship("UserAccount", foreign_keys=[user_id])
