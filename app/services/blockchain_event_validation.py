"""Pure immutable-event validation; no web configuration, DB engine or network."""
from datetime import datetime, timezone
import hashlib
import json
import re
from app.models.blockchain import OutboxIntegrityError

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
