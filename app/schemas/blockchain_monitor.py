"""Strict, bounded public projections of private Fabric query results."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Number = Annotated[int, Field(ge=0, le=9007199254740991)]
State = Literal['ONLINE', 'DEGRADED', 'OFFLINE', 'UNKNOWN']


class SafeModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Node(SafeModel):
    name: Literal['peer1', 'peer2', 'peer3', 'peer4']
    msp: Literal['Org1MSP', 'Org2MSP']
    status: State
    channel_member: bool | None
    height: Number | None
    current_block_hash: Hash | None
    previous_block_hash: Hash | None
    checked_at: datetime
    last_success_at: datetime | None
    error_code: Literal['TIMEOUT', 'UNAVAILABLE', 'NOT_CONFIGURED', 'QUERY_FAILED', 'INVALID_RESPONSE', 'INVALID_NUMBER'] | None


class Orderer(SafeModel):
    name: Literal['orderer']
    status: State
    signal: Literal['TLS operations /healthz']
    height: None = None


class Chaincode(SafeModel):
    name: Literal['labchain-anchor']
    version: Annotated[str, Field(pattern=r'^[A-Za-z0-9._-]{1,64}$')]
    sequence: Number
    endorsement_policy: Annotated[str, Field(max_length=160, pattern=r'^(\/[A-Za-z0-9/_-]+|Signature policy \(details withheld\))$')]


class Overview(SafeModel):
    channel: Literal['labchain-channel']
    topology: Literal['SINGLE_VPS']
    status: State
    ledger_height: Number | None
    checked_at: datetime
    nodes: Annotated[list[Node], Field(min_length=4, max_length=4)]
    orderer: Orderer
    chaincode: Chaincode | None


class Transaction(SafeModel):
    transaction_id: Hash | None
    validation_code: Annotated[int, Field(ge=0, le=255)] | None
    validation_status: Annotated[str, Field(pattern=r'^[A-Z_]{1,64}$')]
    timestamp: datetime | None


class BlockSummary(SafeModel):
    number: Number
    block_hash: Hash
    previous_block_hash: Hash | None
    transaction_count: Annotated[int, Field(ge=0, le=1000)]
    timestamp: datetime | None


class Observation(SafeModel):
    source_peer: Literal['peer1']
    checked_at: datetime


class Block(BlockSummary, Observation):
    transactions: Annotated[list[Transaction], Field(max_length=1000)]


class Blocks(Observation):
    items: Annotated[list[BlockSummary], Field(max_length=10)]
    next_before: Number | None
    ledger_height: Number


class TransactionDetail(Transaction, Observation):
    block_number: Number
    block_hash: Hash


class AnchorEvidence(Observation):
    anchor_id: Annotated[str, Field(pattern=r'^[0-9a-f-]{36}$')]
    entity_reference: Annotated[str, Field(pattern=r'^[0-9a-f-]{36}$')]
    event_type: Literal['REPORT_RELEASED', 'REPORT_REVOKED', 'REPORT_SUPERSEDED']
    content_hash: Hash
    previous_hash: Hash | None
    transaction_id: Hash


class Anchor(SafeModel):
    event_id: int
    event_uuid: str
    event_type: str
    entity_type: Literal['REPORT']
    entity_reference: str
    status: Literal['PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD']
    occurred_at: datetime
    confirmed_at: datetime | None
    transaction_id: Hash | None
    block_number: Number | None
    record_hash: Hash
    previous_hash: Hash | None


class Anchors(SafeModel):
    items: list[Anchor]
    next_before: int | None


class Integrity(SafeModel):
    report_id: int
    status: Literal['VERIFIED', 'MISMATCH', 'NOT_ANCHORED', 'REPORT_NOT_RELEASED', 'FILE_MISSING', 'UNKNOWN']
    checked_at: datetime
    artifact_sha256: Hash | None = None
    report_hash: Hash | None = None
    record_hash: Hash | None = None
    ledger_content_hash: Hash | None = None
    source_peer: Literal['peer1'] | None = None
