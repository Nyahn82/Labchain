"""One-time activation security history; plaintext credentials are never persisted."""
from datetime import datetime

from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PatientActivationToken(Base):
    __tablename__ = 'patient_activation_token'

    activation_token_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('patient.patient_id'), index=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    issued_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user_account.user_id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
