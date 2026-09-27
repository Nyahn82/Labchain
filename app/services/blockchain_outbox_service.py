"""Forward-only MySQL capture. Caller owns the transaction and report/order locks."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import select

from app.config import settings
from app.models import BlockchainEvent, BlockchainNode, ReportVerification
from app.models.blockchain import OutboxIntegrityError
from app.services.identity_service import audit

EVENT_TYPES = frozenset({'REPORT_RELEASED', 'REPORT_REVOKED', 'REPORT_SUPERSEDED'})
PAYLOAD_KEYS = frozenset({
    'schema_version', 'event_type', 'entity_type', 'entity_reference', 'report_version',
    'artifact_sha256', 'occurred_at', 'previous_hash', 'source_node', 'source_msp',
    'superseding_entity_reference',
})
NODE_MSPS = {'node1': 'Org1MSP', 'node2': 'Org1MSP', 'node3': 'Org2MSP', 'node4': 'Org2MSP'}
UUID_PATTERN = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
HASH_PATTERN = re.compile(r'[0-9a-f]{64}')


def require_uuid(value):
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        raise OutboxIntegrityError('Blockchain identity must be a lowercase UUIDv4.')
    return value


def require_hash(value):
    if not isinstance(value, str) or not HASH_PATTERN.fullmatch(value):
        raise OutboxIntegrityError('Blockchain hash must be lowercase SHA-256 hex.')
    return value


def utc(value):
    if not isinstance(value, datetime):
        raise OutboxIntegrityError('Blockchain event timestamp is required.')
    # The application's existing naive datetimes represent UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def canonicalize(*, event_type, entity_reference, report_version, artifact_sha256,
                 occurred_at, previous_hash=None, source_node, source_msp,
                 superseding_entity_reference=None):
    """Keyword-only allowlist: arbitrary report/clinical fields cannot enter JSON."""
    if event_type not in EVENT_TYPES or type(report_version) is not int or report_version < 1:
        raise OutboxIntegrityError('Invalid blockchain lifecycle metadata.')
    require_uuid(entity_reference)
    require_hash(artifact_sha256)
    if NODE_MSPS.get(source_node) != source_msp or source_msp is None:
        raise OutboxIntegrityError('Blockchain source node and MSP do not match.')
    if previous_hash is not None:
        require_hash(previous_hash)
    if (event_type == 'REPORT_RELEASED') != (previous_hash is None):
        raise OutboxIntegrityError('Invalid lifecycle previous hash.')
    if event_type == 'REPORT_SUPERSEDED':
        require_uuid(superseding_entity_reference)
        if superseding_entity_reference == entity_reference:
            raise OutboxIntegrityError('A report cannot supersede itself.')
    elif superseding_entity_reference is not None:
        raise OutboxIntegrityError('Unexpected superseding identity.')
    payload = dict(schema_version=1, event_type=event_type, entity_type='REPORT',
        entity_reference=entity_reference, report_version=report_version,
        artifact_sha256=artifact_sha256, occurred_at=utc(occurred_at).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        previous_hash=previous_hash, source_node=source_node, source_msp=source_msp,
        superseding_entity_reference=superseding_entity_reference)
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def validate_event(row):
    """Duplicate critical DB guards and verify frozen canonical data on ORM writes."""
    require_uuid(row.event_uuid)
    require_uuid(row.entity_reference)
    require_hash(row.record_hash)
    try:
        payload = json.loads(row.canonical_payload)
        if set(payload) != PAYLOAD_KEYS or type(payload['schema_version']) is not int or payload['schema_version'] != 1:
            raise ValueError()
        if payload['entity_type'] != 'REPORT':
            raise ValueError()
        values = {key: value for key, value in payload.items() if key not in {'schema_version', 'entity_type'}}
        values['occurred_at'] = datetime.strptime(values['occurred_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
        if canonicalize(**values) != row.canonical_payload:
            raise ValueError()
        if any(payload[key] != getattr(row, key) for key in ('event_type', 'entity_type', 'entity_reference', 'previous_hash')):
            raise ValueError()
        if utc(row.occurred_at) != utc(values['occurred_at']):
            raise ValueError()
        if hashlib.sha256(row.canonical_payload.encode('utf-8')).hexdigest() != row.record_hash:
            raise ValueError()
    except (TypeError, ValueError, KeyError):
        raise OutboxIntegrityError('Invalid canonical blockchain event.') from None
    if (row.event_type == 'REPORT_RELEASED') != (row.predecessor_event_id is None):
        raise OutboxIntegrityError('Invalid lifecycle predecessor.')
    status = row.event_status or 'PENDING'
    if status not in {'PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD'}:
        raise OutboxIntegrityError('Invalid blockchain delivery status.')
    if row.attempt_count is not None and (type(row.attempt_count) is not int or row.attempt_count < 0):
        raise OutboxIntegrityError('Invalid blockchain attempt count.')
    if status == 'PROCESSING':
        if any(getattr(row, key) is None for key in ('processing_started_at', 'lease_token', 'lease_expires_at')):
            raise OutboxIntegrityError('Processing requires a complete lease.')
        require_uuid(row.lease_token)
    if status == 'CONFIRMED':
        if row.confirmed_at is None or row.fabric_validation_code != 0:
            raise OutboxIntegrityError('Confirmation requires a valid commit receipt.')
        require_hash(row.fabric_transaction_id)


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
