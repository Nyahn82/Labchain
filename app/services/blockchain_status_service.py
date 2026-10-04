"""Read-only MySQL projections. Never import the worker, Gateway or its settings."""
from datetime import datetime, timezone
import re

from sqlalchemy import func, select

from app.models import BlockchainEvent
from app.schemas import blockchain as s

LIFECYCLES = {'REPORT_RELEASED': 'release', 'REPORT_REVOKED': 'revocation', 'REPORT_SUPERSEDED': 'supersession'}
STATUSES = {'PENDING': 'PENDING', 'PROCESSING': 'PROCESSING', 'FAILED': 'RETRYING', 'DEAD': 'FAILED'}


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def global_status(db):
    event = BlockchainEvent
    # The status-leading outbox index supports grouping; no per-event ORM loads.
    rows = {row.event_status: row for row in db.execute(select(
        event.event_status, func.count().label('total'), func.min(event.created_at).label('oldest'),
        func.min(event.next_attempt_at).label('next_due'),
        func.min(event.lease_expires_at).label('first_expiry')
    ).group_by(event.event_status))}
    counts = {state.lower(): rows[state].total if state in rows else 0
              for state in ('PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD')}
    now = utc_now()
    processing = rows.get('PROCESSING')
    pending = rows.get('PENDING')
    if counts['dead']:
        health = 'ERROR'
    elif counts['failed'] or (processing and (processing.first_expiry is None or processing.first_expiry <= now)):
        health = 'DEGRADED'
    elif processing or (pending and pending.next_due <= now):
        health = 'ACTIVE'
    else:
        health = 'IDLE'
    latest = db.execute(select(event.confirmed_at, event.fabric_transaction_id).where(
        event.event_status == 'CONFIRMED', event.fabric_validation_code == 0
    ).order_by(event.confirmed_at.desc(), event.event_id.desc()).limit(1)).first()
    return s.BlockchainStatus(counts=s.OutboxCounts(**counts), worker_health=health,
        last_confirmed_at=latest.confirmed_at if latest else None,
        last_confirmed_transaction_id=latest.fabric_transaction_id if latest else None,
        oldest_pending_at=pending.oldest if pending else None)


def lifecycle_status(row, now):
    if row.event_status == 'CONFIRMED':
        if (row.fabric_validation_code == 0 and row.confirmed_at is not None
                and re.fullmatch(r'[0-9a-f]{64}', row.fabric_transaction_id or '')):
            return s.LifecycleAnchoring(status='CONFIRMED', confirmed_at=row.confirmed_at,
                transaction_id=row.fabric_transaction_id, block_number=row.fabric_block_number)
        return s.LifecycleAnchoring(status='FAILED')
    status = STATUSES.get(row.event_status, 'FAILED')
    if status == 'PROCESSING' and (row.lease_expires_at is None or row.lease_expires_at <= now):
        status = 'PENDING'  # Waiting for reclamation; no currently valid lease.
    return s.LifecycleAnchoring(status=status)


def report_anchoring(db, report, *, revoked=False):
    empty = s.LifecycleAnchoring(status='NOT_ANCHORED')
    if report.blockchain_entity_uuid is None:
        return s.ReportAnchoring(status='NOT_ANCHORED', release=empty)
    event = BlockchainEvent
    # ix_blockchain_event_entity narrows by REPORT + internal report ID. Also
    # require the frozen UUID; a synthetic sentinel or unrelated entity cannot match.
    rows = db.execute(select(event.event_type, event.event_status, event.confirmed_at,
        event.fabric_transaction_id, event.fabric_block_number, event.fabric_validation_code,
        event.lease_expires_at).where(event.entity_type == 'REPORT', event.entity_id == report.report_id,
        event.entity_reference == report.blockchain_entity_uuid, event.event_type.in_(LIFECYCLES))
        .order_by(event.event_id)).all()
    now = utc_now()
    lifecycle = {}
    priority = ('CONFIRMED', 'PENDING', 'PROCESSING', 'RETRYING', 'FAILED')
    for row in rows:
        name, item = LIFECYCLES[row.event_type], lifecycle_status(row, now)
        previous = lifecycle.get(name)
        if (previous is None or priority.index(item.status) > priority.index(previous.status)
                or (item.status == previous.status == 'CONFIRMED' and item.confirmed_at > previous.confirmed_at)):
            lifecycle[name] = item
    release = lifecycle.get('release', empty)
    if release.status == 'NOT_ANCHORED' or ((revoked or report.report_status == 'REVOKED')
            and not {'revocation', 'supersession'}.intersection(lifecycle)):
        status = 'NOT_ANCHORED'
    else:
        # Every captured lifecycle matters: a later pending/dead transition must
        # never be masked by a confirmed release (or another confirmed transition).
        states = {item.status for item in lifecycle.values()}
        status = next(value for value in ('FAILED', 'RETRYING', 'PROCESSING', 'PENDING', 'CONFIRMED') if value in states)
    return s.ReportAnchoring(status=status, release=release,
        revocation=lifecycle.get('revocation'), supersession=lifecycle.get('supersession'))


def safe_verification(anchoring):
    status = 'PENDING' if anchoring.status == 'PROCESSING' else anchoring.status
    confirmed_at = None
    if status == 'CONFIRMED':
        confirmed_at = max(item.confirmed_at for item in
            (anchoring.release, anchoring.revocation, anchoring.supersession) if item is not None)
    return s.PatientBlockchainVerification(status=status, confirmed_at=confirmed_at)
