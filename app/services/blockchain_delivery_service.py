"""Durable delivery only: short claims, remote work outside transactions, fenced ACKs."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import random
import time
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import and_, select, update

from app.models.blockchain import BlockchainEvent, BlockchainNode, DELIVERY_FIELDS, OutboxIntegrityError
from app.services.blockchain_adapter_service import DeliveryError, ERRORS, WorkerOptions, block_number
from app.services.blockchain_event_validation import validate_event, utc

logger = logging.getLogger(__name__)
TABLE = BlockchainEvent.__table__
CLEAR_LEASE = dict(lease_token=None, lease_expires_at=None, processing_started_at=None)
# Even malformed successful replies may follow a commit. Reconcile before classifying.
UNCERTAIN = frozenset({'SUBMISSION_FAILED', 'COMMIT_TIMEOUT', 'ADAPTER_TIMEOUT',
    'ADAPTER_PROCESS_FAILED', 'ANCHOR_CONFLICT', 'INVALID_RESPONSE', 'INTERNAL_ERROR'})


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Claim:
    event_id: int
    event_uuid: str
    event_type: str
    entity_reference: str
    record_hash: str
    previous_hash: str | None
    source_node: str
    source_msp: str
    attempt: int
    lease_token: str
    lease_expires_at: datetime

    def request(self):
        # Exact six chaincode arguments; no clinical data or internal identifiers.
        return dict(action='submit_anchor', anchorId=self.event_uuid, eventType=self.event_type,
                    entityReference=self.entity_reference, contentHash=self.record_hash,
                    previousHash=self.previous_hash or '', sourceNode=self.source_node)

    def expected_anchor(self):
        return dict(anchor_id=self.event_uuid, event_type=self.event_type, entity_type='REPORT',
                    entity_reference=self.entity_reference, content_hash=self.record_hash,
                    previous_hash=self.previous_hash, source_node=self.source_node, source_msp=self.source_msp)


def backoff(attempt, options, jitter=random.random):
    # Clamp before exponentiation. Sum, including jitter, never exceeds retry_max.
    base = min(options.retry_max, options.retry_base * 2 ** min(max(attempt - 1, 0), 30))
    return min(options.retry_max, base + min(1.0, max(0.0, jitter())) * min(base * 0.1, 5))


def _delivery_update(db, where, values):
    # Core intentionally bypasses ORM immutable-data validation only for delivery
    # fields, so even a corrupt immutable payload can be quarantined as DEAD.
    # No caller may repair or rewrite frozen columns through this helper.
    if not set(values) <= DELIVERY_FIELDS:
        raise ValueError('Only delivery fields may be changed.')
    return db.execute(update(TABLE).where(where).values(**values)).rowcount


class DeliveryWorker:
    def __init__(self, session_factory, adapter, options=None, *, now=utc_now,
                 monotonic=time.monotonic, jitter=random.random):
        self.sessions = session_factory
        self.adapter = adapter
        self.options = options or WorkerOptions()
        self.now = now
        self.monotonic = monotonic
        self.jitter = jitter

    def _now(self):
        return utc(self.now()).replace(tzinfo=None)

    def _quarantine(self, db, event_id, code, now):
        _delivery_update(db, TABLE.c.event_id == event_id, dict(
            event_status='DEAD', last_error_code=code, last_error=ERRORS[code][1][:512],
            updated_at=now, **CLEAR_LEASE))
        # event_id only: corrupt immutable text must never reach logs.
        logger.info('blockchain_delivery event_id=%d state=DEAD error_code=%s', event_id, code)

    @staticmethod
    def _candidate(db, now):
        # A combined OR + filesort can lock every eligible row before LIMIT in
        # InnoDB. Each existing index supplies this query's filter AND ordering.
        # Recover expired work first, then due retries, then new events.
        for status, due, index in (
            ('PROCESSING', TABLE.c.lease_expires_at, 'ix_blockchain_event_lease'),
            ('FAILED', TABLE.c.next_attempt_at, 'ix_blockchain_event_eligible'),
            ('PENDING', TABLE.c.next_attempt_at, 'ix_blockchain_event_eligible'),
        ):
            query = (select(TABLE).where(TABLE.c.event_status == status, due <= now)
                .order_by(due, TABLE.c.event_id).limit(1)
                .with_hint(TABLE, f'FORCE INDEX ({index})', dialect_name='mysql')
                .with_for_update(skip_locked=True))
            values = db.execute(query).mappings().first()
            if values is not None:
                return values
        return None

    def claim(self):
        now = self._now()
        with self.sessions.begin() as db:
            if db.get_bind().dialect.name == 'mysql':
                # Queue claims do not need repeatable-read gap locks. This is
                # local to this transaction/connection, not the application's engine.
                db.connection(execution_options={'isolation_level': 'READ COMMITTED'})
            # Bound scans/locks per transaction, including blocked lifecycle rows.
            for _ in range(32):
                values = self._candidate(db, now)
                if values is None:
                    return None
                row = SimpleNamespace(**values)
                try:
                    validate_event(row)
                    payload = json.loads(row.canonical_payload)
                    node = db.execute(select(BlockchainNode.node_code, BlockchainNode.is_active).where(
                        BlockchainNode.node_id == row.origin_node_id)).first()
                    if (node is None or not node.is_active or node.node_code != payload['source_node']
                            or payload['source_node'] != self.options.source_node
                            or payload['source_msp'] != self.options.source_msp):
                        raise OutboxIntegrityError('Frozen source is inconsistent.')
                    if row.predecessor_event_id is not None:
                        predecessor = db.execute(select(TABLE).where(
                            TABLE.c.event_id == row.predecessor_event_id)).mappings().first()
                        if predecessor is None:
                            raise OutboxIntegrityError('Release predecessor is missing.')
                        previous = SimpleNamespace(**predecessor)
                        validate_event(previous)
                        if (previous.event_type != 'REPORT_RELEASED' or previous.entity_id != row.entity_id
                                or previous.entity_reference != row.entity_reference
                                or previous.record_hash != row.previous_hash
                                or previous.origin_node_id != row.origin_node_id):
                            raise OutboxIntegrityError('Release predecessor is inconsistent.')
                        if previous.event_status == 'DEAD':
                            self._quarantine(db, row.event_id, 'PREDECESSOR_DEAD', now)
                            continue
                        if previous.event_status != 'CONFIRMED':
                            # Returning an expired dependent lease to PENDING is safe
                            # under its row lock, and makes next_attempt_at effective.
                            _delivery_update(db, TABLE.c.event_id == row.event_id, dict(
                                event_status='PENDING', next_attempt_at=now + timedelta(seconds=self.options.poll),
                                updated_at=now, **CLEAR_LEASE))
                            continue
                except (OutboxIntegrityError, TypeError, ValueError, KeyError, RecursionError):
                    self._quarantine(db, row.event_id, 'OUTBOX_INTEGRITY_FAILURE', now)
                    continue
                if row.attempt_count >= self.options.max_attempts and row.event_status != 'PROCESSING':
                    self._quarantine(db, row.event_id, 'MAX_ATTEMPTS', now)
                    continue
                # One final read-only recovery claim can recover a commit lost on
                # the last permitted attempt. It may never submit another write.
                token = str(uuid4())
                expires = now + timedelta(seconds=self.options.lease)
                attempt = row.attempt_count + 1
                _delivery_update(db, TABLE.c.event_id == row.event_id, dict(
                    event_status='PROCESSING', processing_started_at=now, lease_token=token,
                    lease_expires_at=expires, attempt_count=attempt, updated_at=now))
                claimed = Claim(row.event_id, row.event_uuid, row.event_type, row.entity_reference,
                    row.record_hash, row.previous_hash, payload['source_node'], payload['source_msp'],
                    attempt, token, expires)
                break
            else:
                return None
        # Transaction committed and connection returned before any adapter call.
        logger.info('blockchain_delivery event_id=%d event_type=%s attempt=%d state=PROCESSING',
                    claimed.event_id, claimed.event_type, claimed.attempt)
        return claimed

    def _finish(self, claim, values):
        with self.sessions.begin() as db:
            changed = _delivery_update(db, and_(TABLE.c.event_id == claim.event_id,
                TABLE.c.event_status == 'PROCESSING', TABLE.c.lease_token == claim.lease_token),
                dict(**values, updated_at=self._now(), **CLEAR_LEASE))
        if changed:
            logger.info('blockchain_delivery event_id=%d event_type=%s attempt=%d state=%s error_code=%s transaction_id=%s',
                claim.event_id, claim.event_type, claim.attempt, values['event_status'],
                values.get('last_error_code') or '-', values.get('fabric_transaction_id') or '-')
        else:
            logger.info('blockchain_delivery event_id=%d state=LEASE_LOST', claim.event_id)
        return bool(changed)

    def confirm(self, claim, anchor, block=None):
        # Adapter validates types; compare every immutable semantic field here.
        if any(anchor[key] != value for key, value in claim.expected_anchor().items()):
            raise DeliveryError('ANCHOR_CONFLICT')
        return self._finish(claim, dict(event_status='CONFIRMED',
            fabric_transaction_id=anchor['transaction_id'], fabric_validation_code=0,
            fabric_block_number=block, confirmed_at=self._now(), last_error_code=None, last_error=None))

    def fail(self, claim, error):
        retry = error.retryable and claim.attempt < self.options.max_attempts
        values = dict(event_status='FAILED' if retry else 'DEAD',
                      last_error_code=error.code, last_error=ERRORS[error.code][1][:512])
        if retry:
            values['next_attempt_at'] = self._now() + timedelta(seconds=backoff(claim.attempt, self.options, self.jitter))
        return self._finish(claim, values)

    def deliver(self, claim):
        # All subprocesses in this attempt share ONE budget, shorter than the
        # lease. Delays between claim and invocation also reduce that budget.
        budget = min(self.options.timeout, (claim.lease_expires_at - self._now()).total_seconds() - 10)
        deadline = self.monotonic() + max(0, budget)

        def call(action, *, reserve=0):
            remaining = deadline - self.monotonic() - reserve
            if remaining <= 0:
                raise DeliveryError('ADAPTER_TIMEOUT')
            request = claim.request() if action == 'submit_anchor' else dict(action=action, anchorId=claim.event_uuid)
            return self.adapter.call(request, timeout=remaining)

        def reconcile():
            anchor = call('read_anchor')
            return self.confirm(claim, anchor)

        submitted = False
        try:
            if call('anchor_exists'):
                return reconcile()
            if claim.attempt > self.options.max_attempts:
                raise DeliveryError('MAX_ATTEMPTS')
            submitted = True
            # Reserve up to 15 seconds for reconciliation after a lost ACK.
            result = call('submit_anchor', reserve=min(15, max(0, budget / 6)))
            submitted = False  # semantic conflicts are permanent, not duplicate-submit errors
            return self.confirm(claim, result['anchor'], block_number(result['block_number']))
        except DeliveryError as error:
            # A semantic mismatch is already authoritative; never resubmit it.
            if submitted and error.code in UNCERTAIN:
                try:
                    return reconcile()
                except DeliveryError as recovery_error:
                    if recovery_error.code == 'ANCHOR_CONFLICT':
                        error = recovery_error
                    elif error.code == 'ANCHOR_CONFLICT':
                        # Duplicate submit + unavailable read needs a later read,
                        # rather than incorrectly declaring a content conflict.
                        error = DeliveryError('COMMIT_TIMEOUT')
            return self.fail(claim, error)

    def cycle(self, stopping=None):
        count = 0
        for _ in range(self.options.batch):
            if stopping is not None and stopping.is_set():
                break
            claim = self.claim()
            if claim is None:
                break
            self.deliver(claim)
            count += 1
        return count
