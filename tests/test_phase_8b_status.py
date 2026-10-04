"""Synthetic database/API tests; no live Fabric, worker, systemd or production DB."""
from datetime import datetime, timedelta
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select, update

from app.api import blockchain, health
from app.config import settings
from app.models import BlockchainEvent, LabReport, Permission, Role, RolePermission, UserRole
from app.services import blockchain_status_service as status_service
from app.services.permission_catalog import ensure_permissions
from app.services.rbac_service import ensure_core_roles, user_has_permission
from phase8b_delivery_support import seed, state
from test_phase_6a_patient_portal import (
    env, password_hash, lab_api, workflow_api, results_api, reports_api, admin, api,
    portal, two_reports, patient_login, provision,
)
from test_phase_5b_release import ready, release, call, login, verify, metadata
from test_phase_8b_outbox import make_legacy, prepare_replacement

NOW = datetime(2030, 1, 1, 12)
PRIVATE = 'PRIVATE_WORKER_ERROR grpc /private/credentials'


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(status_service, 'utc_now', lambda: NOW)
    def forbidden(*args, **kwargs):
        pytest.fail('Status/report APIs must not execute subprocesses')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def change_status(factory, status, event_id=1, **overrides):
    with factory.begin() as db:
        row = db.get(BlockchainEvent, event_id)
        row.event_status = status
        row.next_attempt_at = NOW - timedelta(seconds=1)
        if status == 'PROCESSING':
            row.processing_started_at = NOW
            row.lease_token = str(uuid4())
            row.lease_expires_at = NOW + timedelta(seconds=120)
        if status == 'CONFIRMED':
            row.fabric_transaction_id = f'{event_id:064x}'
            row.fabric_validation_code = 0
            row.fabric_block_number = event_id + 4
            row.confirmed_at = NOW + timedelta(seconds=event_id)
        if status in {'FAILED', 'DEAD'}:
            row.last_error_code = 'INTERNAL_PRIVATE_CODE'
            row.last_error = PRIVATE
        for key, value in overrides.items():
            setattr(row, key, value)


@pytest.fixture
def global_api(env):
    env.app.include_router(blockchain.router, prefix='/api/v1')
    with env.factory.begin() as db:
        ensure_permissions(db)
        ensure_core_roles(db)
    return env


def grant_status(api):
    with api.factory.begin() as db:
        permission = db.scalar(select(Permission).where(Permission.permission_code == 'BLOCKCHAIN_STATUS_VIEW'))
        db.add(RolePermission(role_id=1, permission_id=permission.permission_id))
    assert login(api).status_code == 200


def get_status(api):
    response = api.client.get('/api/v1/blockchain/status')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


def test_global_requires_staff_permission_and_admin_bypass(global_api):
    api = global_api
    assert api.client.get('/api/v1/blockchain/status').status_code == 401
    assert login(api).status_code == 200
    assert api.client.get('/api/v1/blockchain/status').status_code == 403
    with api.factory.begin() as db:
        assert ensure_permissions(db) == []
        assert not user_has_permission(db, 1, 'BLOCKCHAIN_STATUS_VIEW')
        admin_role = db.scalar(select(Role).where(Role.role_code == 'SYSTEM_ADMIN'))
        admin_role_id = admin_role.role_id
        db.add(UserRole(user_id=1, role_id=admin_role_id, assigned_at=NOW))
    assert get_status(api)['worker_health'] == 'IDLE'
    with api.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.role_id == admin_role_id))
    assert api.client.get('/api/v1/blockchain/status').status_code == 403
    grant_status(api)
    assert get_status(api)['counts'] == dict(pending=0, processing=0, confirmed=0, failed=0, dead=0)
    with api.factory.begin() as db:
        db.get(Role, 1).is_active = False
    assert api.client.get('/api/v1/blockchain/status').status_code == 403


def test_patient_role_cannot_gain_global_access_from_permission_alone(global_api, monkeypatch):
    api = global_api
    grant_status(api)
    monkeypatch.setattr(settings, 'patient_mfa_required', False)
    with api.factory.begin() as db:
        patient_role = db.scalar(select(Role).where(Role.role_code == 'PATIENT'))
        permission_id = db.scalar(select(Permission.permission_id).where(Permission.permission_code == 'BLOCKCHAIN_STATUS_VIEW'))
        db.execute(delete(UserRole).where(UserRole.user_id == 1))
        db.add(UserRole(user_id=1, role_id=patient_role.role_id, assigned_at=NOW))
        db.add(RolePermission(role_id=patient_role.role_id, permission_id=permission_id))
    assert api.client.get('/api/v1/blockchain/status').status_code == 403


def test_global_counts_last_confirmation_and_redaction(global_api, monkeypatch):
    api = global_api
    grant_status(api)
    for number, status in enumerate(('PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD', 'CONFIRMED'), 1):
        seed(api.factory, number)
        change_status(api.factory, status, number)
    def forbidden(*args, **kwargs):
        pytest.fail('Status API must not run a subprocess')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    result = get_status(api)
    assert result['counts'] == dict(pending=1, processing=1, confirmed=2, failed=1, dead=1)
    assert result['last_confirmed_transaction_id'] == f'{6:064x}'
    assert result['last_confirmed_at'] == (NOW + timedelta(seconds=6)).isoformat()
    assert result['oldest_pending_at'] is not None
    assert result['worker_health'] == 'ERROR'
    assert result['delivery_enabled'] is None
    assert set(result) == {'delivery_enabled', 'counts', 'worker_health', 'last_confirmed_at',
                           'last_confirmed_transaction_id', 'oldest_pending_at'}
    assert PRIVATE not in json.dumps(result) and 'INTERNAL_PRIVATE_CODE' not in json.dumps(result)


@pytest.mark.parametrize('states,expected', [
    ([], 'IDLE'), (['CONFIRMED'], 'IDLE'), (['PENDING'], 'ACTIVE'),
    (['FUTURE_PENDING'], 'IDLE'), (['PROCESSING'], 'ACTIVE'),
    (['EXPIRED'], 'DEGRADED'), (['FAILED'], 'DEGRADED'),
    (['FAILED', 'PROCESSING'], 'DEGRADED'), (['DEAD'], 'ERROR'),
    (['DEAD', 'FAILED', 'PROCESSING', 'PENDING'], 'ERROR'),
])
def test_global_health_precedence(global_api, states, expected):
    grant_status(global_api)
    for number, value in enumerate(states, 1):
        seed(global_api.factory, number)
        changes = {}
        if value == 'FUTURE_PENDING':
            value, changes = 'PENDING', {'next_attempt_at': NOW + timedelta(days=1)}
        if value == 'EXPIRED':
            value, changes = 'PROCESSING', {'lease_expires_at': NOW}
        change_status(global_api.factory, value, number, **changes)
    assert get_status(global_api)['worker_health'] == expected


@pytest.mark.parametrize('status,expected', [
    ('PENDING', 'PENDING'), ('PROCESSING', 'PROCESSING'), ('FAILED', 'RETRYING'),
    ('DEAD', 'FAILED'), ('CONFIRMED', 'CONFIRMED'), ('LEGACY', 'NOT_ANCHORED'),
])
def test_staff_detail_and_public_release_status(api, status, expected):
    ready(api)
    assert release(api)['anchoring']['status'] == 'PENDING'
    if status == 'LEGACY':
        make_legacy(api)
    else:
        change_status(api.factory, status)
    response = call(api, 'GET', '/reports/1')
    assert response.status_code == 200
    body = response.json()
    assert body['report_status'] == 'RELEASED' and body['verification_status'] == 'AUTHENTIC'
    anchor = body['anchoring']
    assert set(anchor) == {'status', 'release', 'revocation', 'supersession'}
    assert anchor['status'] == anchor['release']['status'] == expected
    assert anchor['revocation'] is anchor['supersession'] is None
    assert set(anchor['release']) == {'status', 'confirmed_at', 'transaction_id', 'block_number'}
    if status == 'CONFIRMED':
        assert anchor['release']['transaction_id'] == f'{1:064x}'
        assert anchor['release']['block_number'] == 5
    else:
        assert anchor['release']['transaction_id'] is anchor['release']['confirmed_at'] is None
    for forbidden in ('canonical_payload', 'lease_token', 'lease_expires_at', 'last_error',
                      'entity_id', 'created_by_user_id', 'origin_node_id', 'event_uuid', PRIVATE):
        assert forbidden not in json.dumps(anchor)
    public = verify(api).json()
    assert public['status'] == 'VERIFIED'
    assert public['blockchain_status'] == ('PENDING' if expected == 'PROCESSING' else expected)
    assert set(public) <= {'status', 'message', 'issuing_facility', 'report_date', 'version',
                           'blockchain_status', 'blockchain_confirmed_at'}
    assert ('blockchain_confirmed_at' in public) == (status == 'CONFIRMED')


@pytest.mark.parametrize('transition', ['revoke', 'supersede'])
@pytest.mark.parametrize('status,expected', [('PENDING', 'PENDING'), ('CONFIRMED', 'CONFIRMED'), ('FAILED', 'RETRYING'), ('DEAD', 'FAILED')])
def test_later_lifecycle_never_hidden_by_confirmed_release(api, transition, status, expected):
    ready(api); release(api)
    change_status(api.factory, 'CONFIRMED')
    name = 'revocation' if transition == 'revoke' else 'supersession'
    if transition == 'revoke':
        assert call(api, 'POST', '/reports/1/revoke', {'reason': 'Synthetic correction'}).status_code == 200
    else:
        prepare_replacement(api)
        release(api, 2)
    with api.factory() as db:
        event_id = db.scalar(select(BlockchainEvent.event_id).where(
            BlockchainEvent.entity_id == 1, BlockchainEvent.event_type != 'REPORT_RELEASED'))
    change_status(api.factory, status, event_id)
    body = call(api, 'GET', '/reports/1').json()
    assert body['report_status'] == 'REVOKED' and body['verification_status'] == 'REVOKED'
    assert body['anchoring']['release']['status'] == 'CONFIRMED'
    assert body['anchoring'][name]['status'] == body['anchoring']['status'] == expected
    public = verify(api).json()
    assert public['status'] == 'REVOKED' and public['blockchain_status'] == expected
    assert ('blockchain_confirmed_at' in public) == (status == 'CONFIRMED')


@pytest.mark.parametrize('status,expected', [('PENDING', 'PENDING'), ('PROCESSING', 'PENDING'),
    ('CONFIRMED', 'CONFIRMED'), ('FAILED', 'RETRYING'), ('DEAD', 'FAILED'), ('LEGACY', 'NOT_ANCHORED')])
def test_patient_status_allowlist_ownership_and_staff_endpoint_denied(two_reports, status, expected):
    api = two_reports
    api.app.include_router(blockchain.router, prefix='/api/v1')
    if status == 'LEGACY':
        make_legacy(api)
    else:
        change_status(api.factory, status)
    patient_login(api)
    response = api.client.get('/api/v1/patient/reports/1')
    assert response.status_code == 200
    result = response.json()['blockchain_verification']
    assert set(result) == {'status', 'confirmed_at'}
    assert result['status'] == expected
    assert (result['confirmed_at'] is not None) == (expected == 'CONFIRMED')
    for forbidden in ('transaction_id', 'event_uuid', 'block_number', 'source_node', 'source_msp',
                      'attempt_count', 'last_error', 'lease_', 'INTERNAL_PRIVATE_CODE', PRIVATE):
        assert forbidden not in response.text
    assert api.client.get('/api/v1/patient/reports/2').status_code == 404
    assert api.client.get('/api/v1/blockchain/status').status_code == 403


def test_unknown_public_token_remains_neutral(api):
    for token in ('invalid', 'x' * 43):
        result = api.client.get('/api/v1/verify/' + token)
        assert result.status_code == 200
        assert result.json() == {'status': 'NOT_FOUND', 'message': 'Verification record not found.'}


def test_revoked_without_lifecycle_cannot_reuse_release_confirmation(api):
    ready(api); release(api)
    change_status(api.factory, 'CONFIRMED')
    with api.factory.begin() as db:
        db.get(LabReport, 1).report_status = 'REVOKED'
    body = verify(api).json()
    assert body['status'] == 'REVOKED'
    assert body['blockchain_status'] == 'NOT_ANCHORED'
    assert 'blockchain_confirmed_at' not in body


def test_pdf_integrity_is_independent_of_confirmed_evidence(api):
    ready(api)
    report = release(api)
    change_status(api.factory, 'CONFIRMED')
    artifact = settings.report_storage_dir / report['pdf_path']
    artifact.chmod(0o600)
    artifact.write_bytes(b'synthetic altered PDF')
    body = verify(api).json()
    assert body['status'] == 'ALTERED' and body['blockchain_status'] == 'CONFIRMED'


def test_expired_processing_report_is_pending(env):
    seed(env.factory)
    change_status(env.factory, 'PROCESSING', lease_expires_at=NOW)
    row = state(env.factory)
    report = SimpleNamespace(report_id=1, blockchain_entity_uuid=row['entity_reference'], report_status='RELEASED')
    with env.factory() as db:
        result = status_service.report_anchoring(db, report)
    assert result.status == result.release.status == 'PENDING'


@pytest.mark.parametrize('mismatch', ['uuid', 'report_id', 'entity_type'])
def test_projection_does_not_match_unrelated_events(env, mismatch):
    seed(env.factory)
    if mismatch == 'entity_type':
        with env.factory.begin() as db:
            db.execute(update(BlockchainEvent).values(entity_type='OTHER'))
    row = state(env.factory)
    report = SimpleNamespace(report_id=2 if mismatch == 'report_id' else 1,
        blockchain_entity_uuid=str(uuid4()) if mismatch == 'uuid' else row['entity_reference'], report_status='RELEASED')
    with env.factory() as db:
        assert status_service.report_anchoring(db, report).status == 'NOT_ANCHORED'


def test_multiple_supersessions_do_not_mask_unconfirmed_evidence(env):
    seed(env.factory)
    seed(env.factory, 2, predecessor=1, event_type='REPORT_SUPERSEDED')
    seed(env.factory, 3, predecessor=1, event_type='REPORT_SUPERSEDED')
    change_status(env.factory, 'CONFIRMED', 1)
    change_status(env.factory, 'CONFIRMED', 3)
    row = state(env.factory)
    report = SimpleNamespace(report_id=1, blockchain_entity_uuid=row['entity_reference'], report_status='REVOKED')
    with env.factory() as db:
        result = status_service.report_anchoring(db, report)
    assert result.status == result.supersession.status == 'PENDING'
    assert result.release.status == 'CONFIRMED'


@pytest.mark.parametrize('backlog', ['PENDING', 'DEAD'])
def test_ready_ignores_outbox_backlog(global_api, monkeypatch, backlog):
    seed(global_api.factory)
    change_status(global_api.factory, backlog)
    global_api.app.include_router(health.router, prefix='/api/v1')
    monkeypatch.setattr(health, 'engine', global_api.engine)
    statements = []
    def record(conn, cursor, sql, *args):
        statements.append(sql)
    event.listen(global_api.engine, 'before_cursor_execute', record)
    try:
        result = global_api.client.get('/api/v1/ready')
    finally:
        event.remove(global_api.engine, 'before_cursor_execute', record)
    assert result.status_code == 200
    assert statements == ['SELECT 1']


def test_report_lists_do_not_query_outbox(two_reports):
    api = two_reports
    queries = []
    def record(conn, cursor, statement, *args):
        if 'blockchain_event' in statement:
            queries.append(statement)
    event.listen(api.engine, 'before_cursor_execute', record)
    try:
        result = call(api, 'GET', '/reports')
        assert result.status_code == 200
        assert all('anchoring' not in row for row in result.json()['items'])
        patient_login(api)
        result = api.client.get('/api/v1/patient/reports')
        assert result.status_code == 200
        assert all('blockchain_verification' not in row for row in result.json()['items'])
    finally:
        event.remove(api.engine, 'before_cursor_execute', record)
    assert queries == []


def test_status_openapi_contracts():
    from app.main import app
    schema = app.openapi()
    route = schema['paths']['/api/v1/blockchain/status']['get']
    assert route['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/BlockchainStatus')
    models = schema['components']['schemas']
    assert models['PatientBlockchainVerification']['properties']['status']['enum'] == ['NOT_ANCHORED', 'PENDING', 'RETRYING', 'CONFIRMED', 'FAILED']
    assert 'clinical validity' in models['PatientBlockchainVerification']['properties']['status']['description']
    assert 'worker/peer liveness' in models['BlockchainStatus']['properties']['worker_health']['description']
    assert set(models['LifecycleAnchoring']['properties']) == {'status', 'confirmed_at', 'transaction_id', 'block_number'}
    assert set(models['PatientBlockchainVerification']['properties']) == {'status', 'confirmed_at'}


def test_projections_use_bounded_queries_without_loading_payloads(env):
    for number in range(1, 6):
        seed(env.factory, number)
    row = state(env.factory)
    report = SimpleNamespace(report_id=1, blockchain_entity_uuid=row['entity_reference'], report_status='RELEASED')
    queries = []
    def record(conn, cursor, statement, *args):
        queries.append(statement)
    event.listen(env.engine, 'before_cursor_execute', record)
    try:
        with env.factory() as db:
            status_service.global_status(db)
            status_service.report_anchoring(db, report)
    finally:
        event.remove(env.engine, 'before_cursor_execute', record)
    assert len(queries) == 3
    assert all('canonical_payload' not in sql and 'last_error' not in sql for sql in queries)


@pytest.mark.parametrize('changes', [
    {'fabric_transaction_id': 'invalid'}, {'confirmed_at': None}, {'fabric_validation_code': 11},
])
def test_confirmation_requires_valid_receipt_fields(changes):
    row = SimpleNamespace(event_status='CONFIRMED', fabric_transaction_id='a'*64,
        confirmed_at=NOW, fabric_validation_code=0, fabric_block_number=5)
    for key, value in changes.items():
        setattr(row, key, value)
    result = status_service.lifecycle_status(row, NOW)
    assert result.status == 'FAILED'
    assert result.transaction_id is result.confirmed_at is result.block_number is None
