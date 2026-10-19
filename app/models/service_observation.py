"""Bounded worker liveness observations, independent of clinical/outbox data."""
from datetime import datetime
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class ServiceObservation(Base):
    __tablename__ = 'service_observation'

    service: Mapped[str] = mapped_column(String(40), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
