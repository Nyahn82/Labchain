"""Synthetic API/SQLite/PDF checks; no production DB, sockets or Fabric calls."""
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, event as sql_event

from app.api import blockchain_monitor
from app.config import settings
from app.models import BlockchainEvent, LabReport, Permission, Role, RolePermission, UserRole
from app.schemas import blockchain_monitor as schemas
from app.services import blockchain_monitor_client as bridge, blockchain_monitor_service as service
from app.services.permission_catalog import ensure_permissions
from app.services.rbac_service import ensure_core_roles
from phase8b_delivery_support import seed
from test_phase_5b_release import (
    env, password_hash, lab_api, workflow_api, results_api, reports_api, admin, api,
    ready, release, login,
)

BASE = '/api/v1/admin/blockchain'
H = 'a' * 64
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


@pytest.fixture
def monitor_api(env, monkeypatch):
    env.app.include_router(blockchain_monitor.router, prefix='/api/v1')
    with env.factory.begin() as db:
        ensure_permissions(db)
        ensure_core_roles(db)
    def unavailable(*a, **kw):
        raise bridge.MonitorUnavailable()
    monkeypatch.setattr(bridge, 'query', unavailable)
    return env


def grant(api, code):
    with api.factory.begin() as db:
        pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == code))
        db.add(RolePermission(role_id=1, permission_id=pid))


def test_unauthenticated_unauthorized_explicit_grants_and_admin(monitor_api):
    a = monitor_api
    paths = ['/overview', '/queue', '/blocks', '/blocks/1', '/transactions/' + H, '/anchors', '/reports/1/integrity']
    for p in paths:
        assert a.client.get(BASE + p).status_code == 401
    assert login(a).status_code == 200
    for p in paths:
        assert a.client.get(BASE + p).status_code == 403
    grant(a, 'BLOCKCHAIN_STATUS_VIEW')  # Existing staff permission must not grant explorer access.
    assert a.client.get(BASE + '/overview').status_code == 403
    grant(a, 'BLOCKCHAIN_EXPLORER_VIEW')
    assert a.client.get(BASE + '/overview').status_code == 200
    assert a.client.get(BASE + '/reports/1/integrity').status_code == 403
    with a.factory.begin() as db:
        rid = db.scalar(select(Role.role_id).where(Role.role_code == 'SYSTEM_ADMIN'))
        db.add(UserRole(user_id=1, role_id=rid, assigned_at=NOW))
    assert a.client.get(BASE + '/reports/1/integrity').status_code == 404
    assert a.client.get(BASE + '/overview').status_code == 200


def test_unknown_network_is_distinct_from_idle_queue(monitor_api):
    a = monitor_api; grant(a, 'BLOCKCHAIN_EXPLORER_VIEW'); login(a)
    result = a.client.get(BASE + '/overview')
    assert result.headers['cache-control'] == 'no-store'
    assert result.json()['status'] == 'UNKNOWN'
    assert all(n['height'] is None for n in result.json()['nodes'])
    assert a.client.get(BASE + '/queue').json()['worker_health'] == 'IDLE'


def test_query_boundaries_redaction_and_pagination(monitor_api, monkeypatch):
    a = monitor_api; grant(a, 'BLOCKCHAIN_EXPLORER_VIEW'); login(a)
    calls = []
    def query(request, schema):
        calls.append(request)
        return schemas.Blocks(items=[], next_before=None, ledger_height=0, source_peer='peer1', checked_at=NOW)
    monkeypatch.setattr(bridge, 'query', query)
    assert a.client.get(BASE + '/blocks?before=4&limit=2').status_code == 200
    assert calls == [{'action': 'blocks', 'before': 4, 'limit': 2}]
    for path in ['/blocks?limit=11', '/blocks/-1', '/transactions/PRIVATE-KEY', '/anchors?entity_reference=SECRET']:
        response = a.client.get(BASE + path)
        assert response.status_code == 422
        assert 'PRIVATE' not in response.text and 'SECRET' not in response.text
    assert len(calls) == 1


def test_monitor_unavailable_is_sanitized(monitor_api):
    grant(monitor_api, 'BLOCKCHAIN_EXPLORER_VIEW'); login(monitor_api)
    response = monitor_api.client.get(BASE + '/blocks/1')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Fabric query unavailable. No ledger conclusion can be drawn.'}


def test_anchor_projection_keyset_filters_and_no_private_fields(monitor_api):
    a = monitor_api; grant(a, 'BLOCKCHAIN_EXPLORER_VIEW'); login(a)
    for i in range(1, 5):
        seed(a.factory, i, last_error='PRIVATE_EXCEPTION_WITH_KEY', lease_token='PRIVATE_LEASE')
    first = a.client.get(BASE + '/anchors?limit=2').json()
    assert [r['event_id'] for r in first['items']] == [4, 3]
    second = a.client.get(BASE + '/anchors?limit=2&before=3').json()
    assert [r['event_id'] for r in second['items']] == [2, 1]
    assert second['next_before'] is None
    assert a.client.get(BASE + '/anchors?status=CONFIRMED').json()['items'] == []
    ref = first['items'][0]['entity_reference']
    assert len(a.client.get(BASE + '/anchors?entity_reference=' + ref).json()['items']) == 1
    text = json.dumps(first)
    for denied in ['canonical_payload', 'lease_token', 'last_error', 'entity_id', 'PRIVATE', 'created_by_user_id']:
        assert denied not in text


@pytest.fixture
def released(api, monkeypatch):
    api.app.include_router(blockchain_monitor.router, prefix='/api/v1')
    ready(api); release(api)
    with api.factory.begin() as db:
        row = db.scalar(select(BlockchainEvent).where(BlockchainEvent.event_type == 'REPORT_RELEASED'))
        row.event_status = 'CONFIRMED'; row.fabric_validation_code = 0
        row.fabric_transaction_id = H; row.fabric_block_number = 3; row.confirmed_at = NOW.replace(tzinfo=None)
        anchor = dict(anchor_id=row.event_uuid, entity_reference=row.entity_reference, event_type=row.event_type,
            content_hash=row.record_hash, previous_hash=row.previous_hash, transaction_id=H,
            source_peer='peer1', checked_at=NOW)
    calls = []
    def query(request, schema):
        calls.append(request)
        if request['action'] == 'anchor':
            return schemas.AnchorEvidence(**anchor)
        return schemas.TransactionDetail(transaction_id=H, validation_code=0, validation_status='VALID',
            timestamp=NOW, block_number=3, block_hash='b' * 64, source_peer='peer1', checked_at=NOW)
    monkeypatch.setattr(bridge, 'query', query)
    return SimpleNamespace(api=api, calls=calls, anchor=anchor)


def test_integrity_verified_is_read_only_and_does_not_return_pdf(released):
    a = released.api
    statements = []
    def watch(conn, cursor, statement, parameters, context, many):
        statements.append(statement.strip().split()[0].upper())
    sql_event.listen(a.engine, 'before_cursor_execute', watch)
    # Service-level check excludes routine session bookkeeping by auth middleware.
    with a.factory() as db:
        result = service.integrity(db, 1)
        assert not db.new and not db.dirty and not db.deleted
    sql_event.remove(a.engine, 'before_cursor_execute', watch)
    assert result.status == 'VERIFIED'
    assert set(statements) <= {'SELECT'}
    assert [r['action'] for r in released.calls] == ['anchor', 'transaction']
    response = a.client.get(BASE + '/reports/1/integrity')
    assert response.status_code == 200
    for denied in ['canonical_payload', 'patient', 'pdf_path', '%PDF', 'lease', 'PRIVATE']:
        assert denied not in response.text


@pytest.mark.parametrize('case,expected', [
    ('file', 'MISMATCH'), ('missing', 'FILE_MISSING'), ('pending', 'NOT_ANCHORED'),
    ('ledger', 'MISMATCH'), ('unavailable', 'UNKNOWN'), ('draft', 'REPORT_NOT_RELEASED'),
    ('no_event', 'NOT_ANCHORED'), ('symlink', 'UNKNOWN'),
])
def test_integrity_failures(released, monkeypatch, case, expected, tmp_path):
    a = released.api
    with a.factory() as db:
        path = settings.report_storage_dir / db.get(LabReport, 1).pdf_path
    if case == 'file':
        path.chmod(0o600)  # Only the synthetic test artifact; releases are immutable on disk.
        path.write_bytes(b'altered synthetic PDF')
    elif case == 'missing':
        path.unlink()
    elif case == 'symlink':
        path.unlink(); path.symlink_to(tmp_path / 'private')
    elif case == 'ledger':
        released.anchor['content_hash'] = 'f' * 64
    elif case == 'unavailable':
        def unavailable(*a, **kw):
            raise bridge.MonitorUnavailable()
        monkeypatch.setattr(bridge, 'query', unavailable)
    elif case == 'draft':
        with a.factory.begin() as db:
            db.get(LabReport, 1).report_status = 'GENERATED'
    elif case == 'no_event':
        # Simulate a legacy report through a read stub, never delete an immutable event.
        original = service.select
        monkeypatch.setattr(service, 'select', lambda model: original(model).where(False) if model is BlockchainEvent else original(model))
    else:
        with a.factory.begin() as db:
            db.scalar(select(BlockchainEvent)).event_status = 'PENDING'
    assert a.client.get(BASE + '/reports/1/integrity').json()['status'] == expected


class FakeSocket:
    def __init__(self, data): self.data = data; self.sent = None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): assert 0 < value <= 12
    def connect(self, path): assert path == '/run/rhu-labchain-monitor/monitor.sock'
    def sendall(self, data): self.sent = data
    def recv(self, size):
        part, self.data = self.data[:size], self.data[size:]
        return part


@pytest.mark.parametrize('data', [b'PRIVATE SECRET\n', b'{"ok":false,"error":"PRIVATE"}\n',
    b'{"ok":true,"result":{"canonical_payload":"PRIVATE"}}\n', b'x' * (1024 * 1024 + 1), b''],
    ids=['invalid-json', 'private-error', 'private-field', 'oversized', 'empty'])
def test_socket_bridge_rejects_malformed_oversized_private_responses(data, monkeypatch):
    monkeypatch.setattr(bridge.socket, 'socket', lambda *a: FakeSocket(data))
    with pytest.raises(bridge.MonitorUnavailable) as err:
        bridge.query({'action': 'overview'}, schemas.Overview)
    assert 'PRIVATE' not in str(err.value)


@pytest.mark.parametrize('age,valid', [(0, True), (60, False), (-60, False)])
def test_socket_bridge_accepts_only_fresh_typed_evidence(age, valid, monkeypatch):
    body = dict(items=[], next_before=None, ledger_height=0, source_peer='peer1',
                checked_at=(datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat())
    sock = FakeSocket(json.dumps({'ok': True, 'result': body}).encode() + b'\n')
    monkeypatch.setattr(bridge.socket, 'socket', lambda *a: sock)
    if valid:
        assert bridge.query({'action': 'blocks', 'before': None, 'limit': 10}, schemas.Blocks).ledger_height == 0
    else:
        with pytest.raises(bridge.MonitorUnavailable):
            bridge.query({'action': 'blocks', 'before': None, 'limit': 10}, schemas.Blocks)


def test_socket_timeout_is_sanitized(monkeypatch):
    sock = FakeSocket(b'')
    def timeout(_):
        raise TimeoutError('PRIVATE credentials /path')
    monkeypatch.setattr(sock, 'connect', timeout)
    monkeypatch.setattr(bridge.socket, 'socket', lambda *a: sock)
    with pytest.raises(bridge.MonitorUnavailable) as err:
        bridge.query({'action': 'overview'}, schemas.Overview)
    assert 'PRIVATE' not in str(err.value)
