"""Staff activation projections and invitations use synthetic SQLite only."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.models import (Patient, PatientAccountLink, PatientActivationToken,
                        Permission, RolePermission, UserAccount, UserRole)
from app.services import patient_activation_service as service
from app.services.auth_service import utc_now
from test_phase_6a_patient_portal import (env, password_hash, lab_api, workflow_api,
    results_api, reports_api, admin, api, portal, issue, activate, call, login)


@pytest.mark.parametrize('kind,expected', [
    ('none', 'NOT_ACTIVATED'), ('pending', 'TOKEN_ACTIVE'),
    ('expired', 'TOKEN_EXPIRED'), ('revoked', 'TOKEN_REVOKED'),
    ('used', 'REVIEW_REQUIRED'), ('linked', 'ACTIVATED'),
])
def test_directory_detail_and_status_agree_without_credentials(portal, kind, expected):
    secret = None
    if kind != 'none':
        secret = issue(portal)['activation_token']
        with portal.factory.begin() as db:
            token = db.scalar(select(PatientActivationToken))
            if kind == 'expired': token.expires_at = utc_now() - timedelta(seconds=1)
            if kind == 'revoked': token.revoked_at = utc_now()
            if kind == 'used': token.used_at = utc_now()
    if kind == 'linked':
        assert activate(portal, secret).status_code == 201
    for path in ['/patients', '/patients/1', '/patients/1/activation-status']:
        response = call(portal, 'GET', path)
        assert response.status_code == 200, response.text
        data = response.json()
        row = data['items'][0] if path == '/patients' else data
        key = 'status' if path.endswith('activation-status') else 'activation_status'
        assert row[key] == expected
        assert response.headers['cache-control'] == 'no-store'
        assert 'token_hash' not in response.text and 'activation_token' not in response.text
        if secret: assert secret not in response.text


def test_reissue_expiry_link_replay_and_immutable_patient_identity(portal, monkeypatch):
    with portal.factory() as db:
        original = db.get(Patient, 1).patient_code
    first = issue(portal)['activation_token']
    now = utc_now()
    with portal.factory.begin() as db:
        db.scalar(select(PatientActivationToken)).expires_at = now
    monkeypatch.setattr(service, 'utc_now', lambda: now)
    assert call(portal, 'GET', '/patients/1/activation-status').json()['status'] == 'TOKEN_EXPIRED'
    assert activate(portal, first).status_code == 400
    second = issue(portal)['activation_token']
    assert second != first
    assert call(portal, 'GET', '/patients/1').json()['activation_status'] == 'TOKEN_ACTIVE'
    response = activate(portal, second)
    assert response.status_code == 201
    assert activate(portal, second, 'replay-user').status_code == 400
    assert call(portal, 'POST', '/patients/1/activation-token').status_code == 409
    assert call(portal, 'GET', '/patients/1').json()['activation_status'] == 'ACTIVATED'
    with portal.factory() as db:
        assert db.get(PatientAccountLink, 1).user_id == response.json()['user_id']
        assert db.get(Patient, 1).patient_code == original
        assert db.get(PatientAccountLink, 2) is None


def test_consumed_history_without_link_cannot_create_another_account(portal):
    first = issue(portal)['activation_token']
    second = issue(portal)['activation_token']
    with portal.factory.begin() as db:
        oldest = db.scalar(select(PatientActivationToken).order_by(PatientActivationToken.activation_token_id))
        oldest.used_at = utc_now()
    assert call(portal, 'GET', '/patients/1/activation-status').json()['status'] == 'REVIEW_REQUIRED'
    assert call(portal, 'POST', '/patients/1/activation-token').status_code == 409
    assert activate(portal, first).status_code == 400
    assert activate(portal, second).status_code == 400
    with portal.factory() as db:
        assert db.get(PatientAccountLink, 1) is None
        assert len(list(db.scalars(select(PatientActivationToken)))) == 2


@pytest.mark.parametrize('permission', [None, 'ACCOUNT_READ', 'PATIENT_ACCOUNT_ACTIVATE'])
def test_directory_activation_projection_requires_separate_permission(portal, permission):
    issue(portal)
    with portal.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.user_id == 1, UserRole.role_id == 2))
        for code in ['PATIENT_READ'] + ([permission] if permission else []):
            permission_id = db.scalar(select(Permission.permission_id).where(Permission.permission_code == code))
            db.add(RolePermission(role_id=1, permission_id=permission_id))
    for path in ['/patients', '/patients/1']:
        response = call(portal, 'GET', path)
        assert response.status_code == 200
        data = response.json()
        row = data['items'][0] if path == '/patients' else data
        assert ('activation_status' in row) == bool(permission)
    assert call(portal, 'GET', '/patients/1/activation-status').status_code == (200 if permission else 403)
    assert call(portal, 'POST', '/patients/1/activation-token').status_code == (201 if permission == 'PATIENT_ACCOUNT_ACTIVATE' else 403)


@pytest.mark.parametrize('association', ['role', 'link'])
def test_patient_even_with_admin_cannot_administer_invitations(portal, association):
    with portal.factory.begin() as db:
        if association == 'role': db.add(UserRole(user_id=1, role_id=3, assigned_at=utc_now()))
        else: db.add(PatientAccountLink(patient_id=2, user_id=1))
    for method, path in [('GET', '/patients/1/activation-status'), ('POST', '/patients/1/activation-token')]:
        assert call(portal, method, path).status_code == 403
    assert 'activation_status' not in call(portal, 'GET', '/patients/1').json()
    with portal.factory() as db:
        assert list(db.scalars(select(PatientActivationToken))) == []


def test_status_projection_is_page_scoped_and_read_only(portal):
    issue(portal, 2)
    response = call(portal, 'GET', '/patients?page=2&page_size=1')
    assert response.status_code == 200
    assert [r['patient_id'] for r in response.json()['items']] == [2]
    assert response.json()['items'][0]['activation_status'] == 'TOKEN_ACTIVE'
    assert call(portal, 'GET', '/patients/1').json()['activation_status'] == 'NOT_ACTIVATED'
    assert call(portal, 'PATCH', '/patients/1', {'activation_status': 'ACTIVATED'}).status_code == 422


@pytest.mark.parametrize('account_status', ['ACTIVE', 'DISABLED', 'SUSPENDED'])
def test_existing_link_wins_without_changing_historical_records(portal, account_status):
    with portal.factory.begin() as db:
        existing = UserAccount(username='historical-patient', password_hash='synthetic-unusable-hash',
                               account_status=account_status, created_at=utc_now())
        db.add(existing)
        db.flush()
        user_id = existing.user_id
        code = db.get(Patient, 1).patient_code
        db.add(PatientAccountLink(patient_id=1, user_id=user_id))
    assert call(portal, 'GET', '/patients/1/activation-status').json() == {'status': 'ACTIVATED'}
    assert call(portal, 'POST', '/patients/1/activation-token').status_code == 409
    with portal.factory() as db:
        assert db.get(Patient, 1).patient_code == code
        assert db.get(PatientAccountLink, 1).user_id == user_id
        assert db.get(UserAccount, user_id).account_status == account_status
        assert list(db.scalars(select(PatientActivationToken))) == []
