"""Focused Phase 10 HTTPS checks, synthetic SQLite only; network blocked by conftest."""
from datetime import timedelta
import json
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from app.api import auth_activity
from app.models import AuditLog, AuthSession, LoginLog, Patient, PatientAccountLink, StaffAccountLink, UserAccount, Role, UserRole
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from test_phase_3a_authentication_rbac import env, password_hash, login, csrf, PASSWORD
from test_phase_3b_identity_admin import api, admin, request, grant


@pytest.fixture
def monitor(api):
    api.app.include_router(auth_activity.router, prefix='/api/v1')
    return api


@pytest.fixture
def manager(monitor, admin):
    return admin


def seed_session(api, user_id=2, *, expired=False, revoked=False):
    import secrets
    token = secrets.token_hex(32)
    with api.factory.begin() as db:
        row = AuthSession(user_id=user_id, token_hash=hash_token(token), csrf_token_hash=hash_token('secret-csrf'),
            created_at=utc_now() - timedelta(hours=2), expires_at=utc_now()+timedelta(hours=-1 if expired else 1),
            revoked_at=utc_now() if revoked else None, ip_address='192.0.2.50', user_agent='Synthetic Browser')
        db.add(row); db.flush(); sid = row.session_id
    return sid, token


@pytest.mark.parametrize('status', ['ACTIVE', 'SUSPENDED', 'LOCKED', 'DISABLED', 'INACTIVE'])
def test_account_state_login_is_generic(monitor, status):
    with monitor.factory.begin() as db:
        db.get(UserAccount, 2).account_status = status
    result = login(monitor, 'second')
    if status == 'ACTIVE':
        assert result.status_code == 200
    else:
        assert result.status_code == 401
        assert result.json() == login(monitor, 'does-not-exist').json()
        assert status not in result.text


@pytest.mark.parametrize('status', ['SUSPENDED', 'LOCKED', 'DISABLED', 'INACTIVE'])
def test_existing_session_checks_account_state(monitor, status):
    sid, token = seed_session(monitor)
    with monitor.factory.begin() as db:
        db.get(UserAccount, 2).account_status = status
    monitor.client.cookies.set('rhu_session', token)
    assert monitor.client.get('/api/v1/auth/me').status_code == 401


def test_patient_suspension_reactivation_is_atomic_and_clinically_isolated(manager):
    with manager.factory.begin() as db:
        db.add(Patient(patient_id=1, patient_code='SYNTH', first_name='Clinical', last_name='Unchanged'))
        db.flush(); db.add(PatientAccountLink(patient_id=1, user_id=2))
    sid, token = seed_session(manager)
    response = request(manager, 'POST', '/users/2/suspend', {'reason': '  Temporary review  '})
    assert response.status_code == 200, response.text
    assert response.json()['suspension_reason'] == 'Temporary review'
    with manager.factory() as db:
        user = db.get(UserAccount, 2)
        assert user.account_status == 'SUSPENDED' and user.suspended_by_user_id == 1 and user.suspended_at
        assert db.get(AuthSession, sid).revoked_at
        patient = db.get(Patient, 1)
        assert (patient.patient_code, patient.first_name, patient.last_name) == ('SYNTH', 'Clinical', 'Unchanged')
        assert db.get(PatientAccountLink, 1).user_id == 2
        log = db.scalar(select(AuditLog).where(AuditLog.action == 'ACCOUNT_SUSPENDED'))
        assert log.record_id == 2 and log.user_id == 1 and log.new_value['reason'] == 'Temporary review'
    rows = request(manager, 'GET', '/admin/auth-activity?user_id=2&account_type=PATIENT').json()['items']
    assert {r['activity_type'] for r in rows} == {'ACCOUNT_SUSPENDED', 'SESSION_REVOKED'}
    assert 'Temporary review' not in json.dumps(rows)
    assert request(manager, 'POST', '/users/2/reactivate').status_code == 200
    with manager.factory() as db:
        user = db.get(UserAccount, 2)
        assert user.account_status == 'ACTIVE' and user.suspension_reason is None and user.suspended_at is None
        assert db.get(AuthSession, sid).revoked_at  # never resurrect old cookies
    assert login(manager, 'second').status_code == 200


@pytest.mark.parametrize('payload', [{}, {'reason': ''}, {'reason': '  '}, {'reason': 'x'*501}, {'reason': 'valid', 'revoke_sessions': False}])
def test_suspend_reason_validation(manager, payload):
    assert request(manager, 'POST', '/users/2/suspend', payload).status_code == 422


@pytest.mark.parametrize('status', ['ACTIVE', 'LOCKED', 'DISABLED', 'INACTIVE'])
def test_reactivate_is_not_an_unlock_or_enable(manager, status):
    with manager.factory.begin() as db:
        db.get(UserAccount, 2).account_status = status
    assert request(manager, 'POST', '/users/2/reactivate').status_code == 409


def test_invalid_status_transition_and_self_protection(manager):
    assert request(manager, 'POST', '/users/1/suspend', {'reason': 'test'}).status_code == 409
    assert request(manager, 'PATCH', '/users/2/status', {'account_status': 'ACTIVE'}).status_code == 409
    assert request(manager, 'POST', '/users/2/suspend', {'reason': 'test'}).status_code == 200
    assert request(manager, 'PATCH', '/users/2/status', {'account_status': 'LOCKED'}).status_code == 409
    assert request(manager, 'PATCH', '/users/2/status', {'account_status': 'DISABLED'}).status_code == 200
    assert request(manager, 'PATCH', '/users/2/status', {'account_status': 'ACTIVE'}).status_code == 200


@pytest.mark.parametrize('method,path,payload,permission', [
    ('GET', '/admin/auth-activity', None, 'AUTH_ACTIVITY_VIEW'),
    ('GET', '/admin/sessions', None, 'SESSION_MANAGE'),
    ('GET', '/admin/users/2/sessions', None, 'AUTH_ACTIVITY_VIEW'),
    ('POST', '/admin/users/2/sessions/revoke-all', None, 'SESSION_MANAGE'),
    ('POST', '/users/2/suspend', {'reason':'test'}, 'ACCOUNT_STATUS_UPDATE'),
])
def test_permissions_and_csrf(monitor, method, path, payload, permission):
    assert monitor.client.request(method, '/api/v1'+path, json=payload).status_code == 401
    assert login(monitor).status_code == 200
    assert request(monitor, method, path, payload).status_code == 403
    grant(monitor, permission)
    if method == 'POST':
        assert monitor.client.request(method, '/api/v1'+path, json=payload).status_code == 403
    assert request(monitor, method, path, payload).status_code == 200


@pytest.mark.parametrize('path', ['/admin/auth-activity', '/admin/sessions', '/admin/users/2/sessions'])
def test_patient_denied_even_with_permission(manager, monkeypatch, path):
    from app.config import settings
    monkeypatch.setattr(settings, 'patient_mfa_required', False)
    with manager.factory.begin() as db:
        db.add(Role(role_id=8, role_code='PATIENT', role_name='Patient', is_active=True)); db.flush()
        db.add(UserRole(user_id=1, role_id=8, assigned_at=utc_now()))
    assert request(manager, 'GET', path).status_code == 403
    assert request(manager, 'POST', '/admin/users/2/sessions/revoke-all').status_code == 403
    assert request(manager, 'POST', '/users/2/suspend', {'reason':'x'}).status_code == 403


def test_persisted_activity_normalization_filters_and_redaction(manager):
    now = utc_now()
    with manager.factory.begin() as db:
        db.add(StaffAccountLink(staff_id=1, user_id=2))
        for action in ['MFA_CHALLENGE_FAILED', 'MFA_CHALLENGE_SUCCESS', 'PASSWORD_CHANGE', 'ACCOUNT_MFA_RESET']:
            db.add(AuditLog(user_id=1, action=action, entity_type='user_account', record_id=2,
                created_at=now, ip_address='192.0.2.99', new_value={'secret':'NEVER-EXPOSE'}))
        db.add(LoginLog(user_id=None, username_attempted='PRIVATE-ATTEMPT', login_time=now, status='FAILED'))
    assert login(manager, password='incorrect').status_code == 401
    rows = request(manager, 'GET', '/admin/auth-activity').json()['items']
    assert {'LOGIN_SUCCESS', 'LOGIN_FAILED', 'PASSWORD_CHANGED', 'MFA_SUCCESS', 'MFA_FAILED', 'MFA_RESET'} <= {r['activity_type'] for r in rows}
    assert sum(r['activity_type'] == 'LOGIN_SUCCESS' for r in rows) == 1  # not AUTH_LOGIN duplicate
    encoded = json.dumps(rows)
    for secret in ['NEVER-EXPOSE', 'PRIVATE-ATTEMPT', 'password_hash', 'token_hash', 'csrf_token', 'new_value']:
        assert secret not in encoded
    for query in ['user_id=2', 'account_type=STAFF', 'search=second', 'search=Synthetic', 'ip_address=192.0.2.99']:
        result = request(manager, 'GET', '/admin/auth-activity?'+query).json()
        assert result['total'] == 4 and all(row['user_id'] == 2 for row in result['items'])
    assert request(manager, 'GET', '/admin/auth-activity?activity_type=MFA_FAILED&status=FAILED').json()['total'] == 1
    assert request(manager, 'GET', '/admin/auth-activity?search=%25').json()['total'] == 0
    assert request(manager, 'GET', '/admin/auth-activity?date_from=2099-01-01T00:00:00Z').json()['items'] == []
    first = request(manager, 'GET', '/admin/auth-activity?page_size=2').json()
    second = request(manager, 'GET', '/admin/auth-activity?page_size=2&page=2').json()
    assert len(first['items']) == 2 and not {r['activity_id'] for r in first['items']} & {r['activity_id'] for r in second['items']}


@pytest.mark.parametrize('query', ['page_size=101', 'page=0', 'page=10001', 'search='+'x'*101, 'date_from=2026-02-02&date_to=2026-01-01', 'activity_type=UNKNOWN'])
def test_bounded_activity_input(manager, query):
    assert request(manager, 'GET', '/admin/auth-activity?'+query).status_code == 422


def test_logout_is_exact_session_audit(manager):
    assert request(manager, 'POST', '/auth/logout').status_code == 200
    assert login(manager).status_code == 200
    response = request(manager, 'GET', '/admin/auth-activity?activity_type=LOGOUT')
    assert response.status_code == 200, response.text
    rows = response.json()['items']
    assert len(rows) == 1 and rows[0]['session_id'] and rows[0]['user_id'] == 1


def test_session_states_revoke_one_all_and_audit(manager):
    sid, token = seed_session(manager)
    other, _ = seed_session(manager)
    expired, _ = seed_session(manager, expired=True)
    revoked, _ = seed_session(manager, revoked=True)
    result = request(manager, 'GET', '/admin/users/2/sessions').json()
    assert result['total'] == 2 and all(r['state'] == 'ACTIVE' for r in result['items'])
    assert 'token' not in json.dumps(result)
    for state, expected in [('EXPIRED', expired), ('REVOKED', revoked)]:
        assert request(manager, 'GET', '/admin/users/2/sessions?state='+state).json()['items'][0]['session_id'] == expected
    assert request(manager, 'POST', f'/admin/sessions/{sid}/revoke').json()['revoked_count'] == 1
    assert request(manager, 'POST', f'/admin/sessions/{sid}/revoke').json()['revoked_count'] == 0
    assert request(manager, 'POST', '/admin/users/2/sessions/revoke-all').json()['revoked_count'] == 1
    assert request(manager, 'GET', '/admin/users/2/sessions').json()['total'] == 0
    assert request(manager, 'GET', '/admin/auth-activity?user_id=2&activity_type=SESSION_REVOKED').json()['total'] == 3
    current = request(manager, 'GET', '/admin/sessions?user_id=1').json()['items'][0]
    assert current['is_current']
    assert request(manager, 'POST', f"/admin/sessions/{current['session_id']}/revoke").status_code == 409
    assert request(manager, 'POST', '/admin/users/1/sessions/revoke-all').status_code == 409
    manager.client.cookies.clear(); manager.client.cookies.set('rhu_session', token)
    assert manager.client.get('/api/v1/auth/me').status_code == 401


def test_audit_failure_rolls_back_suspension_and_revocation(manager):
    sid, _ = seed_session(manager)
    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith('INSERT INTO audit_log'):
            raise SQLAlchemyError('synthetic audit failure')
    event.listen(manager.engine, 'before_cursor_execute', fail)
    try:
        assert request(manager, 'POST', '/users/2/suspend', {'reason':'rollback'}).status_code == 503
    finally:
        event.remove(manager.engine, 'before_cursor_execute', fail)
    with manager.factory() as db:
        assert db.get(UserAccount, 2).account_status == 'ACTIVE'
        assert db.get(AuthSession, sid).revoked_at is None


def test_account_association_filters(manager):
    with manager.factory.begin() as db:
        db.add(StaffAccountLink(staff_id=1, user_id=2))
    assert request(manager, 'GET', '/users?staff_id=1').json()['items'][0]['user_id'] == 2
    assert request(manager, 'GET', '/users?patient_id=999').json()['total'] == 0


def test_suspension_revokes_pending_mfa_challenges(manager):
    from app.models.mfa import MfaChallenge
    with manager.factory.begin() as db:
        db.add(MfaChallenge(challenge_id=1, user_id=2, token_hash=hash_token('synthetic-challenge'),
            created_at=utc_now(), expires_at=utc_now()+timedelta(minutes=5), attempt_count=0))
    assert request(manager, 'POST', '/users/2/suspend', {'reason':'review'}).status_code == 200
    with manager.factory() as db:
        assert db.get(MfaChallenge, 1).revoked_at is not None


def test_single_revoke_csrf_and_nonadmin_admin_target_protection(monitor):
    sid, _ = seed_session(monitor)
    assert login(monitor).status_code == 200
    grant(monitor, 'SESSION_MANAGE', 'ACCOUNT_STATUS_UPDATE')
    assert monitor.client.post(f'/api/v1/admin/sessions/{sid}/revoke').status_code == 403
    with monitor.factory.begin() as db:
        db.add(UserRole(user_id=2, role_id=2, assigned_at=utc_now()))
    assert request(monitor, 'POST', f'/admin/sessions/{sid}/revoke').status_code == 403
    assert request(monitor, 'POST', '/admin/users/2/sessions/revoke-all').status_code == 403
    assert request(monitor, 'POST', '/users/2/suspend', {'reason':'test'}).status_code == 403


def test_last_admin_guard_remains_in_status_service(manager):
    # An independent actor with status permission cannot deactivate the final
    # admin; self-protection and nonadmin privilege checks are additional guards.
    from app.services.administration_service import protect_last_admin, current_roles
    from fastapi import HTTPException
    with manager.factory() as db:
        with pytest.raises(HTTPException) as error:
            protect_last_admin(db, db.get(UserAccount, 1), current_roles(db, 1), db.get(Role, 2))
        assert error.value.status_code == 409


def test_revoke_audit_failure_rolls_back(manager):
    sid, _ = seed_session(manager)
    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith('INSERT INTO audit_log'):
            raise SQLAlchemyError('synthetic audit failure')
    event.listen(manager.engine, 'before_cursor_execute', fail)
    try:
        assert request(manager, 'POST', f'/admin/sessions/{sid}/revoke').status_code == 503
    finally:
        event.remove(manager.engine, 'before_cursor_execute', fail)
    with manager.factory() as db:
        assert db.get(AuthSession, sid).revoked_at is None
