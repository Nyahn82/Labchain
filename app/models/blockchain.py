"""Transactional outbox and logical blockchain metadata; no network calls.

MySQL remains the source of truth. Do not store patient names, full result values,
complete reports or other protected clinical content in these support records.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CHAR, DateTime, Enum, ForeignKey, Integer, String, Text, text, CheckConstraint, Index, event, inspect, select
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.exc import SQLAlchemyError

from app.models.base import Base
from app.models.outbox_types import UUID_TYPE, TIME_TYPE, UINT_TYPE, UBIGINT_TYPE, CurrentTimestamp6


class BlockchainNode(Base):
    __tablename__ = "blockchain_node"

    node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_code: Mapped[str] = mapped_column(String(30), unique=True)
    port: Mapped[int] = mapped_column(Integer, unique=True)
    node_role: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class BlockchainEvent(Base):
    __tablename__ = "blockchain_event"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(CHAR(36), unique=True)
    origin_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("blockchain_node.node_id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(80))
    record_hash: Mapped[str] = mapped_column(CHAR(64))
    event_status: Mapped[str] = mapped_column(
        Enum('PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD', name="blockchain_event_event_status"),
        server_default=text("'PENDING'")
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    deduplication_key: Mapped[str] = mapped_column(String(160), unique=True)
    entity_reference: Mapped[str] = mapped_column(UUID_TYPE)
    canonical_payload: Mapped[str] = mapped_column(Text)
    previous_hash: Mapped[str | None] = mapped_column(CHAR(64))
    predecessor_event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey('blockchain_event.event_id'), index=True)
    predecessor: Mapped['BlockchainEvent | None'] = relationship(
        remote_side='BlockchainEvent.event_id', foreign_keys=[predecessor_event_id], viewonly=True)
    occurred_at: Mapped[datetime] = mapped_column(TIME_TYPE)
    attempt_count: Mapped[int] = mapped_column(UINT_TYPE, server_default=text('0'))
    next_attempt_at: Mapped[datetime] = mapped_column(TIME_TYPE)
    processing_started_at: Mapped[datetime | None] = mapped_column(TIME_TYPE)
    lease_token: Mapped[str | None] = mapped_column(UUID_TYPE)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIME_TYPE)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(512))
    fabric_transaction_id: Mapped[str | None] = mapped_column(CHAR(64))
    fabric_block_number: Mapped[int | None] = mapped_column(UBIGINT_TYPE)
    fabric_validation_code: Mapped[int | None] = mapped_column(Integer)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIME_TYPE)
    updated_at: Mapped[datetime] = mapped_column(TIME_TYPE, server_default=CurrentTimestamp6())

    __table_args__ = (
        CheckConstraint("event_status != 'PROCESSING' OR (processing_started_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)", name='processing_lease_required'),
        CheckConstraint("event_status != 'CONFIRMED' OR (fabric_transaction_id IS NOT NULL AND confirmed_at IS NOT NULL AND fabric_validation_code IS NOT NULL AND fabric_validation_code = 0)", name='confirmation_required'),
        CheckConstraint("event_type NOT IN ('REPORT_REVOKED', 'REPORT_SUPERSEDED') OR previous_hash IS NOT NULL", name='lifecycle_previous_required'),
        CheckConstraint('attempt_count >= 0', name='attempt_count_nonnegative'),
        Index('ix_blockchain_event_eligible', 'event_status', 'next_attempt_at', 'event_id'),
        Index('ix_blockchain_event_lease', 'event_status', 'lease_expires_at', 'event_id'),
        Index('ix_blockchain_event_entity', 'entity_type', 'entity_id', 'event_id'),
        Base.__table_args__,
    )


class OutboxIntegrityError(SQLAlchemyError):
    """Safe error message: never include conflicting payloads or clinical data."""


DELIVERY_FIELDS = frozenset({
    'event_status', 'attempt_count', 'next_attempt_at', 'processing_started_at',
    'lease_token', 'lease_expires_at', 'last_error_code', 'last_error',
    'fabric_transaction_id', 'fabric_block_number', 'fabric_validation_code',
    'confirmed_at', 'updated_at',
})


@event.listens_for(BlockchainEvent, 'before_update')
def protect_event(mapper, connection, target):
    table = BlockchainEvent.__table__
    original = connection.execute(select(table).where(
        table.c.event_id == inspect(target).identity[0])).mappings().one()
    if any(getattr(target, name) != original[name] for name in table.c.keys() if name not in DELIVERY_FIELDS):
        raise OutboxIntegrityError('Immutable blockchain event cannot be changed.')


@event.listens_for(BlockchainEvent, 'before_insert')
@event.listens_for(BlockchainEvent, 'before_update')
def validate_event(mapper, connection, target):
    from app.services.blockchain_outbox_service import validate_event as validate
    validate(target)


@event.listens_for(BlockchainEvent, 'before_delete')
def protect_event_delete(mapper, connection, target):
    raise OutboxIntegrityError('Blockchain events cannot be deleted through the application.')


class BlockchainVerificationLog(Base):
    __tablename__ = "blockchain_verification_log"

    verification_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("blockchain_event.event_id"), index=True)
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("blockchain_node.node_id"), index=True)
    database_hash: Mapped[str] = mapped_column(CHAR(64))
    chain_hash: Mapped[str] = mapped_column(CHAR(64))
    verification_status: Mapped[str] = mapped_column(
        Enum('MATCH', 'MISMATCH', 'NOT_FOUND', name="blockchain_verification_log_verification_status")
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime)
    details: Mapped[str | None] = mapped_column(Text)


class BlockchainSyncLog(Base):
    __tablename__ = "blockchain_sync_log"

    sync_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("blockchain_node.node_id"), index=True)
    target_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("blockchain_node.node_id"), index=True)
    block_height: Mapped[int | None] = mapped_column(BigInteger)
    sync_status: Mapped[str] = mapped_column(
        Enum('SUCCESS', 'FAILED', 'CONFLICT', name="blockchain_sync_log_sync_status")
    )
    synced_at: Mapped[datetime] = mapped_column(DateTime)
    details: Mapped[str | None] = mapped_column(Text)
