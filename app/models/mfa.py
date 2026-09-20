"""Encrypted TOTP configuration and hashed one-time authentication credentials."""
from datetime import datetime
from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class UserTotpMfa(Base):
    __tablename__ = 'user_totp_mfa'
    mfa_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user_account.user_id'), unique=True)
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary(12))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_counter: Mapped[int | None] = mapped_column(BigInteger)


class MfaRecoveryCode(Base):
    __tablename__ = 'mfa_recovery_code'
    recovery_code_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mfa_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user_totp_mfa.mfa_id'), index=True)
    code_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class MfaChallenge(Base):
    __tablename__ = 'mfa_challenge'
    challenge_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user_account.user_id'), index=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempt_count: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
