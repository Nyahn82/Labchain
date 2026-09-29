"""Delivery tests use synthetic SQLite data and fake Gateway calls only."""
from datetime import timedelta
import hashlib
import json
import logging
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Integer, MetaData, create_engine, event, update
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.services.blockchain_adapter_service import DeliveryError, WorkerOptions
from app.services.blockchain_delivery_service import DeliveryWorker, TABLE, backoff, _delivery_update
from phase8b_delivery_support import NOW, TX, FakeAdapter, anchor, seed, state


@pytest.fixture
def factory(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'delivery.sqlite'))
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        clone = table.to_metadata(metadata)
        for column in clone.primary_key:
            if column.autoincrement:
                column.type = Integer()
    metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def worker(factory, *responses, **kw):
    return DeliveryWorker(factory, FakeAdapter(*responses), now=lambda: NOW, jitter=lambda: 0, **kw)


def mutate(factory, number=1, **values):
    # Intentional raw tampering of synthetic data, bypassing producer ORM guards.
    with factory.begin() as db:
        db.execute(update(TABLE).where(TABLE.c.event_id == number).values(**values))


def test_claim_mapping_and_privacy(factory, caplog):
    caplog.set_level(logging.INFO)
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    row = state(factory)
    assert row['event_status'] == 'PROCESSING' and row['attempt_count'] == 1
    assert str(UUID(row['lease_token'])) == row['lease_token'] and UUID(row['lease_token']).version == 4
    assert row['lease_expires_at'] == NOW + timedelta(seconds=120)
    assert row['processing_started_at'] == row['updated_at'] == NOW
    assert claim.request() == dict(action='submit_anchor', anchorId=row['event_uuid'],
        eventType='REPORT_RELEASED', entityReference=row['entity_reference'],
        contentHash=row['record_hash'], previousHash='', sourceNode='node1')
    assert len(claim.request()) == 7
    assert row['canonical_payload'] not in json.dumps(claim.request())
    for private in ('entity_id', 'created_by_user_id', 'report_id', 'canonical_payload', 'deduplication_key'):
        assert private not in claim.request()
    assert row['record_hash'] not in caplog.text and row['canonical_payload'] not in caplog.text


@pytest.mark.parametrize('status,due,claimed', [
    ('PENDING', True, True), ('PENDING', False, False),
    ('FAILED', True, True), ('FAILED', False, False),
    ('PROCESSING', True, True), ('PROCESSING', False, False),
    ('DEAD', True, False), ('CONFIRMED', True, False),
])
def test_claim_eligibility(factory, status, due, claimed):
    changes = dict(event_status=status, attempt_count=2,
                   next_attempt_at=NOW + timedelta(seconds=-1 if due else 1))
    if status == 'PROCESSING':
        changes.update(processing_started_at=NOW-timedelta(seconds=120), lease_token=str(uuid4()),
                       lease_expires_at=NOW + timedelta(seconds=-1 if due else 1))
    if status == 'CONFIRMED':
        changes.update(fabric_transaction_id=TX, confirmed_at=NOW, fabric_validation_code=0)
    seed(factory, **changes)
    result = worker(factory).claim()
    assert (result is not None) == claimed
    assert state(factory)['attempt_count'] == (3 if claimed else 2)


@pytest.mark.parametrize('field,value', [
    ('record_hash', 'f'*64), ('canonical_payload', '{"patient":"SYNTHETIC_PRIVATE"}'),
    ('entity_reference', str(uuid4())), ('event_uuid', 'SYNTHETIC_PRIVATE'),
    ('event_type', 'SYNTHETIC_PRIVATE'), ('entity_type', 'OTHER'),
    ('occurred_at', NOW-timedelta(days=1)), ('previous_hash', 'd'*64),
])
def test_tampering_dead_without_gateway(factory, field, value, caplog):
    caplog.set_level(logging.INFO)
    seed(factory)
    mutate(factory, **{field: value})
    delivery = worker(factory)
    assert delivery.claim() is None
    row = state(factory)
    assert row['event_status'] == 'DEAD' and row['last_error_code'] == 'OUTBOX_INTEGRITY_FAILURE'
    assert row['attempt_count'] == 0 and not delivery.adapter.calls
    assert 'SYNTHETIC_PRIVATE' not in caplog.text + row['last_error']
    assert row[field] == value


def test_frozen_source_mismatch_dead_even_with_recomputed_hash(factory):
    seed(factory)
    payload = json.loads(state(factory)['canonical_payload'])
    payload['source_node'], payload['source_msp'] = 'node3', 'Org2MSP'
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    mutate(factory, canonical_payload=canonical, record_hash=hashlib.sha256(canonical.encode()).hexdigest())
    assert worker(factory).claim() is None
    assert state(factory)['last_error_code'] == 'OUTBOX_INTEGRITY_FAILURE'


@pytest.mark.parametrize('block', ['42', None])
def test_direct_valid_confirmation_and_transaction_closed(factory, block, caplog):
    caplog.set_level(logging.INFO)
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    delivery.adapter.responses = [False, dict(confirmed=True, validation_code=0,
        transaction_id=TX, block_number=block, anchor=anchor(claim))]
    delivery.adapter.check = lambda: _assert_claim_committed(factory, claim)
    assert delivery.deliver(claim)
    row = state(factory)
    assert row['event_status'] == 'CONFIRMED' and row['fabric_transaction_id'] == TX
    assert row['fabric_validation_code'] == 0 and row['confirmed_at'] == NOW
    assert row['fabric_block_number'] == (42 if block else None)
    assert all(row[key] is None for key in ('lease_token', 'lease_expires_at', 'processing_started_at', 'last_error_code', 'last_error'))
    assert [call[0]['action'] for call in delivery.adapter.calls] == ['anchor_exists', 'submit_anchor']
    assert row['record_hash'] not in caplog.text


def _assert_claim_committed(factory, claim):
    assert state(factory)['lease_token'] == claim.lease_token
    assert factory.kw['bind'].pool.checkedout() == 0


def test_existing_exact_anchor_confirms_original_transaction_without_submit(factory):
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    delivery.adapter.responses = [True, anchor(claim)]
    delivery.deliver(claim)
    assert state(factory)['event_status'] == 'CONFIRMED'
    assert state(factory)['fabric_transaction_id'] == TX
    assert state(factory)['fabric_block_number'] is None
    assert [c[0]['action'] for c in delivery.adapter.calls] == ['anchor_exists', 'read_anchor']


@pytest.mark.parametrize('field,value', [
    ('anchor_id', str(uuid4())), ('content_hash', 'c'*64), ('entity_reference', str(uuid4())),
    ('event_type', 'REPORT_REVOKED'), ('previous_hash', 'd'*64), ('entity_type', 'OTHER'),
    ('source_node', 'node2'), ('source_msp', 'Org2MSP'),
])
def test_existing_semantic_conflict_never_rewritten(factory, field, value):
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    existing = anchor(claim)
    existing[field] = value
    delivery.adapter.responses = [True, existing]
    delivery.deliver(claim)
    assert state(factory)['event_status'] == 'DEAD'
    assert state(factory)['last_error_code'] == 'ANCHOR_CONFLICT'
    assert all(call[0]['action'] != 'submit_anchor' for call in delivery.adapter.calls)


@pytest.mark.parametrize('code', ['COMMIT_TIMEOUT', 'SUBMISSION_FAILED', 'ADAPTER_TIMEOUT',
                                  'ADAPTER_PROCESS_FAILED', 'ANCHOR_CONFLICT', 'INVALID_RESPONSE'])
def test_uncertain_ack_reconciles_matching_state(factory, code):
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    delivery.adapter.responses = [False, DeliveryError(code), anchor(claim)]
    delivery.deliver(claim)
    assert state(factory)['event_status'] == 'CONFIRMED'
    assert state(factory)['fabric_transaction_id'] == TX
    assert [c[0]['action'] for c in delivery.adapter.calls] == ['anchor_exists', 'submit_anchor', 'read_anchor']


def test_crash_before_remote_and_after_commit_recovers(factory):
    seed(factory)
    delivery = worker(factory)
    old = delivery.claim()
    assert delivery.claim() is None
    delivery.now = lambda: NOW + timedelta(seconds=121)
    recovered = delivery.claim()
    assert recovered.attempt == 2 and old.lease_token != recovered.lease_token
    committed = anchor(recovered)
    delivery.now = lambda: NOW + timedelta(seconds=242)
    newest = delivery.claim()
    delivery.adapter.responses = [True, committed]
    delivery.deliver(newest)
    assert state(factory)['event_status'] == 'CONFIRMED'
    before = state(factory)
    assert not delivery.confirm(old, anchor(old))
    assert not delivery.fail(recovered, DeliveryError('GATEWAY_UNAVAILABLE'))
    assert state(factory) == before


@pytest.mark.parametrize('terminal', ['confirm', 'retry', 'dead'])
def test_stale_token_cannot_touch_new_processing_lease(factory, terminal):
    seed(factory)
    delivery = worker(factory)
    old = delivery.claim()
    delivery.now = lambda: NOW + timedelta(seconds=121)
    fresh = delivery.claim()
    before = state(factory)
    if terminal == 'confirm':
        assert not delivery.confirm(old, anchor(old))
    else:
        assert not delivery.fail(old, DeliveryError('GATEWAY_UNAVAILABLE' if terminal == 'retry' else 'CREDENTIAL_INVALID'))
    assert state(factory) == before and before['lease_token'] == fresh.lease_token


@pytest.mark.parametrize('code,status', [
    ('GATEWAY_UNAVAILABLE', 'FAILED'), ('ENDORSEMENT_FAILED', 'FAILED'),
    ('EVALUATION_FAILED', 'FAILED'), ('ADAPTER_TIMEOUT', 'FAILED'),
    ('INVALID_INPUT', 'DEAD'), ('CREDENTIAL_INVALID', 'DEAD'),
    ('CONFIG_INVALID', 'DEAD'), ('COMMIT_INVALID', 'DEAD'), ('TLS_FAILED', 'DEAD'),
])
def test_failure_classification_sanitized_and_lease_cleared(factory, code, status, caplog):
    caplog.set_level(logging.INFO)
    seed(factory)
    error = DeliveryError(code)
    error.args = ('SYNTHETIC_PRIVATE PEM DB_PASSWORD stack trace',)
    delivery = worker(factory, error)
    delivery.deliver(delivery.claim())
    row = state(factory)
    assert row['event_status'] == status and row['last_error_code'] == code
    assert 'SYNTHETIC_PRIVATE' not in row['last_error'] + caplog.text and len(row['last_error']) <= 512
    assert row['lease_token'] is row['lease_expires_at'] is row['processing_started_at'] is None
    assert row['confirmed_at'] is None
    if status == 'FAILED':
        assert row['next_attempt_at'] == NOW + timedelta(seconds=15)


def test_invalid_commit_never_confirmed(factory):
    seed(factory)
    delivery = worker(factory, False, DeliveryError('COMMIT_INVALID'))
    delivery.deliver(delivery.claim())
    assert state(factory)['event_status'] == 'DEAD'
    assert state(factory)['confirmed_at'] is None


def test_retry_exhaustion_and_final_lost_ack_recovery(factory):
    seed(factory, attempt_count=7)
    delivery = worker(factory, DeliveryError('GATEWAY_UNAVAILABLE'))
    delivery.deliver(delivery.claim())
    assert state(factory)['event_status'] == 'DEAD' and state(factory)['attempt_count'] == 8
    assert delivery.claim() is None
    seed(factory, 2, attempt_count=7)
    last = delivery.claim()
    delivery.now = lambda: NOW + timedelta(seconds=121)
    recovery = delivery.claim()
    assert recovery.attempt == 9  # recovery claim only; no ninth write allowed
    delivery.adapter.responses = [True, anchor(last)]
    delivery.deliver(recovery)
    assert state(factory, 2)['event_status'] == 'CONFIRMED'
    seed(factory, 3, attempt_count=7)
    delivery.claim()
    delivery.now = lambda: NOW + timedelta(seconds=242)
    recovery = delivery.claim()
    delivery.adapter.responses = [False]
    delivery.deliver(recovery)
    assert state(factory, 3)['last_error_code'] == 'MAX_ATTEMPTS'
    assert delivery.adapter.responses == []


def test_backoff_caps_exponent_and_jitter():
    options = WorkerOptions()
    assert [backoff(n, options, lambda: 0) for n in range(1, 9)] == [15, 30, 60, 120, 240, 480, 900, 900]
    assert backoff(1, options, lambda: 1) == 16.5
    assert backoff(1000000000, options, lambda: 1) == 900
    assert backoff(0, options, lambda: 0) == 15


@pytest.mark.parametrize('lifecycle', ['REPORT_REVOKED', 'REPORT_SUPERSEDED'])
@pytest.mark.parametrize('predecessor_status', ['PENDING', 'FAILED', 'PROCESSING', 'CONFIRMED', 'DEAD'])
def test_predecessor_ordering_without_wasted_attempts(factory, lifecycle, predecessor_status):
    changes = dict(event_status=predecessor_status, next_attempt_at=NOW+timedelta(hours=1))
    if predecessor_status == 'PROCESSING':
        changes.update(lease_token=str(uuid4()), processing_started_at=NOW, lease_expires_at=NOW+timedelta(seconds=120))
    if predecessor_status == 'CONFIRMED':
        changes.update(fabric_transaction_id=TX, fabric_validation_code=0, confirmed_at=NOW)
    seed(factory, **changes)
    seed(factory, 2, predecessor=1, event_type=lifecycle)
    delivery = worker(factory)
    claim = delivery.claim()
    row = state(factory, 2)
    if predecessor_status == 'CONFIRMED':
        assert claim.event_id == 2 and row['attempt_count'] == 1
        assert claim.request()['previousHash'] == state(factory)['record_hash']
    else:
        assert claim is None and row['attempt_count'] == 0
        if predecessor_status == 'DEAD':
            assert row['event_status'] == 'DEAD' and row['last_error_code'] == 'PREDECESSOR_DEAD'
        else:
            assert row['event_status'] == 'PENDING' and row['next_attempt_at'] == NOW+timedelta(seconds=2)
            assert delivery.claim() is None
    assert not delivery.adapter.calls


def test_blocked_predecessor_does_not_starve_independent_event(factory):
    seed(factory, next_attempt_at=NOW+timedelta(hours=1))
    seed(factory, 2, predecessor=1, event_type='REPORT_REVOKED')
    seed(factory, 3)
    assert worker(factory).claim().event_id == 3
    assert state(factory, 2)['attempt_count'] == 0


def test_wrong_predecessor_link_is_integrity_failure(factory):
    seed(factory, next_attempt_at=NOW+timedelta(hours=1))
    seed(factory, 2, predecessor=1, event_type='REPORT_REVOKED')
    mutate(factory, 2, entity_id=999)
    assert worker(factory).claim() is None
    assert state(factory, 2)['last_error_code'] == 'OUTBOX_INTEGRITY_FAILURE'


def test_delivery_update_allowlist(factory):
    with factory.begin() as db, pytest.raises(ValueError):
        _delivery_update(db, TABLE.c.event_id == 1, {'record_hash': 'f'*64})


def test_single_budget_for_all_calls_and_expired_local_claim(factory):
    seed(factory)
    ticks = iter([0, 5, 20, 40])
    delivery = worker(factory, False, DeliveryError('COMMIT_TIMEOUT'), DeliveryError('ANCHOR_NOT_FOUND'),
                      monotonic=lambda: next(ticks))
    claim = delivery.claim()
    delivery.deliver(claim)
    assert [timeout for _, timeout in delivery.adapter.calls] == [85, 55, 50]
    assert state(factory)['event_status'] == 'FAILED'
    mutate(factory, event_status='PENDING', next_attempt_at=NOW)
    delivery = worker(factory)
    claim = delivery.claim()
    delivery.now = lambda: NOW+timedelta(seconds=121)
    delivery.deliver(claim)
    assert not delivery.adapter.calls


def test_cycle_stops_new_claims_and_claims_batches_sequentially(factory):
    seed(factory)
    seed(factory, 2)
    stopping = threading.Event()
    delivery = worker(factory, DeliveryError('GATEWAY_UNAVAILABLE'), options=WorkerOptions(batch=2))
    def stop_after_first_call():
        assert state(factory, 2)['event_status'] == 'PENDING'
        stopping.set()
    delivery.adapter.check = stop_after_first_call
    assert delivery.cycle(stopping) == 1
    assert state(factory, 2)['event_status'] == 'PENDING'
    assert delivery.cycle(stopping) == 0


def test_direct_semantic_conflict_is_dead_without_second_read(factory):
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    result = anchor(claim)
    result['content_hash'] = 'c'*64
    delivery.adapter.responses = [False, dict(confirmed=True, validation_code=0,
        transaction_id=TX, block_number='42', anchor=result)]
    delivery.deliver(claim)
    assert state(factory)['last_error_code'] == 'ANCHOR_CONFLICT'
    assert state(factory)['event_status'] == 'DEAD'
    assert len(delivery.adapter.calls) == 2


@pytest.mark.parametrize('recovery', ['ANCHOR_NOT_FOUND', 'GATEWAY_UNAVAILABLE'])
def test_duplicate_submit_with_unavailable_read_retries_without_overwrite(factory, recovery):
    seed(factory)
    delivery = worker(factory, False, DeliveryError('ANCHOR_CONFLICT'), DeliveryError(recovery))
    delivery.deliver(delivery.claim())
    assert state(factory)['event_status'] == 'FAILED'
    assert state(factory)['last_error_code'] == 'COMMIT_TIMEOUT'
    assert len(delivery.adapter.calls) == 3


def test_lost_ack_then_conflicting_ledger_state_is_permanent(factory):
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    existing = anchor(claim)
    existing['entity_reference'] = str(uuid4())
    delivery.adapter.responses = [False, DeliveryError('COMMIT_TIMEOUT'), existing]
    delivery.deliver(claim)
    assert state(factory)['last_error_code'] == 'ANCHOR_CONFLICT'
    assert state(factory)['event_status'] == 'DEAD'


def test_ack_database_failure_leaves_lease_for_reconciliation(factory, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    seed(factory)
    delivery = worker(factory)
    claim = delivery.claim()
    delivery.adapter.responses = [False, dict(confirmed=True, validation_code=0,
        transaction_id=TX, block_number='1', anchor=anchor(claim))]
    original = delivery._finish
    def unavailable(*args):
        raise SQLAlchemyError('SYNTHETIC_PRIVATE database detail')
    monkeypatch.setattr(delivery, '_finish', unavailable)
    with pytest.raises(SQLAlchemyError):
        delivery.deliver(claim)
    assert state(factory)['event_status'] == 'PROCESSING'
    monkeypatch.setattr(delivery, '_finish', original)
    delivery.now = lambda: NOW+timedelta(seconds=121)
    recovered = delivery.claim()
    delivery.adapter.responses = [True, anchor(claim)]
    delivery.deliver(recovered)
    assert state(factory)['event_status'] == 'CONFIRMED'


def test_failed_retry_becomes_eligible_at_scheduled_time(factory):
    seed(factory)
    delivery = worker(factory, DeliveryError('GATEWAY_UNAVAILABLE'))
    delivery.deliver(delivery.claim())
    assert delivery.claim() is None
    delivery.now = lambda: NOW+timedelta(seconds=15)
    second = delivery.claim()
    assert second.attempt == 2
    assert state(factory)['event_status'] == 'PROCESSING'
