"""Forward-only MySQL capture. Caller owns the transaction and report/order locks."""
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.config import settings
from app.models import BlockchainEvent, BlockchainNode, ReportVerification
from app.models.blockchain import OutboxIntegrityError
from app.services.identity_service import audit

# Public re-exports retain the Phase 8B-1 producer API and exact validation logic.
from app.services.blockchain_event_validation import (
    EVENT_TYPES, PAYLOAD_KEYS, NODE_MSPS, UUID_PATTERN, HASH_PATTERN,
    require_uuid, require_hash, utc, canonicalize, validate_event,
)


def current(statement):
    # Current reads avoid stale repeatable-read snapshots after acquiring report locks.
    return statement.with_for_update().execution_options(populate_existing=True)


def capture(db, *, report, event_type, artifact_sha256, occurred_at, actor_id,
            predecessor=None, superseding_report=None):
    """No commit/session creation. Report/order locks serialize clinical producers."""
    if report.blockchain_entity_uuid is None:
        raise OutboxIntegrityError('Report blockchain identity is missing.')
    if event_type == 'REPORT_RELEASED':
        if predecessor is not None or superseding_report is not None:
            raise OutboxIntegrityError('Release cannot have a lifecycle predecessor.')
    elif predecessor is None or predecessor.event_type != 'REPORT_RELEASED' or predecessor.entity_id != report.report_id or predecessor.entity_reference != report.blockchain_entity_uuid:
        raise OutboxIntegrityError('Report release predecessor is inconsistent.')
    if predecessor is not None:
        validate_event(predecessor)
        if json.loads(predecessor.canonical_payload)['artifact_sha256'] != artifact_sha256:
            raise OutboxIntegrityError('Report artifact differs from its captured release.')
    dedup = f'{event_type}:{report.report_id}'
    if event_type == 'REPORT_SUPERSEDED':
        if superseding_report is None:
            raise OutboxIntegrityError('Replacement report is required.')
        dedup += f':{superseding_report.report_id}'
    elif superseding_report is not None:
        raise OutboxIntegrityError('Unexpected replacement report.')
    payload = canonicalize(event_type=event_type, entity_reference=report.blockchain_entity_uuid,
        report_version=report.version_no, artifact_sha256=artifact_sha256, occurred_at=occurred_at,
        previous_hash=predecessor.record_hash if predecessor else None,
        source_node=settings.blockchain_source_node, source_msp=settings.blockchain_source_msp,
        superseding_entity_reference=superseding_report.blockchain_entity_uuid if superseding_report else None)
    node = db.scalar(select(BlockchainNode).where(BlockchainNode.node_code == settings.blockchain_source_node))
    if node is None or not node.is_active:
        raise OutboxIntegrityError('Blockchain source registry is unavailable; run the node bootstrap.')
    values = dict(deduplication_key=dedup, origin_node_id=node.node_id, entity_type='REPORT',
        entity_id=report.report_id, entity_reference=report.blockchain_entity_uuid, event_type=event_type,
        canonical_payload=payload, record_hash=hashlib.sha256(payload.encode('utf-8')).hexdigest(),
        previous_hash=predecessor.record_hash if predecessor else None,
        predecessor_event_id=predecessor.event_id if predecessor else None,
        occurred_at=utc(occurred_at).replace(tzinfo=None), created_by_user_id=actor_id)
    # Also handle repeated calls before flush when the Session has autoflush disabled.
    existing = next((row for row in db.new if isinstance(row, BlockchainEvent) and row.deduplication_key == dedup), None)
    if existing is None:
        existing = db.scalar(current(select(BlockchainEvent).where(BlockchainEvent.deduplication_key == dedup)))
    if existing is not None:
        validate_event(existing)
        if any(getattr(existing, key) != value for key, value in values.items()):
            raise OutboxIntegrityError('Blockchain event deduplication conflict; manual integrity review required.')
        return existing
    row = BlockchainEvent(**values, event_uuid=str(uuid4()), event_status='PENDING', attempt_count=0,
        next_attempt_at=values['occurred_at'], updated_at=values['occurred_at'])
    validate_event(row)
    db.add(row)
    # Unique deduplication_key is the final race guard. Never swallow its failure:
    # a losing transaction rolls back with the report, then can safely retry.
    return row


def capture_release(db, report, digest, now, actor_id):
    if report.blockchain_entity_uuid is None:
        report.blockchain_entity_uuid = str(uuid4())
    return capture(db, report=report, event_type='REPORT_RELEASED', artifact_sha256=digest,
        occurred_at=now, actor_id=actor_id)


def capture_lifecycle(db, report, event_type, now, actor_id, *, superseding_report=None):
    release = db.scalar(current(select(BlockchainEvent).where(
        BlockchainEvent.deduplication_key == f'REPORT_RELEASED:{report.report_id}')))
    if report.blockchain_entity_uuid is None and release is None:
        # Persisted with the clinical operation. No token, reason, or identifying text.
        audit(db, actor_id, 'BLOCKCHAIN_CAPTURE_SKIPPED', 'lab_report', report.report_id, None,
            new={'reason_code': 'LEGACY_REPORT_NOT_ANCHORED', 'event_type': event_type})
        return None
    if report.blockchain_entity_uuid is None or release is None:
        raise OutboxIntegrityError('Captured report release event is missing or inconsistent.')
    # Read only the hash: refreshing the ORM verification here would overwrite
    # the caller's unflushed AUTHENTIC -> REVOKED change (autoflush is disabled).
    verifications = list(db.scalars(select(ReportVerification.report_hash).where(
        ReportVerification.report_id == report.report_id).with_for_update()))
    if len(verifications) != 1:
        raise OutboxIntegrityError('Report artifact verification is inconsistent.')
    return capture(db, report=report, event_type=event_type,
        artifact_sha256=verifications[0], occurred_at=now, actor_id=actor_id,
        predecessor=release, superseding_report=superseding_report)
