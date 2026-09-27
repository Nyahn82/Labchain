"""Synthetic Phase 8B-1 capture, privacy, integrity and transaction regression."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import subprocess
from uuid import UUID

import pytest
from sqlalchemy import delete, event, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.cli import bootstrap_blockchain_nodes as bootstrap
from app.config import settings, Settings
from app.models import AuditLog, BlockchainEvent, BlockchainNode, LabReport, ReportVerification
from app.models.blockchain import OutboxIntegrityError
from app.services import blockchain_outbox_service as outbox
from test_phase_5b_release import (env, password_hash, lab_api, workflow_api, results_api,
    reports_api, admin, api, ready, release, call, create, sign, count)

NOW = datetime(2026, 9, 24, 12, 34, 56, 123456)
ENTITY = '11111111-1111-4111-8111-111111111111'
GOLDEN = '{"artifact_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","entity_reference":"11111111-1111-4111-8111-111111111111","entity_type":"REPORT","event_type":"REPORT_RELEASED","occurred_at":"2026-09-24T12:34:56.123456Z","previous_hash":null,"report_version":1,"schema_version":1,"source_msp":"Org1MSP","source_node":"node1","superseding_entity_reference":null}'
GOLDEN_HASH = 'dd11ba543b5ee8e8ae64f598bc8feda22df2b70fc2ad794d08d5c0c0011aacef'


def values(**changes):
    return dict(dict(event_type='REPORT_RELEASED', entity_reference=ENTITY, report_version=1,
        artifact_sha256='a'*64, occurred_at=NOW, source_node='node1', source_msp='Org1MSP'), **changes)


def events(db):
    return list(db.scalars(select(BlockchainEvent).order_by(BlockchainEvent.event_id)))


def test_canonical_golden_order_utc_nulls():
    result = outbox.canonicalize(**values())
    assert result == GOLDEN
    assert hashlib.sha256(result.encode('utf-8')).hexdigest() == GOLDEN_HASH
    assert outbox.canonicalize(**dict(reversed(list(values().items())))) == result
    assert outbox.canonicalize(**values(occurred_at=NOW.replace(tzinfo=timezone.utc))) == result
    assert outbox.canonicalize(**values(occurred_at=(NOW + timedelta(hours=8)).replace(tzinfo=timezone(timedelta(hours=8))))) == result
    data = json.loads(result)
    assert set(data) == outbox.PAYLOAD_KEYS
    assert data['previous_hash'] is data['superseding_entity_reference'] is None


@pytest.mark.parametrize('change', [
    {'entity_reference': 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'},
    {'entity_reference': 'aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa'},
    {'artifact_sha256': 'A'*64}, {'artifact_sha256': 'a'*63},
    {'report_version': True}, {'report_version': '1'}, {'report_version': 0},
    {'source_node': 'node-1'}, {'source_msp': 'Org2MSP'},
    {'event_type': 'REPORT_REVOKED'}, {'previous_hash': 'b'*64},
    {'superseding_entity_reference': ENTITY},
])
def test_strict_canonical_validation(change):
    with pytest.raises(OutboxIntegrityError): outbox.canonicalize(**values(**change))


@pytest.mark.parametrize('field', ['patient_id', 'patient_name', 'birth_date', 'sex', 'address',
    'email', 'phone', 'medical_record_number', 'order_id', 'report_code', 'verification_token',
    'verification_url', 'pdf_path', 'physician_name', 'staff_id', 'result_value', 'test_name',
    'diagnosis', 'clinical_interpretation', 'revocation_reason', 'notes', 'report_id', 'username', 'ip_address'])
def test_private_fields_cannot_enter_serializer(field):
    with pytest.raises(TypeError): outbox.canonicalize(**values(), **{field: 'SYNTHETIC_PRIVATE'})


def test_release_atomic_capture_offline_and_uuid(api, monkeypatch):
    ready(api)
    def forbidden(*args, **kwargs):
        pytest.fail('Report release attempted subprocess execution')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    # conftest also blocks every socket connection. No running Fabric is needed.
    release(api)
    with api.factory() as db:
        report = db.get(LabReport, 1)
        verification = db.scalar(select(ReportVerification))
        row, = events(db)
        payload = json.loads(row.canonical_payload)
        assert UUID(row.event_uuid).version == UUID(report.blockchain_entity_uuid).version == 4
        assert str(UUID(row.event_uuid)) == row.event_uuid
        assert row.entity_reference == report.blockchain_entity_uuid == payload['entity_reference']
        assert payload['artifact_sha256'] == verification.report_hash
        assert set(payload) == outbox.PAYLOAD_KEYS
        assert row.record_hash == hashlib.sha256(row.canonical_payload.encode()).hexdigest()
        assert row.event_status == 'PENDING' and row.attempt_count == 0
        assert row.next_attempt_at == row.occurred_at
        assert row.previous_hash is row.predecessor_event_id is row.fabric_transaction_id is None
        assert payload['source_node'] == 'node1' and payload['source_msp'] == 'Org1MSP'
        assert row.deduplication_key == 'REPORT_RELEASED:1'
        assert verification.verification_token not in row.canonical_payload
        assert report.report_code not in row.canonical_payload
        old_uuid = report.blockchain_entity_uuid
    assert call(api, 'POST', '/reports/1/release').status_code == 409
    with api.factory() as db:
        assert db.get(LabReport, 1).blockchain_entity_uuid == old_uuid
        assert len(events(db)) == 1


def fail_outbox(api):
    def fail(conn, cursor, statement, *args):
        if statement.startswith('INSERT INTO blockchain_event '):
            raise SQLAlchemyError('Synthetic outbox failure')
    event.listen(api.engine, 'before_cursor_execute', fail)
    return fail


def test_release_outbox_failure_rolls_back_everything(api):
    ready(api)
    with api.factory() as db: before_audits = count(db, AuditLog)
    fail = fail_outbox(api)
    try:
        assert call(api, 'POST', '/reports/1/release').status_code == 503
    finally:
        event.remove(api.engine, 'before_cursor_execute', fail)
    with api.factory() as db:
        report = db.get(LabReport, 1)
        assert report.report_status == 'APPROVED'
        assert report.blockchain_entity_uuid is report.pdf_path is report.released_at is None
        assert count(db, ReportVerification) == count(db, BlockchainEvent) == 0
        assert count(db, AuditLog) == before_audits
    assert not list(settings.report_storage_dir.rglob('*.pdf'))
    assert not list(settings.report_storage_dir.rglob('*.tmp'))


def test_missing_node_registry_fails_release_atomically(api):
    ready(api)
    with api.factory.begin() as db: db.execute(delete(BlockchainNode))
    assert call(api, 'POST', '/reports/1/release').status_code == 503
    with api.factory() as db:
        assert db.get(LabReport, 1).report_status == 'APPROVED'
        assert not events(db) and count(db, ReportVerification) == 0


def test_dedup_exact_reuse_and_conflict(api):
    ready(api); release(api)
    with api.factory.begin() as db:
        row, = events(db)
        original_uuid = row.event_uuid
        args = dict(report=db.get(LabReport, 1), event_type='REPORT_RELEASED',
            artifact_sha256=json.loads(row.canonical_payload)['artifact_sha256'], occurred_at=row.occurred_at, actor_id=1)
        assert outbox.capture(db, **args) is row
        assert row.event_uuid == original_uuid
        with pytest.raises(OutboxIntegrityError, match='deduplication conflict'):
            outbox.capture(db, **{**args, 'artifact_sha256': '0'*64})
    with api.factory.begin() as db:
        row, = events(db)
        clone = {col.name: getattr(row, col.name) for col in BlockchainEvent.__table__.columns if col.name != 'event_id'}
        clone['event_uuid'] = '22222222-2222-4222-8222-222222222222'
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(BlockchainEvent.__table__.insert().values(**clone))


@pytest.mark.parametrize('field,value', [
    ('event_uuid', '22222222-2222-4222-8222-222222222222'), ('deduplication_key', 'changed'),
    ('origin_node_id', 2), ('entity_type', 'OTHER'), ('entity_id', 2),
    ('entity_reference', '22222222-2222-4222-8222-222222222222'),
    ('event_type', 'REPORT_REVOKED'), ('canonical_payload', '{}'), ('record_hash', 'b'*64),
    ('previous_hash', 'b'*64), ('predecessor_event_id', 1), ('occurred_at', NOW),
    ('created_by_user_id', None),
])
def test_event_immutable_fields(api, field, value):
    ready(api); release(api)
    with pytest.raises(OutboxIntegrityError), api.factory.begin() as db:
        row, = events(db)
        setattr(row, field, value)


def test_report_uuid_immutable_even_after_expiration(api):
    ready(api); release(api)
    with api.factory() as db:
        report = db.get(LabReport, 1)
        db.expire(report, ['blockchain_entity_uuid'])
        with pytest.raises(OutboxIntegrityError): report.blockchain_entity_uuid = None
        with pytest.raises(OutboxIntegrityError): report.blockchain_entity_uuid = '22222222-2222-4222-8222-222222222222'


def test_delivery_validation_and_mutability(api):
    ready(api); release(api)
    for change in ({'event_status': 'PROCESSING'}, {'event_status': 'CONFIRMED'},
                   {'event_status': 'CONFIRMED', 'fabric_transaction_id': 'a'*64, 'confirmed_at': NOW, 'fabric_validation_code': None}):
        with pytest.raises(OutboxIntegrityError), api.factory.begin() as db:
            row, = events(db)
            for key, value in change.items(): setattr(row, key, value)
    with api.factory.begin() as db:
        row, = events(db)
        row.event_status = 'FAILED'
        row.attempt_count = 1
        row.next_attempt_at = NOW
        row.last_error_code = 'SYNTHETIC_UNAVAILABLE'
        row.updated_at = NOW
    with api.factory() as db: assert events(db)[0].event_status == 'FAILED'


def make_legacy(api):
    # Explicit synthetic fixture conversion, never an application/backfill path.
    with api.factory.begin() as db:
        db.execute(delete(BlockchainEvent))
        db.execute(update(LabReport).values(blockchain_entity_uuid=None))


def assert_legacy_skip(db, event_type):
    skipped = list(db.scalars(select(AuditLog).where(AuditLog.action == 'BLOCKCHAIN_CAPTURE_SKIPPED')))
    assert skipped[-1].new_value == {'reason_code': 'LEGACY_REPORT_NOT_ANCHORED', 'event_type': event_type}
    assert skipped[-1].ip_address is None


@pytest.mark.parametrize('legacy', [False, True])
def test_revoke_capture_and_legacy(api, legacy):
    ready(api); release(api)
    if legacy: make_legacy(api)
    assert call(api, 'POST', '/reports/1/revoke', {'reason': 'SYNTHETIC_PRIVATE_REASON'}).status_code == 200
    with api.factory() as db:
        assert db.get(LabReport, 1).report_status == 'REVOKED'
        assert db.scalar(select(ReportVerification)).verification_status == 'REVOKED'
        if legacy:
            assert not events(db) and db.get(LabReport, 1).blockchain_entity_uuid is None
            assert_legacy_skip(db, 'REPORT_REVOKED')
        else:
            first, revoked = events(db)
            assert revoked.event_type == 'REPORT_REVOKED'
            assert revoked.previous_hash == first.record_hash and revoked.predecessor_event_id == first.event_id
            assert revoked.entity_reference == first.entity_reference
            assert json.loads(revoked.canonical_payload)['artifact_sha256'] == json.loads(first.canonical_payload)['artifact_sha256']
            assert 'SYNTHETIC_PRIVATE_REASON' not in revoked.canonical_payload
            assert first.event_status == revoked.event_status == 'PENDING'


def prepare_replacement(api):
    assert call(api, 'POST', '/reports/1/revise', {}).status_code == 201
    link = create(api, '/reports/2/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'})
    assert sign(api, link['report_signatory_id'], 2).status_code == 200
    assert call(api, 'POST', '/reports/2/approve').status_code == 200


@pytest.mark.parametrize('legacy,revoked', [(False, False), (True, False), (False, True), (True, True)])
def test_supersession_at_release_only(api, legacy, revoked):
    ready(api); release(api)
    if legacy: make_legacy(api)
    if revoked: assert call(api, 'POST', '/reports/1/revoke', {'reason': 'Synthetic'}).status_code == 200
    with api.factory() as db: before = len(events(db))
    prepare_replacement(api)
    with api.factory() as db: assert len(events(db)) == before
    release(api, 2)
    with api.factory() as db:
        rows = events(db)
        replacement = next(row for row in rows if row.entity_id == 2)
        assert replacement.event_type == 'REPORT_RELEASED'
        assert replacement.previous_hash is replacement.predecessor_event_id is None
        if legacy:
            assert len(rows) == 1 and db.get(LabReport, 1).blockchain_entity_uuid is None
            assert_legacy_skip(db, 'REPORT_SUPERSEDED')
        else:
            superseded = next(row for row in rows if row.event_type == 'REPORT_SUPERSEDED')
            original = next(row for row in rows if row.event_type == 'REPORT_RELEASED' and row.entity_id == 1)
            assert superseded.previous_hash == original.record_hash
            assert superseded.predecessor_event_id == original.event_id
            assert json.loads(superseded.canonical_payload)['superseding_entity_reference'] == replacement.entity_reference
            assert superseded.entity_reference == original.entity_reference


@pytest.mark.parametrize('operation', ['revoke', 'supersede'])
def test_lifecycle_outbox_failure_is_atomic(api, operation):
    ready(api); release(api)
    if operation == 'supersede': prepare_replacement(api)
    fail = fail_outbox(api)
    try:
        response = call(api, 'POST', '/reports/1/revoke', {'reason': 'Synthetic'}) if operation == 'revoke' else call(api, 'POST', '/reports/2/release')
        assert response.status_code == 503
    finally: event.remove(api.engine, 'before_cursor_execute', fail)
    with api.factory() as db:
        assert db.get(LabReport, 1).report_status == 'RELEASED'
        assert db.scalar(select(ReportVerification)).verification_status == 'AUTHENTIC'
        assert len(events(db)) == count(db, ReportVerification) == 1
        if operation == 'supersede':
            assert db.get(LabReport, 2).report_status == 'APPROVED'
            assert db.get(LabReport, 2).blockchain_entity_uuid is None
    assert len(list(settings.report_storage_dir.rglob('*.pdf'))) == 1


def test_missing_captured_release_is_integrity_failure_not_legacy(api):
    ready(api); release(api)
    with api.factory.begin() as db: db.execute(delete(BlockchainEvent))
    assert call(api, 'POST', '/reports/1/revoke', {'reason': 'Synthetic'}).status_code == 503
    with api.factory() as db: assert db.get(LabReport, 1).report_status == 'RELEASED'


def test_node_bootstrap_idempotent_cli(env, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, 'SessionLocal', env.factory)
    bootstrap.main(); bootstrap.main()
    assert capsys.readouterr().out.splitlines() == ['Blockchain nodes ready; created 4 node(s).', 'Blockchain nodes ready; created 0 node(s).']
    with env.factory() as db:
        assert [(x.node_code, x.port, x.node_role) for x in db.scalars(select(BlockchainNode).order_by(BlockchainNode.node_code))] == list(bootstrap.NODES)


@pytest.mark.parametrize('change', [{'port': 9999}, {'node_role': 'Conflicting'}, {'is_active': False}, {'node_code': 'unexpected'}])
def test_node_bootstrap_conflicts_do_not_rewrite(env, change):
    with env.factory.begin() as db:
        bootstrap.ensure_blockchain_nodes(db)
        row = db.scalar(select(BlockchainNode).where(BlockchainNode.node_code == 'node1'))
        for key, value in change.items(): setattr(row, key, value)
    with pytest.raises(OutboxIntegrityError), env.factory.begin() as db: bootstrap.ensure_blockchain_nodes(db)
    with env.factory() as db: assert count(db, BlockchainNode) == 4


def test_source_config_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError): Settings(blockchain_source_node='node-1')
    with pytest.raises(ValidationError): Settings(blockchain_source_node='node1', blockchain_source_msp='Org2MSP')


def test_pending_session_dedup_preserves_anchor_uuid(api):
    ready(api)
    with api.factory.begin() as db:
        report = db.get(LabReport, 1)
        first = outbox.capture_release(db, report, 'a'*64, NOW, 1)
        second = outbox.capture_release(db, report, 'a'*64, NOW, 1)
        assert first is second and first in db.new
        anchor = first.event_uuid
        db.flush()
        assert outbox.capture_release(db, report, 'a'*64, NOW, 1).event_uuid == anchor
    with api.factory() as db: assert len(events(db)) == 1


def test_failure_after_all_supersession_rows_flushed_rolls_back(api, monkeypatch):
    ready(api); release(api); prepare_replacement(api)
    original = outbox.capture_lifecycle
    def fail_after_flush(*args, **kwargs):
        result = original(*args, **kwargs)
        args[0].flush()
        assert result.event_id is not None
        assert len(events(args[0])) == 3
        raise SQLAlchemyError('Synthetic failure after all outbox writes')
    monkeypatch.setattr(outbox, 'capture_lifecycle', fail_after_flush)
    assert call(api, 'POST', '/reports/2/release').status_code == 503
    with api.factory() as db:
        assert db.get(LabReport, 1).report_status == 'RELEASED'
        assert db.get(LabReport, 2).report_status == 'APPROVED'
        assert db.get(LabReport, 2).blockchain_entity_uuid is None
        assert len(events(db)) == count(db, ReportVerification) == 1
    assert len(list(settings.report_storage_dir.rglob('*.pdf'))) == 1


def test_event_delete_and_canonical_tampering_rejected(api):
    ready(api); release(api)
    with pytest.raises(OutboxIntegrityError), api.factory.begin() as db:
        db.delete(events(db)[0])
    with api.factory() as db:
        row = events(db)[0]
        payload = json.loads(row.canonical_payload)
        payload['patient_name'] = 'SYNTHETIC_PRIVATE'
        row.canonical_payload = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        row.record_hash = hashlib.sha256(row.canonical_payload.encode()).hexdigest()
        with pytest.raises(OutboxIntegrityError, match='Invalid canonical'):
            outbox.validate_event(row)
