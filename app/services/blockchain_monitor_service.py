"""Read-only monitor projections and released-artifact integrity checks."""
from datetime import datetime, timezone
import hashlib
import json
import os
import stat

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models import BlockchainEvent, LabReport, ReportVerification
from app.models.blockchain import OutboxIntegrityError
from app.schemas import blockchain_monitor as s
from app.services import blockchain_monitor_client as monitor, report_storage
from app.services.blockchain_event_validation import validate_event


def now():
    return datetime.now(timezone.utc)


def overview():
    try:
        return monitor.query({'action': 'overview'}, s.Overview)
    except monitor.MonitorUnavailable:
        return s.Overview(channel='labchain-channel', topology='SINGLE_VPS', status='UNKNOWN',
            ledger_height=None, checked_at=now(), chaincode=None,
            orderer=s.Orderer(name='orderer', status='UNKNOWN', signal='TLS operations /healthz'),
            nodes=[s.Node(name=f'peer{i}', msp='Org1MSP' if i < 3 else 'Org2MSP', status='UNKNOWN',
                channel_member=None, height=None, current_block_hash=None, previous_block_hash=None,
                checked_at=now(), last_success_at=None, error_code='NOT_CONFIGURED') for i in range(1, 5)])


def ledger(request, schema):
    try:
        return monitor.query(request, schema)
    except monitor.MonitorUnavailable:
        raise HTTPException(503, 'Fabric query unavailable. No ledger conclusion can be drawn.') from None


def anchors(db, *, before=None, limit=20, status=None, event_type=None, block_number=None,
            transaction_id=None, entity_reference=None):
    e = BlockchainEvent
    # Explicit projection excludes clinical IDs, canonical data, leases and raw errors.
    statement = select(e.event_id, e.event_uuid, e.event_type, e.entity_type, e.entity_reference,
        e.event_status.label('status'), e.occurred_at, e.confirmed_at,
        e.fabric_transaction_id.label('transaction_id'), e.fabric_block_number.label('block_number'),
        e.record_hash, e.previous_hash).where(e.entity_type == 'REPORT')
    if before is not None:
        statement = statement.where(e.event_id < before)
    for column, value in ((e.event_status, status), (e.event_type, event_type),
                          (e.fabric_block_number, block_number), (e.fabric_transaction_id, transaction_id),
                          (e.entity_reference, entity_reference)):
        if value is not None:
            statement = statement.where(column == value)
    rows = db.execute(statement.order_by(e.event_id.desc()).limit(limit + 1)).mappings().all()
    return s.Anchors(items=[s.Anchor(**r) for r in rows[:limit]],
        next_before=rows[limit - 1]['event_id'] if len(rows) > limit else None)


def artifact_hash(relative):
    path = report_storage.safe_path(settings.report_storage_dir, relative)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        initial = os.fstat(stream.fileno())
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > 64 * 1024 * 1024:
            raise report_storage.ArtifactUnavailable()
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > 64 * 1024 * 1024:
                raise report_storage.ArtifactUnavailable()
            digest.update(chunk)
        final = os.fstat(stream.fileno())
        if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
            raise report_storage.ArtifactUnavailable()
        return digest.hexdigest()


def integrity(db, report_id):
    result = s.Integrity(report_id=report_id, status='UNKNOWN', checked_at=now())
    report = db.get(LabReport, report_id)
    if report is None:
        raise HTTPException(404, 'Report not found.')
    if report.report_status != 'RELEASED':
        result.status = 'REPORT_NOT_RELEASED'
        return result
    records = db.scalars(select(ReportVerification).where(ReportVerification.report_id == report_id)).all()
    if len(records) != 1 or records[0].verification_status != 'AUTHENTIC':
        return result
    result.report_hash = records[0].report_hash
    try:
        result.artifact_sha256 = artifact_hash(report.pdf_path)
    except FileNotFoundError:
        result.status = 'FILE_MISSING'
        return result
    except (OSError, ValueError, RuntimeError, report_storage.ArtifactUnavailable):
        return result
    if result.artifact_sha256 != result.report_hash:
        result.status = 'MISMATCH'
        return result
    rows = db.scalars(select(BlockchainEvent).where(BlockchainEvent.entity_type == 'REPORT',
        BlockchainEvent.entity_id == report_id, BlockchainEvent.entity_reference == report.blockchain_entity_uuid,
        BlockchainEvent.event_type == 'REPORT_RELEASED').limit(2)).all()
    if not rows or (len(rows) == 1 and rows[0].event_status != 'CONFIRMED'):
        result.status = 'NOT_ANCHORED'
        return result
    if len(rows) != 1:
        return result
    event = rows[0]
    try:
        validate_event(event)
        payload = json.loads(event.canonical_payload)
    except (OutboxIntegrityError, ValueError, TypeError):
        result.status = 'MISMATCH'
        return result
    result.record_hash = event.record_hash
    if payload['artifact_sha256'] != result.artifact_sha256 or payload['report_version'] != report.version_no:
        result.status = 'MISMATCH'
        return result
    try:
        evidence = monitor.query({'action': 'anchor', 'anchor_id': event.event_uuid}, s.AnchorEvidence)
        # Independently observe validation in a committed block; MySQL CONFIRMED alone is insufficient.
        tx = monitor.query({'action': 'transaction', 'transaction_id': evidence.transaction_id}, s.TransactionDetail)
    except monitor.MonitorUnavailable:
        return result
    result.ledger_content_hash = evidence.content_hash
    result.source_peer = evidence.source_peer
    matches = (evidence.anchor_id == event.event_uuid and evidence.entity_reference == event.entity_reference
        and evidence.event_type == event.event_type and evidence.content_hash == event.record_hash
        and evidence.previous_hash == event.previous_hash and evidence.transaction_id == event.fabric_transaction_id
        and tx.transaction_id == evidence.transaction_id and tx.validation_code == 0
        and tx.validation_status == 'VALID' and (event.fabric_block_number is None or tx.block_number == event.fabric_block_number))
    result.status = 'VERIFIED' if matches else 'MISMATCH'
    return result
