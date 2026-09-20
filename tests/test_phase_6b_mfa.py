"""Synthetic patient MFA, credential privacy, rollback and clinical ownership."""
from datetime import timedelta, timezone
import json
import subprocess
import sys

import pyotp
import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import mfa as routes
from app.config import Settings, settings
from app.models import (AuditLog, AuthSession, LoginLog, MfaChallenge, MfaRecoveryCode,
    UserAccount, UserTotpMfa, UserRole, Role, RolePermission, Permission)
from app.security.mfa_crypto import decode_key, decrypt_secret, encrypt_secret, generate_key
from app.security.passwords import verify_password
from app.security.tokens import hash_token
from app.services import mfa_service as service
from app.services.auth_service import utc_now
from test_phase_6a_patient_portal import (env, password_hash, lab_api, workflow_api, results_api, reports_api,
    admin, api, portal, two_reports, provision, patient_login, login, call, count, PASSWORD)


@pytest.fixture
def security(portal, monkeypatch):
    monkeypatch.setattr(settings, 'patient_mfa_required', True)
    portal.app.include_router(routes.router, prefix='/api/v1')
    portal.clock = utc_now().replace(microsecond=0)
    monkeypatch.setattr(service, 'utc_now', lambda: portal.clock)
    portal.account = provision(portal)
    patient_login(portal)
    return portal


def otp(api, secret, advance=0):
    api.clock += timedelta(seconds=advance)
    return pyotp.TOTP(secret).at(api.clock.replace(tzinfo=timezone.utc))


def enable(api):
    response = call(api, 'POST', '/patient/mfa/totp/enroll')
    assert response.status_code == 200, response.text
    secret = response.json()['secret']
    response = call(api, 'POST', '/patient/mfa/totp/confirm', {'code': otp(api, secret)})
    assert response.status_code == 200, response.text
    return secret, response.json()['recovery_codes']


def challenge(api):
    api.client.cookies.clear()
    response = login(api, username='patient-a', password=PASSWORD)
    assert response.status_code == 202, response.text
    return response


def verify(api, code, recovery=False):
    return api.client.post('/api/v1/auth/mfa/'+('recovery' if recovery else 'verify'),
        json={'recovery_code' if recovery else 'code': code})


def test_crypto_and_key_cli():
    key = decode_key(generate_key())
    secret = pyotp.random_base32()
    ciphertext, nonce = encrypt_secret(secret, key, 42)
    ciphertext2, nonce2 = encrypt_secret(secret, key, 42)
    assert len(key) == 32 and len(nonce) == 12
    assert ciphertext != ciphertext2 and nonce != nonce2 and secret not in ciphertext
    assert decrypt_secret(ciphertext, nonce, key, 42) == secret
    for ct, iv, k, uid in ((ciphertext, nonce, key, 43), ('broken', nonce, key, 42),
                           (ciphertext, nonce2, key, 42), (ciphertext, nonce, decode_key(generate_key()), 42)):
        with pytest.raises(ValueError): decrypt_secret(ct, iv, k, uid)
    result = subprocess.run([sys.executable, '-m', 'app.cli.generate_mfa_key'], capture_output=True, text=True, check=True)
    assert len(decode_key(result.stdout.strip())) == 32 and not result.stderr


@pytest.mark.parametrize('key', ['', 'short', 'a'*44, 'A'*43, 'A'*44+'=', ' '*44, 'A'*43+'=\n'])
def test_invalid_key_rejected_without_secret_echo(key):
    with pytest.raises(ValidationError) as error:
        Settings(mfa_secret_encryption_key=key)
    assert 'input_value' not in str(error.value)


@pytest.mark.parametrize('changes', [{'mfa_totp_valid_window': 2}, {'mfa_max_challenge_attempts': 0},
    {'mfa_challenge_ttl_minutes': 16}, {'mfa_recovery_code_count': 0}, {'mfa_challenge_cookie_name': 'rhu_session'}])
def test_mfa_configuration_bounds(changes):
    with pytest.raises(ValidationError): Settings(**changes)


@pytest.mark.parametrize('path', ['/patient/me', '/patient/reports', '/patient/reports/1',
    '/patient/reports/1/pdf', '/patient/access-history', '/patients', '/users'])
def test_password_only_patient_is_limited(security, path):
    response = security.client.get('/api/v1'+path)
    assert response.status_code == 403
    assert response.json()['detail'] == 'MFA_ENROLLMENT_REQUIRED'
    basics = security.client.get('/api/v1/auth/me').json()
    assert basics['patient'] is None and basics['staff'] is None and basics['permissions'] == []
    status = security.client.get('/api/v1/patient/security')
    assert status.status_code == 200
    assert status.json() == dict(mfa_required=True, totp_enabled=False,
        mfa_verified_for_current_session=False, unused_recovery_codes=0)


def test_full_enrollment_encryption_assurance_and_recovery_privacy(security, caplog):
    api = security
    with api.factory() as db:
        before = count(db, LoginLog)
    enrolled = call(api, 'POST', '/patient/mfa/totp/enroll')
    secret = enrolled.json()['secret']
    uri = enrolled.json()['provisioning_uri']
    assert uri.startswith('otpauth://totp/') and 'patient-a' in uri and 'P-SYNTH' not in uri
    assert enrolled.headers['cache-control'] == 'no-store'
    with api.factory() as db:
        mfa = db.scalar(select(UserTotpMfa))
        assert mfa.secret_ciphertext != secret and mfa.enabled_at is None
        assert service.secret_for(mfa) == secret
    wrong = call(api, 'POST', '/patient/mfa/totp/confirm', {'code': 'xxxxxx'})
    assert wrong.status_code == 422
    code = otp(api, secret)
    bad = str((int(code)+12345)%1000000).zfill(6)
    assert call(api, 'POST', '/patient/mfa/totp/confirm', {'code': bad}).status_code == 400
    confirmed = call(api, 'POST', '/patient/mfa/totp/confirm', {'code': code})
    assert confirmed.status_code == 200
    codes = confirmed.json()['recovery_codes']
    assert len(codes) == len(set(codes)) == settings.mfa_recovery_code_count
    assert api.client.get('/api/v1/patient/me').status_code == 200
    status = api.client.get('/api/v1/patient/security').json()
    assert status['totp_enabled'] and status['mfa_verified_for_current_session'] and status['unused_recovery_codes'] == len(codes)
    assert call(api, 'POST', '/patient/mfa/totp/enroll').status_code == 409
    assert call(api, 'POST', '/patient/mfa/totp/confirm', {'code': code}).status_code == 409
    with api.factory() as db:
        assert count(db, LoginLog) == before
        row = db.scalar(select(UserTotpMfa))
        assert row.confirmed_at and row.enabled_at and row.last_used_counter is not None
        assert {r.code_hash for r in db.scalars(select(MfaRecoveryCode))} == {hash_token(service.canonical_recovery(c)) for c in codes}
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == api.account['user_id'])).mfa_verified_at
        events = list(db.scalars(select(AuditLog).where(AuditLog.user_id == api.account['user_id'])))
        serialized = json.dumps([{'old': r.old_value, 'new': r.new_value} for r in events])
        assert {'PATIENT_MFA_ENROLL_START', 'PATIENT_MFA_ENABLED'} <= {r.action for r in events}
    for value in [secret, uri, PASSWORD, *codes]:
        assert value not in serialized and value not in caplog.text


def test_challenge_cookie_full_login_and_replay(security):
    api = security
    secret, codes = enable(api)
    with api.factory() as db:
        sessions, logs = count(db, AuthSession), count(db, LoginLog)
    response = challenge(api)
    assert response.json() == {'mfa_required': True, 'methods': ['TOTP', 'RECOVERY_CODE']}
    token = response.cookies[settings.mfa_challenge_cookie_name]
    cookie = next(v for v in response.headers.get_list('set-cookie') if v.startswith(settings.mfa_challenge_cookie_name+'='))
    for attribute in ('HttpOnly', 'Secure', 'SameSite=strict', 'Path=/', 'Max-Age=300'): assert attribute in cookie
    assert token not in response.text and settings.auth_session_cookie_name not in api.client.cookies
    with api.factory() as db:
        assert count(db, AuthSession) == sessions and count(db, LoginLog) == logs
        row = db.scalar(select(MfaChallenge))
        assert row.token_hash == hash_token(token) and row.attempt_count == 0
    assert verify(api, otp(api, secret)).status_code == 401  # confirmation consumed this step
    accepted = verify(api, otp(api, secret, 30))
    assert accepted.status_code == 200
    assert settings.mfa_challenge_cookie_name not in api.client.cookies
    assert api.client.get('/api/v1/patient/me').status_code == 200
    with api.factory() as db:
        assert count(db, AuthSession) == sessions+1 and count(db, LoginLog) == logs+1
        assert db.scalar(select(MfaChallenge)).used_at
    api.client.cookies.clear()
    api.client.cookies.set(settings.mfa_challenge_cookie_name, token)
    assert verify(api, otp(api, secret, 30)).status_code == 401


@pytest.mark.parametrize('state', ['expired', 'revoked', 'used', 'exhausted', 'inactive', 'disabled', 'unknown', 'missing'])
def test_invalid_challenges_fail_generically(security, state):
    api = security
    secret, codes = enable(api)
    challenge(api)
    with api.factory.begin() as db:
        row = db.scalar(select(MfaChallenge))
        if state == 'expired': row.expires_at = api.clock-timedelta(seconds=1)
        if state == 'revoked': row.revoked_at = api.clock
        if state == 'used': row.used_at = api.clock
        if state == 'exhausted': row.attempt_count = settings.mfa_max_challenge_attempts
        if state == 'inactive': db.get(UserAccount, api.account['user_id']).account_status = 'LOCKED'
        if state == 'disabled': db.scalar(select(UserTotpMfa)).disabled_at = api.clock
    if state in {'unknown', 'missing'}:
        api.client.cookies.clear()
        if state == 'unknown': api.client.cookies.set(settings.mfa_challenge_cookie_name, 'unknown', domain='testserver.local', path='/')
    response = verify(api, codes[0], True)
    assert response.status_code == 401 and response.json() == {'detail': 'MFA verification failed.'}
    assert settings.mfa_challenge_cookie_name not in api.client.cookies


def test_attempt_budget_persists_and_does_not_lock_account(security):
    api = security
    enable(api)
    challenge(api)
    for _ in range(settings.mfa_max_challenge_attempts):
        assert verify(api, 'unknown-recovery-code', True).status_code == 401
    with api.factory() as db:
        row = db.scalar(select(MfaChallenge))
        assert row.attempt_count == settings.mfa_max_challenge_attempts and row.revoked_at
        assert db.get(UserAccount, api.account['user_id']).account_status == 'ACTIVE'
    assert settings.mfa_challenge_cookie_name not in api.client.cookies


def test_recovery_one_time_and_normalization(security):
    api = security
    secret, codes = enable(api)
    challenge(api)
    assert verify(api, ' '+codes[0].replace('-', '')+' ', True).status_code == 200
    challenge(api)
    assert verify(api, codes[0], True).status_code == 401
    assert verify(api, codes[1], True).status_code == 200
    assert api.client.get('/api/v1/patient/security').json()['unused_recovery_codes'] == len(codes)-2


def test_regeneration_requires_password_and_fresh_totp(security):
    api = security
    secret, old = enable(api)
    url = '/patient/mfa/recovery-codes/regenerate'
    assert call(api, 'POST', url, {'password': 'wrong', 'totp_code': otp(api, secret, 30)}).status_code == 400
    result = call(api, 'POST', url, {'password': PASSWORD, 'totp_code': otp(api, secret)})
    assert result.status_code == 200
    assert set(result.json()['recovery_codes']).isdisjoint(old)
    assert call(api, 'POST', url, {'password': PASSWORD, 'totp_code': otp(api, secret)}).status_code == 400
    challenge(api)
    assert verify(api, old[0], True).status_code == 401
    assert verify(api, result.json()['recovery_codes'][0], True).status_code == 200


@pytest.mark.parametrize('recovery', [True, False])
def test_disable_requires_second_factor_and_fresh_login(security, recovery):
    api = security
    secret, codes = enable(api)
    payload = {'password': PASSWORD, **({'recovery_code': codes[0]} if recovery else {'totp_code': otp(api, secret, 30)})}
    assert call(api, 'POST', '/patient/mfa/disable', {**payload, 'password': 'wrong'}).status_code == 400
    assert call(api, 'POST', '/patient/mfa/disable', payload).status_code == 200
    assert settings.auth_session_cookie_name not in api.client.cookies
    with api.factory() as db:
        assert db.scalar(select(UserTotpMfa)).disabled_at
        assert all(r.revoked_at for r in db.scalars(select(AuthSession).where(AuthSession.user_id == api.account['user_id'])))
        assert all(r.used_at or r.revoked_at for r in db.scalars(select(MfaRecoveryCode)))
    patient_login(api)
    assert api.client.get('/api/v1/patient/me').status_code == 403
    enable(api)
    assert api.client.get('/api/v1/patient/me').status_code == 200


def test_admin_reset_permission_revocation_and_actor(security):
    api = security
    enable(api)
    challenge(api)
    assert login(api).status_code == 200
    url = f'/users/{api.account["user_id"]}/mfa/reset'
    with api.factory.begin() as db:
        role = db.scalar(select(Role).where(Role.role_code == 'SYSTEM_ADMIN'))
        role_id = role.role_id
        original = role.role_code
        role.role_code = 'ORDINARY_STAFF'
    assert call(api, 'POST', url).status_code == 403
    with api.factory.begin() as db: db.get(Role, role_id).role_code = original
    result = call(api, 'POST', url)
    assert result.status_code == 200 and 'secret' not in result.text
    with api.factory() as db:
        assert db.scalar(select(UserTotpMfa)).disabled_at
        assert db.scalar(select(MfaChallenge)).revoked_at
        assert all(s.revoked_at for s in db.scalars(select(AuthSession).where(AuthSession.user_id == api.account['user_id'])))
        audit = db.scalar(select(AuditLog).where(AuditLog.action == 'ACCOUNT_MFA_RESET'))
        assert audit.user_id == 1 and audit.record_id == api.account['user_id'] and audit.new_value is None
    patient_login(api)
    assert api.client.get('/api/v1/patient/security').json()['totp_enabled'] is False
    assert api.client.get('/api/v1/patient/me').status_code == 403


def test_password_change_preserves_mfa_and_revokes_every_session(security):
    api = security
    secret, codes = enable(api)
    url = '/auth/change-password'
    assert call(api, 'POST', url, {'current_password': 'wrong', 'new_password': 'Another-password-123!'}).status_code == 400
    assert call(api, 'POST', url, {'current_password': PASSWORD, 'new_password': PASSWORD}).status_code == 400
    assert call(api, 'POST', url, {'current_password': PASSWORD, 'new_password': 'short'}).status_code == 422
    # Create an outstanding challenge without discarding this authenticated session.
    with api.factory.begin() as db:
        service.create_challenge(db, db.get(UserAccount, api.account['user_id']), None, None)
    response = call(api, 'POST', url, {'current_password': PASSWORD, 'new_password': 'Another-password-123!'})
    assert response.status_code == 200 and settings.auth_session_cookie_name not in api.client.cookies
    with api.factory() as db:
        assert verify_password('Another-password-123!', db.get(UserAccount, api.account['user_id']).password_hash)
        assert service.enabled(db.scalar(select(UserTotpMfa)))
        assert all(s.revoked_at for s in db.scalars(select(AuthSession).where(AuthSession.user_id == api.account['user_id'])))
        assert db.scalar(select(MfaChallenge)).revoked_at
    assert login(api, username='patient-a', password=PASSWORD).status_code == 401
    assert login(api, username='patient-a', password='Another-password-123!').status_code == 202


@pytest.mark.parametrize('path,body', [('/patient/mfa/totp/enroll', None), ('/patient/mfa/totp/confirm', {'code': '123456'}),
    ('/patient/mfa/recovery-codes/regenerate', {'password': PASSWORD, 'totp_code': '123456'}),
    ('/patient/mfa/disable', {'password': PASSWORD, 'recovery_code': 'unknown'}),
    ('/auth/change-password', {'current_password': PASSWORD, 'new_password': 'Another-password-123!'})])
def test_csrf_and_input_secrets(security, path, body):
    response = security.client.post('/api/v1'+path, json=body)
    assert response.status_code == 403
    assert PASSWORD not in response.text


def test_cross_origin_challenges_rejected(security):
    enable(security)
    challenge(security)
    response = security.client.post('/api/v1/auth/mfa/recovery', json={'recovery_code': 'unknown'}, headers={'Origin': 'https://evil.example'})
    assert response.status_code == 403
    with security.factory() as db: assert security_count(db) == 0


def security_count(db):
    return db.scalar(select(MfaChallenge)).attempt_count


def test_decryption_failure_is_controlled_and_audited(security, caplog):
    secret, codes = enable(security)
    challenge(security)
    with security.factory.begin() as db: db.scalar(select(UserTotpMfa)).secret_ciphertext = 'corrupt-envelope'
    result = verify(security, otp(security, secret, 30))
    assert result.status_code == 503 and 'corrupt' not in result.text
    with security.factory() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'MFA_SECRET_UNAVAILABLE'))
    assert secret not in caplog.text and 'corrupt-envelope' not in caplog.text


@pytest.mark.parametrize('operation', ['confirm', 'challenge', 'recovery', 'regenerate', 'disable', 'password'])
def test_security_audit_failure_rolls_back(operation, security):
    api = security
    if operation == 'confirm':
        secret = call(api, 'POST', '/patient/mfa/totp/enroll').json()['secret']
        codes = []
    else:
        secret, codes = enable(api)
    if operation in {'challenge', 'recovery'}: challenge(api)
    with api.factory() as db:
        before_sessions = count(db, AuthSession)
        before_counter = db.scalar(select(UserTotpMfa)).last_used_counter
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic audit failure')
    event.listen(api.engine, 'before_cursor_execute', fail)
    try:
        if operation == 'confirm': response = call(api, 'POST', '/patient/mfa/totp/confirm', {'code': otp(api, secret)})
        elif operation == 'challenge': response = verify(api, otp(api, secret, 30))
        elif operation == 'recovery': response = verify(api, codes[0], True)
        elif operation == 'regenerate': response = call(api, 'POST', '/patient/mfa/recovery-codes/regenerate', {'password': PASSWORD, 'totp_code': otp(api, secret, 30)})
        elif operation == 'disable': response = call(api, 'POST', '/patient/mfa/disable', {'password': PASSWORD, 'recovery_code': codes[0]})
        else: response = call(api, 'POST', '/auth/change-password', {'current_password': PASSWORD, 'new_password': 'Another-password-123!'})
        assert response.status_code == 503
    finally: event.remove(api.engine, 'before_cursor_execute', fail)
    with api.factory() as db:
        assert count(db, AuthSession) == before_sessions
        mfa = db.scalar(select(UserTotpMfa))
        assert mfa.last_used_counter == before_counter and mfa.disabled_at is None
        if operation == 'confirm': assert mfa.enabled_at is None and count(db, MfaRecoveryCode) == 0
        if operation in {'challenge', 'recovery'}: assert db.scalar(select(MfaChallenge)).used_at is None
        assert all(c.used_at is None and c.revoked_at is None for c in db.scalars(select(MfaRecoveryCode)))
        assert verify_password(PASSWORD, db.get(UserAccount, api.account['user_id']).password_hash)


def test_cross_patient_after_real_mfa(two_reports, monkeypatch):
    api = two_reports
    monkeypatch.setattr(settings, 'patient_mfa_required', True)
    api.app.include_router(routes.router, prefix='/api/v1')
    api.clock = utc_now()
    monkeypatch.setattr(service, 'utc_now', lambda: api.clock)
    for username, own, other in [('patient-a', 1, 2), ('patient-b', 2, 1)]:
        patient_login(api, username)
        assert api.client.get('/api/v1/patient/reports').status_code == 403
        enable(api)
        assert [r['report_id'] for r in api.client.get('/api/v1/patient/reports').json()['items']] == [own]
        for suffix in ('', '/pdf'):
            assert api.client.get(f'/api/v1/patient/reports/{own}{suffix}').status_code == 200
            denied = api.client.get(f'/api/v1/patient/reports/{other}{suffix}')
            assert denied.status_code == 404 and denied.json() == {'detail': 'Report not found.'}


def test_staff_and_policy_off_regressions(security, monkeypatch):
    api = security
    monkeypatch.setattr(settings, 'patient_mfa_required', False)
    assert api.client.get('/api/v1/patient/me').status_code == 200
    enable(api)
    assert challenge(api).status_code == 202  # optional policy never bypasses enabled MFA login
    assert login(api).status_code == 200
    assert api.client.get('/api/v1/patient/security').status_code == 403
    assert call(api, 'POST', '/auth/change-password', {'current_password': 'Synthetic-password-123!', 'new_password': 'Staff-password-456!'}).status_code == 200


def test_openapi_secret_allowlists_and_permission(security):
    from app.main import app
    from app.services.permission_catalog import ensure_permissions
    with security.factory.begin() as db:
        assert ensure_permissions(db) == []
        assert db.scalar(select(Permission).where(Permission.permission_code == 'ACCOUNT_MFA_RESET'))
    schema = app.openapi()
    for secret in ('secret_ciphertext', 'secret_nonce', 'code_hash', 'token_hash', 'password_hash'):
        assert secret not in json.dumps(schema)
    assert '202' in schema['paths']['/api/v1/auth/login']['post']['responses']
    assert not schema['paths']['/api/v1/auth/mfa/verify']['post'].get('security')


@pytest.mark.parametrize('path', ['/patient/me', '/patient/reports', '/patient/reports/1', '/patient/reports/1/pdf', '/patient/access-history'])
def test_enabled_mfa_still_requires_session_assurance(security, path):
    enable(security)
    with security.factory.begin() as db:
        row = db.scalar(select(AuthSession).where(AuthSession.user_id == security.account['user_id']))
        row.mfa_verified_at = None
    response = security.client.get('/api/v1'+path)
    assert response.status_code == 403 and response.json()['detail'] == 'MFA_REQUIRED'
    assert security.client.get('/api/v1/patient/security').status_code == 200


def test_new_challenge_revokes_previous_and_codes_are_account_bound(security):
    api = security
    secret, codes = enable(api)
    old = challenge(api).cookies[settings.mfa_challenge_cookie_name]
    challenge(api)
    with api.factory.begin() as db:
        assert db.scalar(select(MfaChallenge).where(MfaChallenge.token_hash == hash_token(old))).revoked_at
        db.add(UserAccount(user_id=100, username='other-mfa-account', password_hash='unused', account_status='ACTIVE'))
        db.flush()
        ciphertext, nonce = encrypt_secret(pyotp.random_base32(), decode_key(settings.mfa_secret_encryption_key.get_secret_value()), 100)
        other = UserTotpMfa(user_id=100, secret_ciphertext=ciphertext, secret_nonce=nonce, created_at=api.clock,
            confirmed_at=api.clock, enabled_at=api.clock)
        db.add(other)
        db.flush()
        other_codes = service.new_recovery_codes(db, other, api.clock)
    assert verify(api, other_codes[0], True).status_code == 401
    assert verify(api, codes[0], True).status_code == 200


def test_enrollment_rotation_invalidates_pending_secret_and_rollback(security):
    api = security
    original = call(api, 'POST', '/patient/mfa/totp/enroll').json()['secret']
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic audit failure')
    event.listen(api.engine, 'before_cursor_execute', fail)
    try: assert call(api, 'POST', '/patient/mfa/totp/enroll').status_code == 503
    finally: event.remove(api.engine, 'before_cursor_execute', fail)
    with api.factory() as db: assert service.secret_for(db.scalar(select(UserTotpMfa))) == original
    new = call(api, 'POST', '/patient/mfa/totp/enroll').json()['secret']
    assert new != original
    with api.factory() as db: assert service.secret_for(db.scalar(select(UserTotpMfa))) == new
    assert call(api, 'POST', '/patient/mfa/totp/confirm', {'code': otp(api, new)}).status_code == 200


def test_window_and_replay_counter(security):
    secret, codes = enable(security)
    now = security.clock.replace(tzinfo=timezone.utc)
    with security.factory.begin() as db:
        mfa = db.scalar(select(UserTotpMfa))
        assert not service.accept_totp(mfa, pyotp.TOTP(secret).at(now+timedelta(seconds=90)), security.clock)
        assert service.accept_totp(mfa, pyotp.TOTP(secret).at(now+timedelta(seconds=30)), security.clock)
        assert not service.accept_totp(mfa, pyotp.TOTP(secret).at(now), security.clock)


def test_missing_key_rejected(monkeypatch):
    monkeypatch.delenv('MFA_SECRET_ENCRYPTION_KEY')
    with pytest.raises(ValidationError): Settings(_env_file=None)


def test_account_lock_revokes_pending_challenges(security):
    api = security
    enable(api)
    challenge(api)
    assert login(api).status_code == 200
    assert call(api, 'PATCH', f'/users/{api.account["user_id"]}/status', {'account_status': 'LOCKED'}).status_code == 200
    with api.factory() as db: assert db.scalar(select(MfaChallenge)).revoked_at


@pytest.mark.parametrize('method,path,body', [('GET', '/patient/security', None),
    ('POST', '/patient/mfa/totp/enroll', None), ('POST', '/patient/mfa/totp/confirm', {'code': '123456'}),
    ('POST', '/patient/mfa/recovery-codes/regenerate', {'password': PASSWORD, 'totp_code': '123456'}),
    ('POST', '/patient/mfa/disable', {'password': PASSWORD, 'recovery_code': 'unknown'})])
def test_self_service_requires_patient_session(security, method, path, body):
    api = security
    api.client.cookies.clear()
    assert api.client.request(method, '/api/v1'+path, json=body).status_code == 401
    assert login(api).status_code == 200
    assert call(api, method, path, body).status_code == 403


@pytest.mark.parametrize('path', ['/patient/mfa/recovery-codes/regenerate', '/patient/mfa/disable'])
def test_security_mutations_require_assurance_even_when_policy_off(security, monkeypatch, path):
    api = security
    secret, codes = enable(api)
    monkeypatch.setattr(settings, 'patient_mfa_required', False)
    with api.factory.begin() as db:
        db.scalar(select(AuthSession).where(AuthSession.user_id == api.account['user_id'])).mfa_verified_at = None
    assert call(api, 'POST', path, {'password': PASSWORD, 'totp_code': otp(api, secret, 30)}).status_code == 403
