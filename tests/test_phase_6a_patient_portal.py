"""Synthetic activation, strict ownership, portal privacy and rollback checks."""
from datetime import timedelta
import hashlib
import json
import re

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import administration, patient_activation, patient_portal, patients
from app.config import settings
from app.models import (AuditLog, AuthSession, LabReport, LoginLog, Patient, PatientAccountLink,
    PatientActivationToken, Permission, ReportVerification, Role, RolePermission, UserAccount, UserRole)
from app.security.passwords import verify_password
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from test_phase_5b_release import (env, password_hash, lab_api, workflow_api, results_api, reports_api,
    admin, api, ready, release, metadata, verify, call, create, login, count)
from test_phase_5a_reports import completed, generate, sign

PASSWORD = 'Synthetic-patient-password-123!'


@pytest.fixture
def portal(api, monkeypatch):
    # Preserve Phase 6A behavior under the supported policy-off configuration.
    # Phase 6B tests explicitly enable policy and exercise ownership after real MFA.
    monkeypatch.setattr(settings, 'patient_mfa_required', False)
    for router in (patient_activation.router, patient_portal.router, patients.router, administration.router):
        api.app.include_router(router, prefix='/api/v1')
    with api.factory.begin() as db:
        db.add(Role(role_id=3, role_code='PATIENT', role_name='Patient', is_active=True))
    return api


def issue(api, patient_id=1):
    response = call(api, 'POST', f'/patients/{patient_id}/activation-token')
    assert response.status_code == 201, response.text
    return response.json()


def activate(api, token, username='patient-a', **changes):
    return api.client.post('/api/v1/patient/activate', json={
        'activation_token': token, 'username': username, 'password': PASSWORD, **changes})


def provision(api, patient_id=1, username='patient-a'):
    token = issue(api, patient_id)['activation_token']
    response = activate(api, token, username)
    assert response.status_code == 201, response.text
    return response.json()


def patient_login(api, username='patient-a'):
    api.client.cookies.clear()
    response = login(api, username=username, password=PASSWORD)
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def two_reports(portal):
    ready(portal)
    a = release(portal)
    completed(portal, patient_id=2)
    response = generate(portal, order_id=2, template_id=1)
    assert response.status_code == 201, response.text
    link = create(portal, '/reports/2/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'})
    assert sign(portal, link['report_signatory_id'], 2).status_code == 200
    assert call(portal, 'POST', '/reports/2/approve').status_code == 200
    b = release(portal, 2)
    portal.report_a, portal.report_b = a, b
    portal.account_a = provision(portal)
    portal.account_b = provision(portal, 2, 'patient-b')
    return portal


@pytest.mark.parametrize('method,path', [('POST', '/patients/1/activation-token'), ('GET', '/patients/1/activation-status')])
def test_staff_issuance_permission_and_csrf(portal, method, path):
    portal.client.cookies.clear()
    assert portal.client.request(method, '/api/v1'+path).status_code == 401
    assert login(portal).status_code == 200
    with portal.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.user_id == 1, UserRole.role_id == 2))
    assert call(portal, method, path).status_code == 403
    with portal.factory.begin() as db:
        permission_id = db.scalar(select(Permission.permission_id).where(Permission.permission_code == 'PATIENT_ACCOUNT_ACTIVATE'))
        db.add(RolePermission(role_id=1, permission_id=permission_id))
    if method == 'POST':
        assert portal.client.post('/api/v1'+path).status_code == 403
    assert call(portal, method, path).status_code in {200, 201}


def test_issuance_hash_ttl_status_rotation_history_and_privacy(portal, caplog):
    assert call(portal, 'GET', '/patients/1/activation-status').json() == {'status': 'NOT_ACTIVATED'}
    first = issue(portal)
    assert re.fullmatch(r'[A-Za-z0-9_-]{32}', first['activation_token'])
    assert set(first) == {'activation_token', 'expires_at', 'patient_code'}
    assert call(portal, 'GET', '/patients/1/activation-status').json() == {'status': 'TOKEN_ACTIVE'}
    second = issue(portal)
    assert first['activation_token'] != second['activation_token']
    with portal.factory() as db:
        rows = list(db.scalars(select(PatientActivationToken).order_by(PatientActivationToken.activation_token_id)))
        assert len(rows) == 2 and rows[0].revoked_at and rows[1].revoked_at is None
        assert rows[1].token_hash == hashlib.sha256(second['activation_token'].encode()).hexdigest()
        assert rows[1].expires_at - rows[1].created_at == timedelta(minutes=settings.patient_activation_ttl_minutes)
        assert rows[1].issued_by_user_id == 1 and rows[1].used_at is None
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action == 'PATIENT_ACTIVATION_TOKEN_ISSUE')))
        assert len(logs) == 2
        contents = json.dumps([{'old': row.old_value, 'new': row.new_value} for row in logs])
        for secret in (first['activation_token'], second['activation_token'], rows[1].token_hash):
            assert secret not in contents and secret not in caplog.text
    assert activate(portal, first['activation_token']).status_code == 400
    assert call(portal, 'POST', '/patients/999/activation-token').status_code == 404
    assert call(portal, 'GET', '/patients/999/activation-status').status_code == 404


def test_public_activation_atomic_link_role_password_and_existing_login(portal, caplog):
    issued = issue(portal)
    portal.client.cookies.clear()
    response = activate(portal, issued['activation_token'], '  Patient-A  ')
    assert response.status_code == 201, response.text
    account = response.json()
    assert account['username'] == 'Patient-A' and account['roles'] == ['PATIENT'] and account['account_status'] == 'ACTIVE'
    assert set(account) == {'user_id', 'username', 'roles', 'account_status'}
    assert not response.cookies and response.headers['cache-control'] == 'no-store'
    with portal.factory() as db:
        row = db.get(UserAccount, account['user_id'])
        assert row.password_hash.startswith('$argon2id$') and verify_password(PASSWORD, row.password_hash)
        assert db.get(PatientAccountLink, 1).user_id == row.user_id
        assignment = db.scalar(select(UserRole).where(UserRole.user_id == row.user_id))
        assert assignment.role_id == 3 and assignment.assigned_by == 1
        assert assignment.assigned_at and db.scalar(select(PatientActivationToken)).used_at
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'PATIENT_ACCOUNT_ACTIVATE')).user_id == row.user_id
        assert count(db, LoginLog) == 1  # only the pre-existing staff login
    for secret in (PASSWORD, issued['activation_token'], '$argon2id$'):
        assert secret not in response.text and secret not in caplog.text
    patient_login(portal, 'Patient-A')
    with portal.factory() as db:
        assert count(db, LoginLog) == 2
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == account['user_id']))
    # Existing unsafe auth routes still enforce CSRF for patients.
    assert portal.client.post('/api/v1/auth/logout').status_code == 403
    assert login(portal).status_code == 200
    assert call(portal, 'GET', '/patients/1/activation-status').json() == {'status': 'ACTIVATED'}
    assert call(portal, 'POST', '/patients/1/activation-token').status_code == 409


@pytest.mark.parametrize('state', ['unknown', 'expired', 'revoked', 'used', 'linked'])
def test_invalid_token_states_have_identical_public_failure(portal, state):
    token = issue(portal)['activation_token']
    with portal.factory.begin() as db:
        row = db.scalar(select(PatientActivationToken))
        if state == 'expired': row.expires_at = utc_now()-timedelta(seconds=1)
        if state == 'revoked': row.revoked_at = utc_now()
        if state == 'used': row.used_at = utc_now()
        if state == 'linked': db.add(PatientAccountLink(patient_id=1, user_id=1))
    if state == 'unknown': token = 'unknown-token'
    response = activate(portal, token)
    assert response.status_code == 400
    assert response.json() == {'detail': 'Invalid or expired activation token.'}
    if state == 'expired':
        assert call(portal, 'GET', '/patients/1/activation-status').json() == {'status': 'TOKEN_EXPIRED'}


def test_actual_token_reuse_and_duplicate_username_are_atomic(portal):
    token = issue(portal)['activation_token']
    assert activate(portal, token, 'tester').status_code == 409
    with portal.factory() as db:
        assert db.scalar(select(PatientActivationToken)).used_at is None
        assert count(db, PatientAccountLink) == 0
    assert activate(portal, token).status_code == 201
    assert activate(portal, token, 'another-name').status_code == 400
    with portal.factory() as db:
        assert count(db, PatientAccountLink) == 1 and count(db, UserAccount) == 2


@pytest.mark.parametrize('role_state', ['missing', 'inactive'])
def test_role_configuration_fails_safely(portal, role_state):
    token = issue(portal)['activation_token']
    with portal.factory.begin() as db:
        if role_state == 'missing': db.execute(delete(Role).where(Role.role_id == 3))
        else: db.get(Role, 3).is_active = False
    assert activate(portal, token).status_code == 503
    with portal.factory() as db:
        assert db.scalar(select(PatientActivationToken)).used_at is None and count(db, UserAccount) == 1


@pytest.mark.parametrize('changes', [{'role_codes': ['SYSTEM_ADMIN']}, {'patient_id': 2}, {'user_id': 1},
    {'account_status': 'ACTIVE'}, {'password': 'short'}, {'password': 'a'*1025}, {'username': ' '}, {'token_hash': 'secret'}])
def test_activation_input_allowlist_and_secret_validation(portal, changes):
    token = issue(portal)['activation_token']
    response = activate(portal, token, **changes)
    assert response.status_code == 422
    assert response.json() == {'detail': 'Invalid request fields or query parameters.'}
    assert token not in response.text and PASSWORD not in response.text
    with portal.factory() as db: assert db.scalar(select(PatientActivationToken)).used_at is None


@pytest.mark.parametrize('target', ['user_account', 'patient_account_link', 'user_role', 'audit_log', 'commit'])
def test_activation_failure_preserves_unused_token(portal, target):
    token = issue(portal)['activation_token']
    def fail(*args):
        if target == 'commit' or args[2].startswith(f'INSERT INTO {target} '):
            raise SQLAlchemyError('Synthetic rollback')
    owner, event_name = (portal.factory, 'before_commit') if target == 'commit' else (portal.engine, 'before_cursor_execute')
    event.listen(owner, event_name, fail)
    try:
        assert activate(portal, token).status_code == 503
    finally:
        event.remove(owner, event_name, fail)
    with portal.factory() as db:
        assert count(db, UserAccount) == 1 and count(db, PatientAccountLink) == 0
        assert db.scalar(select(PatientActivationToken)).used_at is None
    assert activate(portal, token).status_code == 201


def test_issue_failure_restores_previous_valid_token(portal):
    issue(portal)
    def fail(conn, cursor, statement, *args):
        if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic rollback')
    event.listen(portal.engine, 'before_cursor_execute', fail)
    try: assert call(portal, 'POST', '/patients/1/activation-token').status_code == 503
    finally: event.remove(portal.engine, 'before_cursor_execute', fail)
    with portal.factory() as db:
        assert count(db, PatientActivationToken) == 1
        assert db.scalar(select(PatientActivationToken)).revoked_at is None


PORTAL_PATHS = ['/patient/me', '/patient/reports', '/patient/reports/1', '/patient/reports/1/pdf', '/patient/access-history']


@pytest.mark.parametrize('path', PORTAL_PATHS)
def test_patient_role_link_and_authentication_required(portal, path):
    portal.client.cookies.clear()
    assert portal.client.get('/api/v1'+path).status_code == 401
    assert login(portal).status_code == 200
    # SYSTEM_ADMIN is not a bypass for patient identity/role requirements.
    assert portal.client.get('/api/v1'+path).status_code == 403
    with portal.factory.begin() as db:
        db.add(UserRole(user_id=1, role_id=3, assigned_at=utc_now()))
    response = portal.client.get('/api/v1'+path)
    assert response.status_code == 403 and 'not configured' in response.text


def test_patient_profile_exact_allowlist_and_no_self_edit(portal):
    provision(portal)
    patient_login(portal)
    response = portal.client.get('/api/v1/patient/me')
    assert response.status_code == 200 and response.json()['patient_id'] == 1
    assert response.json()['patient_code'] == 'P-SYNTH-1'
    assert set(response.json()) == {'patient_id', 'patient_code', 'first_name', 'middle_name', 'last_name', 'suffix',
        'birth_date', 'sex', 'civil_status', 'nationality', 'contact_number', 'email', 'address'}
    assert response.headers['cache-control'] == 'no-store'
    assert portal.client.patch('/api/v1/patient/me', json={'first_name': 'Rewrite'}).status_code == 405
    for path in ('/patients', '/users', '/reports', '/lab-orders'):
        assert portal.client.get('/api/v1'+path).status_code == 403


@pytest.mark.parametrize('username,own,other', [('patient-a', 1, 2), ('patient-b', 2, 1)])
def test_cross_patient_manual_id_substitution_denied_server_side(two_reports, username, own, other):
    api = two_reports
    patient_login(api, username)
    listing = api.client.get('/api/v1/patient/reports').json()
    assert [row['report_id'] for row in listing['items']] == [own]
    assert api.client.get(f'/api/v1/patient/reports/{own}').status_code == 200
    assert api.client.get(f'/api/v1/patient/reports/{own}/pdf').content.startswith(b'%PDF-')
    for suffix in ('', '/pdf'):
        denied = api.client.get(f'/api/v1/patient/reports/{other}{suffix}')
        missing = api.client.get(f'/api/v1/patient/reports/999{suffix}')
        assert denied.status_code == missing.status_code == 404
        assert denied.json() == missing.json() == {'detail': 'Report not found.'}
    assert api.client.get(f'/api/v1/patient/reports?patient_id={other}').status_code == 422
    with api.factory() as db:
        user_id = api.account_a['user_id'] if own == 1 else api.account_b['user_id']
        events = list(db.scalars(select(AuditLog).where(AuditLog.user_id == user_id, AuditLog.action.like('PATIENT_REPORT_%'))))
        assert {row.record_id for row in events} == {own}
        assert {row.action for row in events} == {'PATIENT_REPORT_VIEW', 'PATIENT_REPORT_DOWNLOAD'}
        assert all(row.entity_type == 'LAB_REPORT' and row.old_value is row.new_value is None for row in events)


def test_detail_snapshots_and_internal_fields_not_exposed(two_reports):
    api = two_reports
    with api.factory.begin() as db:
        db.get(Patient, 1).first_name = 'CHANGED_LIVE_NAME'
        db.get(LabReport, 1).remarks = 'PRIVATE_STAFF_REMARKS'
    patient_login(api)
    response = api.client.get('/api/v1/patient/reports/1')
    assert response.status_code == 200, response.text
    assert response.json()['patient_snapshot']['patient_name'] == api.report_a['patient_snapshot']['patient_name']
    assert response.json()['result_snapshots'][0]['result_value_snapshot'] == api.report_a['result_snapshots'][0]['result_value_snapshot']
    for secret in ('CHANGED_LIVE_NAME', 'PRIVATE_STAFF_REMARKS', 'pdf_path', 'signature_image_path', 'result_item_id',
                   'staff_id', 'user_id', 'order_id', 'template_id', 'token_hash', 'password', 'approved_by', 'generated_by'):
        assert secret not in response.text


@pytest.mark.parametrize('status', ['GENERATED', 'APPROVED', 'REVOKED'])
def test_unreleased_and_revoked_hidden_everywhere(two_reports, status):
    api = two_reports
    with api.factory.begin() as db: db.get(LabReport, 1).report_status = status
    patient_login(api)
    assert api.client.get('/api/v1/patient/reports').json()['total'] == 0
    for suffix in ('', '/pdf'):
        assert api.client.get('/api/v1/patient/reports/1'+suffix).status_code == 404


@pytest.mark.parametrize('defect', ['tampered', 'missing', 'traversal', 'revoked_verification', 'missing_verification'])
def test_patient_download_integrity_blocks_delivery_and_audits(two_reports, defect):
    api = two_reports
    path = settings.report_storage_dir / api.report_a['pdf_path']
    if defect == 'tampered':
        path.chmod(0o600)
        path.write_bytes(b'%PDF-tampered')
    if defect == 'missing': path.unlink()
    with api.factory.begin() as db:
        if defect == 'traversal': db.get(LabReport, 1).pdf_path = '../private'
        if defect == 'revoked_verification': db.scalar(select(ReportVerification).where(ReportVerification.report_id == 1)).verification_status = 'REVOKED'
        if defect == 'missing_verification': db.execute(delete(ReportVerification).where(ReportVerification.report_id == 1))
    patient_login(api)
    response = api.client.get('/api/v1/patient/reports/1/pdf')
    assert response.status_code == 409 and response.headers['content-type'] == 'application/json'
    assert str(settings.report_storage_dir) not in response.text and '../private' not in response.text
    with api.factory() as db:
        log = db.scalar(select(AuditLog).where(AuditLog.action == 'REPORT_INTEGRITY_MISMATCH'))
        assert log.user_id == api.account_a['user_id'] and log.new_value['severity'] == 'HIGH'
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'PATIENT_REPORT_DOWNLOAD')) is None


def test_patient_access_history_is_scoped_paginated_and_redacted(two_reports):
    api = two_reports
    patient_login(api)
    for _ in range(2): assert api.client.get('/api/v1/patient/reports/1').status_code == 200
    assert api.client.get('/api/v1/patient/reports/1/pdf').status_code == 200
    with api.factory.begin() as db:
        db.add_all([AuditLog(user_id=api.account_b['user_id'], action='PATIENT_REPORT_VIEW', entity_type='LAB_REPORT', record_id=2),
            AuditLog(user_id=1, action='REPORT_DOWNLOAD', entity_type='lab_report', record_id=1),
            AuditLog(user_id=api.account_a['user_id'], action='PATIENT_REPORT_VIEW', entity_type='LAB_REPORT', record_id=2),
            AuditLog(user_id=api.account_a['user_id'], action='ACCOUNT_STATUS_UPDATE', entity_type='user_account', record_id=1)])
    response = api.client.get('/api/v1/patient/access-history?page_size=2')
    body = response.json()
    assert body['total'] == 3 and len(body['items']) == 2
    assert len(api.client.get('/api/v1/patient/access-history?page_size=2&page=2').json()['items']) == 1
    assert all(set(row) == {'action', 'timestamp', 'report_code'} for row in body['items'])
    assert all(row['report_code'] == api.report_a['report_code'] for row in body['items'])
    assert api.report_b['report_code'] not in response.text
    assert api.client.get('/api/v1/patient/access-history?user_id=1').status_code == 422


def test_report_list_filters_pagination_and_no_list_audit(two_reports):
    api = two_reports
    patient_login(api)
    released_date = api.report_a['released_at'][:10]
    for query in ('?page_size=1', '?search='+api.report_a['report_code'], '?date_from='+released_date+'&date_to='+released_date):
        response = api.client.get('/api/v1/patient/reports'+query)
        assert response.status_code == 200 and response.json()['total'] == 1
    for query in ('?page=2&page_size=1', '?search=not-found', '?date_to=2000-01-01', '?search=%25'):
        assert api.client.get('/api/v1/patient/reports'+query).json()['items'] == []
    for query in ('?date_from=2026-01-02&date_to=2026-01-01', '?page=0', '?page_size=101', '?search='+'x'*201, '?order_id=2'):
        assert api.client.get('/api/v1/patient/reports'+query).status_code == 422
    with api.factory() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action.in_(['PATIENT_REPORT_VIEW', 'PATIENT_REPORT_DOWNLOAD']))) is None


def test_real_supersession_and_revocation_update_portal_visibility(two_reports):
    api = two_reports
    old_url = metadata(api)['verification_url']
    original_pdf = (settings.report_storage_dir / api.report_a['pdf_path']).read_bytes()
    new = call(api, 'POST', '/reports/1/revise', {}).json()
    link = create(api, f'/reports/{new["report_id"]}/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'})
    assert sign(api, link['report_signatory_id'], new['report_id']).status_code == 200
    assert call(api, 'POST', f'/reports/{new["report_id"]}/approve').status_code == 200
    release(api, new['report_id'])
    assert api.client.get(old_url).json()['status'] == 'REVOKED'
    patient_login(api)
    assert [row['report_id'] for row in api.client.get('/api/v1/patient/reports').json()['items']] == [new['report_id']]
    assert api.client.get('/api/v1/patient/reports/1').status_code == 404
    assert api.client.get('/api/v1/patient/reports/1/pdf').status_code == 404
    assert api.client.get(f'/api/v1/patient/reports/{new["report_id"]}/pdf').status_code == 200
    assert login(api).status_code == 200
    assert call(api, 'GET', '/reports/1/pdf').content == original_pdf
    assert call(api, 'POST', f'/reports/{new["report_id"]}/revoke', {'reason': 'Synthetic'}).status_code == 200
    patient_login(api)
    assert api.client.get('/api/v1/patient/reports').json()['total'] == 0
    with api.factory() as db: assert count(db, LabReport) == 3


def test_permissions_config_and_openapi(portal):
    with portal.factory.begin() as db: assert ensure_permissions(db) == []
    from app.config import Settings
    from pydantic import ValidationError
    for value in (0, 1441):
        with pytest.raises(ValidationError): Settings(patient_activation_ttl_minutes=value)
    from app.main import app
    paths = app.openapi()['paths']
    assert not paths['/api/v1/patient/activate']['post'].get('security')
    for path in PORTAL_PATHS:
        path = path.replace('/reports/1', '/reports/{report_id}')
        assert paths['/api/v1'+path]['get']['security']


def test_report_ordering_and_order_code_search(two_reports):
    api = two_reports
    with api.factory.begin() as db:
        first = db.get(LabReport, 1)
        # Synthetic existing released records exercise list pagination/order only.
        for identifier in (3, 4):
            db.add(LabReport(report_id=identifier, report_code=f'SYNTH-{identifier}', order_id=first.order_id,
                facility_id=first.facility_id, version_no=identifier, report_status='RELEASED',
                generated_by_user_id=1, generated_at=first.generated_at, released_at=first.released_at))
        from app.models import LabOrder
        order_code = db.get(LabOrder, first.order_id).order_code
    patient_login(api)
    response = api.client.get('/api/v1/patient/reports?page_size=2')
    assert response.json()['total'] == 3
    assert [row['report_id'] for row in response.json()['items']] == [4, 3]
    assert [row['report_id'] for row in api.client.get('/api/v1/patient/reports?page_size=2&page=2').json()['items']] == [1]
    assert api.client.get('/api/v1/patient/reports?search='+order_code).json()['total'] == 3


@pytest.mark.parametrize('path', ['/patient/reports/1', '/patient/reports/1/pdf'])
def test_portal_does_not_deliver_when_access_audit_fails(two_reports, path):
    api = two_reports
    patient_login(api)
    def fail(conn, cursor, statement, *args):
        if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic audit failure')
    event.listen(api.engine, 'before_cursor_execute', fail)
    try:
        response = api.client.get('/api/v1'+path)
        assert response.status_code == 503 and response.headers['content-type'] == 'application/json'
        assert not response.content.startswith(b'%PDF-')
    finally: event.remove(api.engine, 'before_cursor_execute', fail)


def test_status_reader_can_use_existing_account_read_permission(portal):
    with portal.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.user_id == 1, UserRole.role_id == 2))
        permission_id = db.scalar(select(Permission.permission_id).where(Permission.permission_code == 'ACCOUNT_READ'))
        db.add(RolePermission(role_id=1, permission_id=permission_id))
    assert call(portal, 'GET', '/patients/1/activation-status').status_code == 200
    assert call(portal, 'POST', '/patients/1/activation-token').status_code == 403
