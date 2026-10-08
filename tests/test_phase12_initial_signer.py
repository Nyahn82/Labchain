"""Local SQLite plus fake API only; no provisioning against production."""
from copy import deepcopy
from datetime import timedelta
from http.cookiejar import Cookie, CookieJar
import json

import pytest
from sqlalchemy import select

from app.models import AuthSession, Permission, Role, RolePermission, Signatory, Staff, StaffAccountLink, UserAccount, UserRole
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from scripts import phase12_initial_signer_setup as setup
from scripts import phase9_e2e_validation as e2e
from test_phase12_rbac_matrix import factory, grant, snapshot
from test_phase9_signer_setup import API, Identity, CREATED, OPERATOR, SECRET, writes


@pytest.fixture
def ready(factory):
    grant(factory, 'LAB_SIGNER', 'REPORT_SIGN')
    with factory.begin() as db:
        db.add(Staff(staff_id=1, staff_code='P9SIGN01', first_name='Phase', last_name='Nine', is_active=True))
        db.add(UserAccount(user_id=20, username='operator', password_hash='synthetic', account_status='ACTIVE'))
        db.flush()
        db.add(Signatory(signatory_id=1, staff_id=1, is_active=True))
        rid = db.scalar(select(Role.role_id).where(Role.role_code == 'SYSTEM_ADMIN'))
        db.add(UserRole(user_id=20, role_id=rid, assigned_at=utc_now()))
        db.add(AuthSession(user_id=20, token_hash=hash_token('synthetic-cookie'), csrf_token_hash=hash_token('synthetic-csrf'),
                           created_at=utc_now(), expires_at=utc_now() + timedelta(hours=1)))
    return factory


@pytest.fixture
def api(ready):
    from app.main import app
    api = API(app.openapi(), execute=True)
    api.inventory = [deepcopy(OPERATOR)]
    with ready() as db:
        api.roles = [{'role_id': r.role_id, 'role_code': r.role_code, 'is_active': r.is_active}
                     for r in db.scalars(select(Role))]
    api.jar = CookieJar()
    api.jar.set_cookie(Cookie(0, 'rhu_session', 'synthetic-cookie', None, False, 'labchain.online', False, False,
                             '/', True, True, None, True, None, None, {}, False))
    original = api.get
    def get(path):
        if path == '/signatories/1':
            return {'signatory_id': 1, 'staff_id': 1, 'is_active': True}
        return original(path)
    api.get = get
    return api


def proof(api, ready, monkeypatch):
    evidence, _ = setup.preflight(api, ready)
    monkeypatch.setattr(e2e, 'hidden_input', lambda _: SECRET)
    return evidence


def test_preflight_selects_only(ready, api, monkeypatch, tmp_path):
    before = snapshot(ready)
    monkeypatch.setattr(setup, 'SessionLocal', ready)
    monkeypatch.setattr(e2e, 'Client', lambda *a, **kw: api)
    monkeypatch.setattr(e2e, 'hidden_input', lambda _: 'operator')
    assert setup.main(['--intent-file', str(tmp_path / 'intent')]) == 0
    assert setup.parse_args([]).execute is False
    assert not writes(api) and not (tmp_path / 'intent').exists()
    assert snapshot(ready) == before


@pytest.mark.parametrize('change', ['missing_role', 'inactive_role', 'missing_permission', 'extra_permission',
    'staff_code', 'staff_inactive', 'signatory_staff', 'signatory_inactive', 'missing_signatory',
    'existing_link', 'username', 'normalized_username'])
def test_local_conflicts_refuse(ready, change):
    with ready.begin() as db:
        role = db.scalar(select(Role).where(Role.role_code == 'LAB_SIGNER'))
        if change in {'missing_role', 'missing_permission'}:
            for g in db.scalars(select(RolePermission).where(RolePermission.role_id == role.role_id)):
                db.delete(g)
            db.flush()
            if change == 'missing_role':
                db.delete(role)
            else:
                db.delete(db.scalar(select(Permission).where(Permission.permission_code == 'REPORT_SIGN')))
        elif change == 'inactive_role':
            role.is_active = False
        elif change == 'extra_permission':
            pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == 'REPORT_READ'))
            db.add(RolePermission(role_id=role.role_id, permission_id=pid))
        elif change == 'staff_code':
            db.get(Staff, 1).staff_code = 'OTHER'
        elif change == 'staff_inactive':
            db.get(Staff, 1).is_active = False
        elif change == 'signatory_staff':
            db.add(Staff(staff_id=2, staff_code='OTHER', first_name='Test', last_name='Other'))
            db.flush()
            db.get(Signatory, 1).staff_id = 2
        elif change == 'signatory_inactive':
            db.get(Signatory, 1).is_active = False
        elif change == 'missing_signatory':
            db.delete(db.get(Signatory, 1))
        elif change == 'existing_link':
            db.add(StaffAccountLink(staff_id=1, user_id=20))
        else:
            db.get(UserAccount, 20).username = 'p9signer' if change == 'username' else 'P9SÍGNER'
    before = snapshot(ready)
    with pytest.raises(e2e.ValidationError):
        setup.local_evidence(ready)
    assert snapshot(ready) == before


@pytest.mark.parametrize('flag', ['--password', '--username', '--operator-password', '--signer-password'])
def test_cli_credentials_rejected_without_echo(flag, capsys):
    with pytest.raises(SystemExit):
        setup.parse_args([flag, SECRET])
    assert SECRET not in capsys.readouterr().err


def test_wrong_database_session_refused(ready, api):
    api.jar.clear()
    with pytest.raises(e2e.ValidationError, match='cookie'):
        setup.preflight(api, ready)
    assert not writes(api)


def test_execute_gate(ready, api, tmp_path):
    api.execute = False
    with pytest.raises(e2e.ValidationError, match='--execute'):
        setup.execute(api, ready, {}, tmp_path / 'intent')
    assert not writes(api)


def test_password_mismatch_no_write(ready, api, monkeypatch, tmp_path):
    evidence = proof(api, ready, monkeypatch)
    answers = iter([SECRET, 'different'])
    monkeypatch.setattr(e2e, 'hidden_input', lambda _: next(answers))
    with pytest.raises(e2e.ValidationError, match='confirmation'):
        setup.execute(api, ready, evidence, tmp_path / 'intent')
    assert not writes(api)


def test_changed_state_after_prompt_no_write(ready, api, monkeypatch, tmp_path):
    evidence = proof(api, ready, monkeypatch)
    def prompt(_):
        with ready.begin() as db:
            db.get(Staff, 1).is_active = False
        return SECRET
    monkeypatch.setattr(e2e, 'hidden_input', prompt)
    with pytest.raises(e2e.ValidationError):
        setup.execute(api, ready, evidence, tmp_path / 'intent')
    assert not writes(api)


def test_exact_creation_one_post_and_safe_receipt(ready, api, monkeypatch, tmp_path, capsys):
    evidence = proof(api, ready, monkeypatch)
    before = snapshot(ready)
    path = tmp_path / 'intent.json'
    def posted():
        assert json.loads(path.read_text())['state'] == 'PENDING'
    api.before_post = posted
    assert setup.execute(api, ready, evidence, path, client_factory=lambda *a, **kw: Identity(CREATED)) == 22
    assert writes(api) == [('POST', '/api/v1/staff/1/account')]
    # Fake API simulates writes; the utility's SQL never changes any table.
    assert snapshot(ready) == before
    state = json.loads(path.read_text())
    assert state['state'] == 'VERIFIED' and state['user_id'] == 22
    assert set(state) == {'operation_id', 'timestamp', 'staff_id', 'staff_code', 'username', 'role_code', 'permissions', 'state', 'user_id'}
    assert path.stat().st_mode & 0o777 == 0o600
    assert SECRET not in path.read_text() + capsys.readouterr().out
    assert 'synthetic-cookie' not in path.read_text()


def test_uncertain_post_never_retried(ready, api, monkeypatch, tmp_path):
    evidence = proof(api, ready, monkeypatch)
    api.fail_create = True
    path = tmp_path / 'intent.json'
    with pytest.raises(e2e.ValidationError, match='not retried'):
        setup.execute(api, ready, evidence, path)
    assert json.loads(path.read_text())['state'] == 'PENDING'
    with pytest.raises(e2e.ValidationError, match='Existing intent'):
        setup.execute(api, ready, evidence, path)
    assert len(writes(api)) == 1


@pytest.mark.parametrize('change', ['admin', 'patient_role', 'patient_link', 'extra_permission', 'wrong_staff',
                                   'inactive', 'missing_permissions', 'duplicate_permissions', 'extra_role'])
def test_bad_result_stops_without_repair(ready, api, monkeypatch, tmp_path, change):
    evidence = proof(api, ready, monkeypatch)
    me = deepcopy(CREATED)
    if change == 'admin': me['roles'] = ['SYSTEM_ADMIN']
    elif change == 'patient_role': me['roles'] = ['PATIENT']
    elif change == 'patient_link': me['patient'] = {'patient_id': 1}
    elif change == 'extra_permission': me['permissions'].append('REPORT_READ')
    elif change == 'missing_permissions': me['permissions'] = []
    elif change == 'duplicate_permissions': me['permissions'] *= 2
    elif change == 'extra_role': me['roles'].append('LAB_STAFF')
    elif change == 'wrong_staff': me['staff']['staff_id'] = 2
    else: me['account_status'] = 'DISABLED'
    path = tmp_path / 'intent.json'
    with pytest.raises(e2e.ValidationError):
        setup.execute(api, ready, evidence, path, client_factory=lambda *a, **kw: Identity(me))
    assert len(writes(api)) == 1
    assert json.loads(path.read_text())['state'] == 'CREATED_UNVERIFIED'


def test_unexpected_exception_never_prints_secrets(ready, monkeypatch, capsys):
    def fail(*args, **kwargs): raise RuntimeError(SECRET)
    monkeypatch.setattr(setup, 'local_evidence', fail)
    assert setup.main([]) == 1
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize('change', ['session_missing', 'session_revoked', 'session_expired', 'local_authority', 'api_role_id', 'api_contract'])
def test_independent_api_local_evidence_failures(ready, api, change):
    with ready.begin() as db:
        session = db.scalar(select(AuthSession))
        if change == 'session_missing': db.delete(session)
        elif change == 'session_revoked': session.revoked_at = utc_now()
        elif change == 'session_expired': session.expires_at = utc_now() - timedelta(seconds=1)
        elif change == 'local_authority': db.get(UserAccount, 20).account_status = 'DISABLED'
    if change == 'api_role_id':
        next(r for r in api.roles if r['role_code'] == 'LAB_SIGNER')['role_id'] += 100
    elif change == 'api_contract':
        del api.spec['paths']['/api/v1/staff/{staff_id}/account']
    with pytest.raises(e2e.ValidationError):
        setup.preflight(api, ready)
    assert not writes(api)


def test_changed_grant_after_prompt_no_write(ready, api, monkeypatch, tmp_path):
    evidence = proof(api, ready, monkeypatch)
    calls = []
    def prompt(_):
        if not calls:
            grant(ready, 'LAB_SIGNER', 'REPORT_READ')
        calls.append(1)
        return SECRET
    monkeypatch.setattr(e2e, 'hidden_input', prompt)
    with pytest.raises(e2e.ValidationError, match='exactly REPORT_SIGN'):
        setup.execute(api, ready, evidence, tmp_path / 'intent')
    assert not writes(api)


@pytest.mark.parametrize('password', ['short', 'x' * 1025])
def test_password_length_refuses_no_write(ready, api, monkeypatch, tmp_path, password):
    evidence = proof(api, ready, monkeypatch)
    monkeypatch.setattr(e2e, 'hidden_input', lambda _: password)
    with pytest.raises(e2e.ValidationError, match='length'):
        setup.execute(api, ready, evidence, tmp_path / 'intent')
    assert not writes(api)
