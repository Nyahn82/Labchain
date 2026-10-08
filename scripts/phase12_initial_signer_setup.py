#!/usr/bin/env python3
"""One-purpose first p9signer bootstrap; local SQL is SELECT-only.

Default preflight makes no provisioning writes. API login has its normal
session/audit effects. Never run against production without separate approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import sys
import urllib.request
from uuid import uuid4

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import phase9_e2e_validation as e2e
from scripts import phase9_signer_setup as existing
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthSession, Permission, Role, RolePermission, Signatory, Staff, StaffAccountLink, UserAccount
from app.schemas.administration import StaffAccountCreate
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from app.services.rbac_service import get_user_permissions, get_user_roles

ROLE = 'LAB_SIGNER'
USERNAME = 'p9signer'
DEFAULT_INTENT = Path(__file__).resolve().parents[1] / '.phase9-runs' / 'phase12-initial-signer.json'


def local_evidence(factory, *, unused=True):
    """No flush/commit or ORM mutation; never return unrelated identity data."""
    with factory() as db:
        roles = list(db.scalars(select(Role).where(Role.role_code == ROLE)))
        e2e.require(len(roles) == 1 and roles[0].role_code == ROLE and roles[0].is_active,
                    'LAB_SIGNER is missing, ambiguous or inactive.')
        role = roles[0]
        permissions = list(db.execute(select(Permission.permission_id, Permission.permission_code)))
        sign = [(pid, code) for pid, code in permissions if code == 'REPORT_SIGN']
        e2e.require(len(sign) == 1, 'REPORT_SIGN must exist exactly once.')
        grants = list(db.execute(select(RolePermission.role_permission_id, RolePermission.permission_id)
                                .where(RolePermission.role_id == role.role_id)))
        e2e.require(len(grants) == 1 and grants[0].permission_id == sign[0][0],
                    'LAB_SIGNER must grant exactly REPORT_SIGN.')
        staff = db.get(Staff, 1)
        e2e.require(staff is not None and staff.staff_code == 'P9SIGN01' and staff.is_active,
                    'Synthetic staff 1/P9SIGN01 is missing, mismatched or inactive.')
        signatory = db.get(Signatory, 1)
        e2e.require(signatory is not None and signatory.staff_id == 1 and signatory.is_active,
                    'Active signatory 1 must belong to synthetic staff 1.')
        if unused:
            e2e.require(db.get(StaffAccountLink, 1) is None, 'Staff 1 already has an account link.')
            # SQL equality respects database collation; conservative normalization
            # also catches equivalent usernames in SQLite and API test environments.
            conflict = db.scalar(select(UserAccount.user_id).where(UserAccount.username == USERNAME))
            names = db.scalars(select(UserAccount.username))
            e2e.require(conflict is None and all(existing.canonical_username(n) != USERNAME for n in names),
                        'Username p9signer already exists; no retry or repair is allowed.')
        return {'role_id': role.role_id, 'permission_id': sign[0][0],
                'grant_id': grants[0].role_permission_id, 'staff_id': 1, 'staff_code': 'P9SIGN01',
                'signatory_id': 1}


def bind_api_to_local_database(factory, client, me):
    """Prove live API and local evidence refer to the same authenticated session.

    Matching public role/staff IDs alone cannot establish deployment identity.
    Cookie values/hashes remain in memory and are never output or receipted.
    """
    probe = urllib.request.Request(client.base + e2e.API + '/auth/me')
    client.jar.add_cookie_header(probe)
    cookies = SimpleCookie(probe.get_header('Cookie', ''))
    cookie = cookies.get(client.session_cookie)
    e2e.require(cookie is not None and cookie.value, 'Operator session cookie is unavailable.')
    with factory() as db:
        session = db.scalar(select(AuthSession).where(
            AuthSession.token_hash == hash_token(cookie.value), AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utc_now()))
        e2e.require(session is not None and session.user_id == me['user_id'],
                    'API session does not match the local database; no provisioning allowed.')
        user = db.get(UserAccount, session.user_id)
        e2e.require(user is not None and user.account_status == 'ACTIVE' and user.username == me.get('username')
                    and get_user_roles(db, user.user_id) == me.get('roles')
                    and get_user_permissions(db, user.user_id) == me.get('permissions'),
                    'Operator API/local authority differs; no provisioning allowed.')


def preflight(client, factory):
    proof = local_evidence(factory)
    me = e2e.obj(client.get('/auth/me'))
    operator_id = existing.operator_ready(me)
    e2e.require('PATIENT' not in me.get('roles', []) and me.get('patient') is None,
                'Operator must not be a patient identity.')
    e2e.require(e2e.permitted(me, {'SIGNATORY_READ'}), 'Operator requires signatory discovery authority.')
    bind_api_to_local_database(factory, client, me)
    schemas = existing.inspect_contract(client)
    inventory = existing.accounts(client)
    existing.available_target(client, inventory)
    roles = existing.roles_and_permissions(client)
    role = roles.get(ROLE)
    e2e.require(role is not None and role['is_active'] and role['role_id'] == proof['role_id'],
                'Live role metadata disagrees with local evidence.')
    e2e.matches(client.get('/signatories/1'), signatory_id=1, staff_id=1, is_active=True)
    return {**proof, 'operator_id': operator_id}, schemas


def check_account(body, operator_id, *, uid=None, effective=False):
    e2e.matches(body, username=USERNAME, account_status='ACTIVE', roles=[ROLE])
    current = e2e.identifier(body.get('user_id'))
    e2e.require(current != operator_id and (uid is None or current == uid), 'Signer user identity changed.')
    e2e.matches(body.get('staff'), staff_id=1, staff_code='P9SIGN01')
    e2e.require('patient' in body and body['patient'] is None, 'Signer must have no patient identity.')
    if effective:
        e2e.require(body.get('permissions') == ['REPORT_SIGN'], 'Signer must have exactly REPORT_SIGN.')
    return current


def execute(client, factory, evidence, intent_path, *, client_factory=None):
    e2e.require(client.execute, 'Initial signer provisioning requires --execute.')
    current, _ = preflight(client, factory)
    e2e.require(current == evidence, 'Preflight state changed; no account POST sent.')
    path = Path(intent_path)
    e2e.require(not path.exists() and not path.is_symlink(), 'Existing intent: reconcile; never retry an uncertain POST.')
    password = confirmation = payload = None
    try:
        password = e2e.hidden_input('New p9signer password (12–1024 characters): ')
        confirmation = e2e.hidden_input('Confirm new p9signer password: ')
        e2e.require(password == confirmation and 12 <= len(password) <= 1024,
                    'Password confirmation or length requirement failed; no account POST sent.')
        confirmation = None
        # Validate the local authoritative schema without printing validation errors.
        try:
            StaffAccountCreate(username=USERNAME, password=password, role_codes=[ROLE])
        except ValueError:
            raise e2e.ValidationError('Password/account schema validation failed; no account POST sent.') from None
        current, schemas = preflight(client, factory)
        e2e.require(current == evidence, 'Preflight state changed after password input; no account POST sent.')
        payload = {'username': USERNAME, 'password': password, 'role_codes': [ROLE]}
        e2e.validate_payload(payload, schemas['StaffAccountCreate'], schemas)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as receipt:
            state = {'operation_id': str(uuid4()), 'timestamp': datetime.now(timezone.utc).isoformat(),
                     'staff_id': 1, 'staff_code': 'P9SIGN01', 'username': USERNAME,
                     'role_code': ROLE, 'permissions': ['REPORT_SIGN'], 'state': 'PENDING'}

            def record():
                receipt.seek(0)
                json.dump(state, receipt, indent=2, sort_keys=True)
                receipt.truncate()
                receipt.flush()
                os.fsync(receipt.fileno())

            record()
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            # Exactly one application mutation. Transport, status and response
            # uncertainty leave the durable PENDING intent; never retry or repair.
            body = e2e.obj(client.request('POST', e2e.API + '/staff/1/account', payload, expected=(201,)))
            payload = None
            uid = check_account(body, evidence['operator_id'])
            state.update(state='CREATED_UNVERIFIED', user_id=uid)
            record()
            check_account(e2e.obj(client.get(f'/users/{uid}')), evidence['operator_id'], uid=uid)
            signer = (client_factory or e2e.Client)(client.base, session_cookie=client.session_cookie,
                                                    csrf_cookie=client.csrf_cookie)
            signer.login('Initial signer', username=USERNAME, password=password)
            password = None
            check_account(e2e.obj(signer.get('/auth/me')), evidence['operator_id'], uid=uid, effective=True)
            check_account(e2e.obj(client.get(f'/users/{uid}')), evidence['operator_id'], uid=uid)
            e2e.require(local_evidence(factory, unused=False) == {k: v for k, v in evidence.items() if k != 'operator_id'},
                        'Local signer grants or target changed; stop without repair.')
            state['state'] = 'VERIFIED'
            record()
            e2e.emit('PASS', f'Initial signer verified: user_id={uid}, LAB_SIGNER, REPORT_SIGN only, staff_id=1.')
            return uid
    finally:
        password = confirmation = payload = None


def parse_args(argv=None):
    # Suppress argparse's echo of unknown arguments: a mistaken --password must
    # not disclose its value to terminal logs even though it is unsupported.
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, 'Invalid arguments; credentials must use hidden prompts.\n')
    parser = Parser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--base-url', default=e2e.BASE)
    parser.add_argument('--intent-file', type=Path, default=DEFAULT_INTENT)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        # Fail cheap local checks before asking for credentials or making API calls.
        local_evidence(SessionLocal)
        client = e2e.Client(args.base_url, execute=args.execute)
        username = e2e.hidden_input('Operator username (hidden): ').strip()
        client.login('Operator', username=username)
        proof, _ = preflight(client, SessionLocal)
        if args.execute:
            execute(client, SessionLocal, proof, args.intent_file)
        else:
            e2e.emit('PASS', 'PREFLIGHT_ONLY: local/API evidence passed; no provisioning writes. Login has normal session/audit effects.')
        return 0
    except e2e.ValidationError as exc:
        e2e.emit('FAIL', str(exc))
    except FileExistsError:
        e2e.emit('FAIL', 'Intent already exists; reconcile the earlier operation. No POST retried.')
    except (Exception, KeyboardInterrupt):
        e2e.emit('FAIL', 'Stopped; private details withheld. Reconcile any intent before continuing; no POST retried.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
