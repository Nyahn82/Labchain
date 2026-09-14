"""Logical blockchain support metadata only; no ledger or node processes.

MySQL remains the source of truth. Do not store patient names, full result values,
complete reports or other protected clinical content in these support records.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CHAR, DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


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
        Enum('PENDING', 'ACCEPTED', 'REJECTED', name="blockchain_event_event_status")
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.user_id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


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
