"""Phase 3B HTTPS integration tests with synthetic identities and no network."""

import json

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import administration, patients, physicians, referring_facilities, staff
from app.cli import bootstrap_permissions
from app.models import (
    AuditLog, AuthSession, Patient, PatientAccountLink, Permission, Role,
    RolePermission, Staff, StaffAccountLink, UserAccount, UserRole,
)
from app.security.passwords import verify_password
from app.services.auth_service import utc_now
from app.services.permission_catalog import PERMISSION_CATALOG, ensure_permissions
from test_phase_3a_authentication_rbac import env, password_hash, login, csrf, count, PASSWORD

BASE = '/api/v1'
RESOURCES = [
    ('patients', 'patient_id', 'PATIENT', {'patient_code': 'P-SYNTH', 'first_name': '  Ana ', 'last_name': 'Example'}),
    ('staff', 'staff_id', 'STAFF', {'staff_code': 'S-SYNTH', 'first_name': '  Ana ', 'last_name': 'Example'}),
    ('referring-facilities', 'referring_facility_id', 'REFERRING_FACILITY', {'facility_name': '  Synthetic Clinic '}),
    ('physicians', 'physician_id', 'PHYSICIAN', {'first_name': '  Ana ', 'last_name': 'Example'}),
]


@pytest.fixture
def api(env, monkeypatch):
    for module in (patients, staff, physicians, referring_facilities, administration):
        env.app.include_router(module.router, prefix=BASE)
    monkeypatch.setattr(bootstrap_permissions, 'SessionLocal', env.factory)
    with env.factory.begin() as db:
        ensure_permissions(db)
        db.add(Role(role_id=2, role_code='SYSTEM_ADMIN', role_name='Administrator', is_active=True))
        db.add(Role(role_id=3, role_code='INACTIVE_ROLE', role_name='Inactive', is_active=False))
        db.add(Role(role_id=4, role_code='EMPTY_ROLE', role_name='Empty', is_active=True))
        db.add(UserAccount(user_id=2, username='second', password_hash=db.get(UserAccount, 1).password_hash,
                           account_status='ACTIVE'))
        db.add(Staff(staff_id=1, staff_code='S-ACCOUNT', first_name='Synthetic', last_name='Staff'))
    return env


@pytest.fixture
def admin(api):
    with api.factory.begin() as db:
        db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    assert login(api).status_code == 200
    return api


def request(api, method, path, payload=None):
    return api.client.request(method, BASE + path, json=payload, headers=csrf(api))


def grant(api, *codes):
    with api.factory.begin() as db:
        for code in codes:
            permission = db.scalar(select(Permission).where(Permission.permission_code == code))
            db.add(RolePermission(role_id=1, permission_id=permission.permission_id))


ENDPOINTS = []
for path, key, prefix, body in RESOURCES:
    ENDPOINTS.extend([
        ('POST', f'/{path}', body, f'{prefix}_CREATE'),
        ('GET', f'/{path}', None, f'{prefix}_READ'),
        ('GET', f'/{path}/999', None, f'{prefix}_READ'),
        ('PATCH', f'/{path}/999', {}, f'{prefix}_UPDATE'),
    ])
ENDPOINTS += [
    ('POST', '/staff/1/account', {'username': 'created', 'password': PASSWORD, 'role_codes': []}, 'ACCOUNT_CREATE'),
    ('GET', '/users', None, 'ACCOUNT_READ'), ('GET', '/users/2', None, 'ACCOUNT_READ'),
    ('PATCH', '/users/2/status', {'account_status': 'LOCKED'}, 'ACCOUNT_STATUS_UPDATE'),
    ('PUT', '/users/2/roles', {'role_codes': []}, 'ROLE_ASSIGN'),
    ('GET', '/roles', None, 'ROLE_READ'), ('GET', '/permissions', None, 'ROLE_READ'),
]


@pytest.mark.parametrize('method,path,body,permission', ENDPOINTS)
def test_each_route_requires_session_permission_and_csrf(api, method, path, body, permission):
    assert api.client.request(method, BASE + path, json=body).status_code == 401
    assert login(api).status_code == 200
    assert request(api, method, path, body).status_code == 403
    grant(api, permission)
    if method not in {'GET'}:
        assert api.client.request(method, BASE + path, json=body).status_code == 403
    response = request(api, method, path, body)
    assert response.status_code in {200, 201, 404}, response.text
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('path,key,prefix,body', RESOURCES)
def test_identity_lifecycle_and_audit(admin, path, key, prefix, body):
    response = request(admin, 'POST', f'/{path}', body)
    assert response.status_code == 201, response.text
    created = response.json()
    record_id = created[key]
    name = 'facility_name' if path == 'referring-facilities' else 'first_name'
    assert created[name] == body[name].strip()
    assert request(admin, 'GET', f'/{path}/{record_id}').json() == created
    update = {name: ' Revised Name ', 'contact_number': ' Synthetic private contact '}
    response = request(admin, 'PATCH', f'/{path}/{record_id}', update)
    assert response.status_code == 200
    assert response.json()[name] == 'Revised Name'
    assert response.json()['contact_number'] == 'Synthetic private contact'
    if 'last_name' in body:
        assert response.json()['last_name'] == body['last_name']
    response = request(admin, 'PATCH', f'/{path}/{record_id}', {'contact_number': None})
    assert response.json()['contact_number'] is None
    assert request(admin, 'DELETE', f'/{path}/{record_id}').status_code == 405
    assert request(admin, 'GET', f'/{path}/999').status_code == 404
    assert request(admin, 'PATCH', f'/{path}/999', {}).status_code == 404
    if path in {'staff', 'physicians'}:
        assert request(admin, 'PATCH', f'/{path}/{record_id}', {'is_active': False}).json()['is_active'] is False
        result = request(admin, 'GET', f'/{path}?is_active=false').json()
        assert result['total'] == 1 and result['items'][0][key] == record_id
    with admin.factory() as db:
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action.like(prefix + '_%')).order_by(AuditLog.audit_id)))
        assert logs[0].action == prefix + '_CREATE'
        assert logs[1].action == prefix + '_UPDATE'
        assert logs[1].new_value == {'changed_fields': ['contact_number', name]}
        assert all(log.user_id == 1 and log.record_id == record_id and log.created_at and log.ip_address == '192.0.2.10' for log in logs)
        encoded = json.dumps([log.new_value for log in logs])
        assert 'Revised Name' not in encoded and 'private contact' not in encoded
        assert all(log.old_value is None for log in logs)


@pytest.mark.parametrize('path,key,prefix,body', RESOURCES)
def test_paginated_search_filters_and_ordering(admin, path, key, prefix, body):
    for i in range(3):
        values = dict(body)
        if path == 'referring-facilities':
            values['facility_name'] = f'Synthetic Facility {i}'
        else:
            values.update(first_name=f'Synthetic{i}', middle_name='Middlematch', last_name='UniqueSurname')
            if path != 'physicians':
                values[f'{path.rstrip("s")}_code' if path == 'patients' else 'staff_code'] = f'CODE-{i}'
            else:
                values['license_number'] = f'LICENSE-{i}'
        assert request(admin, 'POST', '/' + path, values).status_code == 201
    result = request(admin, 'GET', f'/{path}?search=Synthetic&page_size=2').json()
    assert len(result['items']) == 2 and result['total'] == (4 if path == 'staff' else 3)
    assert result['page'] == 1 and result['page_size'] == 2
    next_page = request(admin, 'GET', f'/{path}?search=Synthetic&page_size=2&page=2').json()
    assert result['items'][-1][key] < next_page['items'][0][key]
    assert request(admin, 'GET', f'/{path}?page=999').json()['items'] == []
    assert request(admin, 'GET', f'/{path}?search=%25').json()['total'] == 0
    for query in ('page=0', 'page_size=0', 'page_size=101', 'page=bad'):
        assert request(admin, 'GET', f'/{path}?{query}').status_code == 422
    if path != 'referring-facilities':
        for term in ('Synthetic1', 'Middlematch', 'UniqueSurname'):
            assert request(admin, 'GET', f'/{path}?search={term}').json()['total'] >= 1
        if path == 'physicians':
            assert request(admin, 'GET', f'/{path}?search=LICENSE-1').json()['total'] == 1
        else:
            code_key = 'patient_code' if path == 'patients' else 'staff_code'
            assert request(admin, 'GET', f'/{path}?{code_key}=CODE-1').json()['total'] == 1
            assert request(admin, 'GET', f'/{path}?search=CODE-1').json()['total'] == 1


@pytest.mark.parametrize('path,key,prefix,body', RESOURCES[:2])
def test_duplicate_codes_create_and_patch_rollback(admin, path, key, prefix, body):
    first = request(admin, 'POST', '/' + path, body).json()
    assert request(admin, 'POST', '/' + path, body).status_code == 409
    code = 'patient_code' if path == 'patients' else 'staff_code'
    second = request(admin, 'POST', '/' + path, {**body, code: 'SECOND'}).json()
    response = request(admin, 'PATCH', f'/{path}/{second[key]}', {code: first[code], 'first_name': 'Must rollback'})
    assert response.status_code == 409
    assert request(admin, 'GET', f'/{path}/{second[key]}').json()['first_name'] == 'Ana'


@pytest.mark.parametrize('path,key,prefix,body', RESOURCES)
def test_input_allowlists_required_nulls_and_lengths(admin, path, key, prefix, body):
    for field in (key, 'created_at', 'updated_at', 'age', 'password', 'password_hash'):
        response = request(admin, 'POST', '/' + path, {**body, field: PASSWORD})
        assert response.status_code == 422 and PASSWORD not in response.text
        assert request(admin, 'PATCH', f'/{path}/1', {field: PASSWORD}).status_code == 422
    field = 'facility_name' if path == 'referring-facilities' else 'first_name'
    for value in (None, '', '  ', 'a' * 151):
        assert request(admin, 'POST', '/' + path, {**body, field: value}).status_code == 422
        assert request(admin, 'PATCH', f'/{path}/1', {field: value}).status_code == 422


@pytest.mark.parametrize('path', ['patients', 'staff'])
def test_email_validation_and_optional_values(admin, path):
    body = dict(RESOURCES[0 if path == 'patients' else 1][3])
    for email in ('bad', '', 'a@@example.com', 'name with spaces@example.com'):
        assert request(admin, 'POST', '/' + path, {**body, 'email': email}).status_code == 422
    response = request(admin, 'POST', '/' + path, {**body, 'email': ' synthetic@example.com '})
    assert response.status_code == 201 and response.json()['email'] == 'synthetic@example.com'


def test_patient_sex_birth_date_and_no_activation(admin):
    for sex in ('m', 'FEMALE', 'OTHER', ' M ', 'ANY'):
        assert request(admin, 'POST', '/patients', {**RESOURCES[0][3], 'sex': sex}).status_code == 422
    for i, sex in enumerate(('M', 'F', 'Other')):
        response = request(admin, 'POST', '/patients', {**RESOURCES[0][3], 'patient_code': str(i), 'sex': sex, 'birth_date': '2000-02-29'})
        assert response.status_code == 201 and 'age' not in response.json()
        assert request(admin, 'GET', f'/patients?sex={sex}').json()['total'] == 1
    assert request(admin, 'POST', '/patients/1/account', {}).status_code == 404
    with admin.factory() as db:
        assert count(db, PatientAccountLink) == 0


def test_physician_facility_relationship(admin):
    facility = request(admin, 'POST', '/referring-facilities', {'facility_name': 'Synthetic'}).json()
    fid = facility['referring_facility_id']
    body = {'first_name': 'Synthetic', 'last_name': 'Physician', 'referring_facility_id': fid}
    response = request(admin, 'POST', '/physicians', body)
    assert response.status_code == 201
    pid = response.json()['physician_id']
    assert request(admin, 'GET', f'/physicians?referring_facility_id={fid}').json()['total'] == 1
    assert request(admin, 'POST', '/physicians', {**body, 'referring_facility_id': 999}).status_code == 422
    assert request(admin, 'PATCH', f'/physicians/{pid}', {'referring_facility_id': 999}).status_code == 422
    assert request(admin, 'GET', f'/physicians/{pid}').json()['referring_facility_id'] == fid
    assert request(admin, 'PATCH', f'/physicians/{pid}', {'referring_facility_id': None}).json()['referring_facility_id'] is None


def account_payload(**changes):
    return {'username': 'new-staff', 'password': PASSWORD, 'role_codes': ['LAB_STAFF'], **changes}


def test_staff_account_success_safe_metadata_links_and_hash(admin, caplog):
    response = request(admin, 'POST', '/staff/1/account', account_payload(role_codes=['LAB_STAFF', 'LAB_STAFF']))
    assert response.status_code == 201, response.text
    result = response.json()
    uid = result['user_id']
    assert result['account_status'] == 'ACTIVE' and result['roles'] == ['LAB_STAFF']
    assert result['staff']['staff_id'] == 1 and result['patient'] is None
    with admin.factory() as db:
        user = db.get(UserAccount, uid)
        assert verify_password(PASSWORD, user.password_hash) and user.password_hash.startswith('$argon2id$')
        assert db.get(StaffAccountLink, 1).user_id == uid
        assert len(user.user_roles) == 1
        assert user.user_roles[0].assigned_by == 1 and user.user_roles[0].assigned_at
        audit = db.scalar(select(AuditLog).where(AuditLog.action == 'STAFF_ACCOUNT_CREATE'))
        assert audit.record_id == uid and audit.new_value == {'staff_id': 1, 'role_ids': [1]}
        private = [PASSWORD, user.password_hash, 'password_hash', 'token_hash', 'csrf_token_hash']
    texts = response.text + caplog.text
    for path in ('/users', f'/users/{uid}'):
        response = request(admin, 'GET', path)
        assert response.status_code == 200
        texts += response.text
    assert all(secret not in texts for secret in private)
    assert request(admin, 'POST', '/staff/1/account', account_payload(username='different')).status_code == 409


@pytest.mark.parametrize('change,status', [
    ({'username': 'tester'}, 409), ({'role_codes': ['UNKNOWN']}, 422),
    ({'role_codes': ['INACTIVE_ROLE']}, 422), ({'role_codes': ['lab_staff']}, 422),
    ({'password': 'short'}, 422), ({'password': PASSWORD * 100}, 422),
    ({'password_hash': 'forbidden'}, 422), ({'role_codes': ['SYSTEM_ADMIN'], 'assigned_by': 2}, 422),
])
def test_failed_staff_accounts_leave_no_partial_records(admin, change, status):
    response = request(admin, 'POST', '/staff/1/account', account_payload(**change))
    assert response.status_code == status, response.text
    with admin.factory() as db:
        assert count(db, UserAccount) == 2 and count(db, StaffAccountLink) == 0
        assert count(db, UserRole) == 2
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'STAFF_ACCOUNT_CREATE')) is None


def test_inactive_and_missing_staff(admin):
    assert request(admin, 'POST', '/staff/999/account', account_payload()).status_code == 404
    assert request(admin, 'PATCH', '/staff/1', {'is_active': False}).status_code == 200
    assert request(admin, 'POST', '/staff/1/account', account_payload()).status_code == 409


@pytest.mark.parametrize('failure_model', [StaffAccountLink, UserRole, AuditLog])
def test_staff_account_database_failure_is_atomic_and_private(admin, failure_model, caplog):
    def fail(session, *_):
        if any(isinstance(row, failure_model) for row in session.new):
            raise SQLAlchemyError('synthetic private failure')
    event.listen(admin.factory, 'before_flush', fail)
    try:
        response = request(admin, 'POST', '/staff/1/account', account_payload())
    finally:
        event.remove(admin.factory, 'before_flush', fail)
    assert response.status_code == 503 and 'private' not in response.text + caplog.text
    with admin.factory() as db:
        assert count(db, UserAccount) == 2 and count(db, StaffAccountLink) == 0
        assert count(db, UserRole) == 2
        assert count(db, AuditLog) == 1  # only administrator login


@pytest.mark.parametrize('status', ['INACTIVE', 'LOCKED'])
def test_disable_revokes_all_sessions_and_reactivation_does_not_restore_them(admin, status):
    admin.client.cookies.clear()
    assert login(admin, username='second').status_code == 200
    first_session = dict(admin.client.cookies)
    admin.client.cookies.clear()
    admin.client.cookies.clear()
    assert login(admin, username='second').status_code == 200
    admin.client.cookies.clear()
    assert login(admin).status_code == 200
    response = request(admin, 'PATCH', '/users/2/status', {'account_status': status})
    assert response.status_code == 200 and response.json()['account_status'] == status
    with admin.factory() as db:
        sessions = list(db.scalars(select(AuthSession).where(AuthSession.user_id == 2)))
        assert len(sessions) == 2 and all(row.revoked_at for row in sessions)
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == 1)).revoked_at is None
        log = db.scalar(select(AuditLog).where(AuditLog.action == 'ACCOUNT_STATUS_UPDATE'))
        assert log.old_value == {'account_status': 'ACTIVE'} and log.new_value == {'account_status': status}
    assert request(admin, 'PATCH', '/users/2/status', {'account_status': 'ACTIVE'}).status_code == 200
    admin.client.cookies.clear()
    admin.client.cookies.update(first_session)
    assert admin.client.get(BASE + '/auth/me').status_code == 401


def test_role_discovery_replacement_assignment_and_live_auth(admin):
    assert len(request(admin, 'GET', '/roles').json()) == 4
    permissions = request(admin, 'GET', '/permissions').json()
    assert {p['permission_code'] for p in permissions} == {'TEST_READ'} | {row[0] for row in PERMISSION_CATALOG}
    assert all(p['permission_name'] and p['description'] for p in permissions if p['permission_code'] != 'TEST_READ')
    response = request(admin, 'PUT', '/users/2/roles', {'role_codes': ['LAB_STAFF', 'EMPTY_ROLE', 'LAB_STAFF']})
    assert response.status_code == 200 and response.json()['roles'] == ['EMPTY_ROLE', 'LAB_STAFF']
    with admin.factory() as db:
        rows = list(db.scalars(select(UserRole).where(UserRole.user_id == 2)))
        assert len(rows) == 2 and all(row.assigned_by == 1 and row.assigned_at for row in rows)
    for role in ('INACTIVE_ROLE', 'UNKNOWN'):
        assert request(admin, 'PUT', '/users/2/roles', {'role_codes': [role]}).status_code == 422
    assert request(admin, 'GET', '/users/2').json()['roles'] == ['EMPTY_ROLE', 'LAB_STAFF']
    assert request(admin, 'PUT', '/users/2/roles', {'role_codes': []}).json()['roles'] == []
    assert request(admin, 'PUT', '/users/999/roles', {'role_codes': []}).status_code == 404
    assert request(admin, 'PATCH', '/users/999/status', {'account_status': 'ACTIVE'}).status_code == 404
    assert request(admin, 'PATCH', '/users/2/status', {'account_status': 'DISABLED'}).status_code == 422


@pytest.mark.parametrize('operation', ['disable', 'lock', 'remove'])
def test_last_active_admin_protection(admin, operation):
    method, path, payload = ('PUT', '/users/1/roles', {'role_codes': []}) if operation == 'remove' else (
        'PATCH', '/users/1/status', {'account_status': 'LOCKED' if operation == 'lock' else 'INACTIVE'})
    assert request(admin, method, path, payload).status_code == 409
    with admin.factory.begin() as db:
        db.add(UserRole(user_id=2, role_id=2, assigned_at=utc_now()))
        db.get(UserAccount, 2).account_status = 'LOCKED'
    assert request(admin, method, path, payload).status_code == 409
    with admin.factory.begin() as db:
        db.get(UserAccount, 2).account_status = 'ACTIVE'
    assert request(admin, method, path, payload).status_code == 200
    assert admin.client.get(BASE + '/auth/me').status_code == (200 if operation == 'remove' else 401)
    if operation == 'remove':
        assert request(admin, 'GET', '/users').status_code == 403


@pytest.mark.parametrize('operation', ['status', 'roles', 'patient'])
def test_audit_failure_rolls_back_mutation_and_revocation(admin, operation):
    admin.client.cookies.clear()
    assert login(admin, username='second').status_code == 200
    admin.client.cookies.clear()
    assert login(admin).status_code == 200
    def fail(session, *_):
        if any(isinstance(row, AuditLog) for row in session.new):
            raise SQLAlchemyError('synthetic private audit failure')
    event.listen(admin.factory, 'before_flush', fail)
    try:
        if operation == 'status':
            response = request(admin, 'PATCH', '/users/2/status', {'account_status': 'LOCKED'})
        elif operation == 'roles':
            response = request(admin, 'PUT', '/users/1/roles', {'role_codes': ['SYSTEM_ADMIN']})
        else:
            response = request(admin, 'POST', '/patients', RESOURCES[0][3])
    finally:
        event.remove(admin.factory, 'before_flush', fail)
    assert response.status_code == 503
    with admin.factory() as db:
        assert db.get(UserAccount, 2).account_status == 'ACTIVE'
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == 2)).revoked_at is None
        assert len(db.get(UserAccount, 1).user_roles) == 2
        assert count(db, Patient) == 0


def test_role_assignment_cannot_escalate_and_account_creation_cannot_bypass_it(api):
    assert login(api).status_code == 200
    grant(api, 'ACCOUNT_CREATE')
    assert request(api, 'POST', '/staff/1/account', account_payload()).status_code == 403
    grant(api, 'ROLE_ASSIGN')
    assert request(api, 'PUT', '/users/1/roles', {'role_codes': ['SYSTEM_ADMIN']}).status_code == 403
    assert request(api, 'POST', '/staff/1/account', account_payload(role_codes=['SYSTEM_ADMIN'])).status_code == 403
    with api.factory.begin() as db:
        permission = db.scalar(select(Permission).where(Permission.permission_code == 'ACCOUNT_STATUS_UPDATE'))
        db.add(RolePermission(role_id=4, permission_id=permission.permission_id))
    assert request(api, 'PUT', '/users/1/roles', {'role_codes': ['EMPTY_ROLE']}).status_code == 403
    assert request(api, 'POST', '/staff/1/account', account_payload(role_codes=['EMPTY_ROLE'])).status_code == 403
    # A delegated administrator may assign a role whose authority they already hold.
    assert request(api, 'PUT', '/users/2/roles', {'role_codes': ['LAB_STAFF']}).status_code == 200


def test_nonadmin_cannot_manage_administrator_target(api):
    with api.factory.begin() as db:
        db.add(UserRole(user_id=2, role_id=2, assigned_at=utc_now()))
    grant(api, 'ROLE_ASSIGN', 'ACCOUNT_STATUS_UPDATE')
    assert login(api).status_code == 200
    assert request(api, 'PUT', '/users/2/roles', {'role_codes': []}).status_code == 403
    assert request(api, 'PATCH', '/users/2/status', {'account_status': 'LOCKED'}).status_code == 403


def test_bootstrap_idempotent_preserves_metadata_and_assignments(api, capsys):
    with api.factory.begin() as db:
        permission = db.scalar(select(Permission).where(Permission.permission_code == 'PATIENT_READ'))
        permission.permission_name = 'Custom metadata'
        permission.description = 'Preserve me'
        assert ensure_permissions(db) == []
        db.delete(db.scalar(select(Permission).where(Permission.permission_code == 'ROLE_ASSIGN')))
    bootstrap_permissions.main()
    bootstrap_permissions.main()
    assert 'created 1 permission(s)' in capsys.readouterr().out
    with api.factory() as db:
        assert count(db, Permission) == len(PERMISSION_CATALOG) + 1 and count(db, RolePermission) == 1
        permission = db.scalar(select(Permission).where(Permission.permission_code == 'PATIENT_READ'))
        assert permission.permission_name == 'Custom metadata' and permission.description == 'Preserve me'


def test_bootstrap_failure_safe(api, capsys):
    with api.factory.begin() as db:
        db.delete(db.scalar(select(Permission).where(Permission.permission_code == 'ROLE_ASSIGN')))
    def fail(*args):
        raise SQLAlchemyError('synthetic private database error')
    event.listen(api.factory, 'before_flush', fail)
    try:
        with pytest.raises(SystemExit) as result:
            bootstrap_permissions.main()
    finally:
        event.remove(api.factory, 'before_flush', fail)
    assert result.value.code == 1 and 'private' not in capsys.readouterr().err


def test_invalid_account_json_never_echoes_secret(admin, caplog):
    response = admin.client.post(BASE + '/staff/1/account', content='{"password":"' + PASSWORD,
                                 headers={**csrf(admin), 'content-type': 'application/json'})
    assert response.status_code == 422 and PASSWORD not in response.text + caplog.text
    assert 'input' not in response.text


def test_users_pagination_and_no_credentials(admin):
    result = request(admin, 'GET', '/users?page_size=1').json()
    assert result['total'] == 2 and len(result['items']) == 1
    assert request(admin, 'GET', '/users?search=second').json()['items'][0]['user_id'] == 2
    assert request(admin, 'GET', '/users?account_status=LOCKED').json()['total'] == 0
    assert request(admin, 'GET', '/users?page_size=101').status_code == 422


def test_openapi_contract_and_migration_chain():
    from app.main import app
    from alembic.script import ScriptDirectory
    from test_phase_2a_migration import config, HEAD
    schema = app.openapi()
    assert set(schema['paths']['/api/v1/patients']) == {'get', 'post'}
    assert set(schema['paths']['/api/v1/patients/{patient_id}']) == {'get', 'patch'}
    for path, _, _, _ in RESOURCES:
        assert schema['paths'][BASE + '/' + path]['get']['tags']
    assert 'password_hash' not in json.dumps(schema)
    assert '/api/v1/patients/{patient_id}/account' not in schema['paths']
    assert ScriptDirectory.from_config(config()).get_heads() == [HEAD]
    assert len(list(ScriptDirectory.from_config(config()).walk_revisions())) == 7


def test_account_patient_summary_is_read_only_and_minimal(admin):
    with admin.factory.begin() as db:
        db.add(Patient(patient_id=1, patient_code='SYNTH-LINK', first_name='Synthetic',
                       last_name='Linked', email='private@example.com', address='Private address'))
        db.flush()
        db.add(PatientAccountLink(patient_id=1, user_id=2))
    for path in ('/users/2', '/users?search=second'):
        response = request(admin, 'GET', path)
        assert response.status_code == 200
        result = response.json() if path == '/users/2' else response.json()['items'][0]
        assert result['patient'] == {'patient_id': 1, 'patient_code': 'SYNTH-LINK',
                                     'first_name': 'Synthetic', 'middle_name': None, 'last_name': 'Linked'}
        assert 'private' not in response.text.lower()
    with admin.factory() as db:
        assert count(db, PatientAccountLink) == 1


def test_audit_values_never_contain_identity_values_or_auth_secrets(admin, caplog):
    response = request(admin, 'POST', '/staff/1/account', account_payload())
    uid = response.json()['user_id']
    assert request(admin, 'PUT', f'/users/{uid}/roles', {'role_codes': []}).status_code == 200
    assert request(admin, 'PATCH', f'/users/{uid}/status', {'account_status': 'LOCKED'}).status_code == 200
    assert request(admin, 'POST', '/patients', {**RESOURCES[0][3], 'email': 'private-patient@example.com'}).status_code == 201
    with admin.factory() as db:
        logs = list(db.scalars(select(AuditLog)))
        serialized = json.dumps([{'old': row.old_value, 'new': row.new_value} for row in logs])
        session = db.scalar(select(AuthSession))
        secrets = [PASSWORD, db.get(UserAccount, uid).password_hash, session.token_hash,
                   session.csrf_token_hash, 'private-patient@example.com', 'P-SYNTH']
    secrets.extend(admin.client.cookies.values())
    assert all(secret not in serialized + caplog.text for secret in secrets)


def test_role_replacement_overwrites_provenance_and_empty_patch_preserves_data(admin):
    with admin.factory.begin() as db:
        db.add(UserRole(user_id=2, role_id=1, assigned_by=2, assigned_at=utc_now()))
    assert request(admin, 'PUT', '/users/2/roles', {'role_codes': ['LAB_STAFF']}).status_code == 200
    with admin.factory() as db:
        rows = list(db.scalars(select(UserRole).where(UserRole.user_id == 2)))
        assert len(rows) == 1 and rows[0].assigned_by == 1
    before = request(admin, 'GET', '/staff/1').json()
    assert request(admin, 'PATCH', '/staff/1', {}).json() == before
    with admin.factory() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'STAFF_UPDATE')).new_value == {'changed_fields': []}
