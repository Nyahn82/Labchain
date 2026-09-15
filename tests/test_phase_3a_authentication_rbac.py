"""Network-blocked HTTPS integration tests with synthetic SQLite data only.

SQLite needs INTEGER primary keys for generated IDs. Only a copied test schema
uses those types; frozen migrations and MySQL BIGINT DDL are tested separately.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Integer, MetaData, create_engine, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api.auth import router
from app.cli import bootstrap_admin, bootstrap_roles
from app.config import Settings, settings
from app.dependencies import auth as dependencies
from app.models import (
    AuditLog, AuthSession, Base, LoginLog, Patient, PatientAccountLink, Permission,
    Role, RolePermission, Staff, StaffAccountLink, UserAccount, UserRole,
)
from app.schemas.auth import LoginRequest
from app.security import passwords
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from app.services.rbac_service import ensure_core_roles

PASSWORD = "Synthetic-password-123!"


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def env(tmp_path, monkeypatch, password_hash):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.sqlite'}", hide_parameters=True)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        clone = table.to_metadata(metadata)
        for column in clone.primary_key:
            if column.autoincrement is True:
                column.type = Integer()
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(dependencies, "SessionLocal", factory)
    monkeypatch.setattr(bootstrap_admin, "SessionLocal", factory)
    monkeypatch.setattr(bootstrap_roles, "SessionLocal", factory)
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1")

    @test_app.api_route("/role", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    def role_probe(user=Depends(dependencies.require_role("LAB_STAFF"))):
        return {"user_id": user.user_id}

    @test_app.api_route("/permission", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    def permission_probe(user=Depends(dependencies.require_permission("TEST_READ"))):
        return {"user_id": user.user_id}

    @test_app.post("/user")
    def user_probe(user=Depends(dependencies.get_current_user)):
        return {"user_id": user.user_id}

    @test_app.get("/alternative-role")
    def alternative_role(user=Depends(dependencies.require_role("DOCTOR", "LAB_STAFF"))):
        return {"user_id": user.user_id}

    @test_app.get("/alternative-permission")
    def alternative_permission(user=Depends(dependencies.require_permission("MISSING", "TEST_READ"))):
        return {"user_id": user.user_id}

    with factory.begin() as db:
        db.add(UserAccount(user_id=1, username="tester", password_hash=password_hash, account_status="ACTIVE"))
        db.add(Role(role_id=1, role_code="LAB_STAFF", role_name="Lab Staff", is_active=True))
        db.add(Permission(permission_id=1, permission_code="TEST_READ", permission_name="Test Read"))
        db.flush()
        db.add(UserRole(user_role_id=1, user_id=1, role_id=1, assigned_at=utc_now()))
        db.add(RolePermission(role_permission_id=1, role_id=1, permission_id=1))
    with TestClient(test_app, base_url="https://testserver", client=("192.0.2.10", 12345)) as client:
        yield SimpleNamespace(client=client, factory=factory, engine=engine, app=test_app)
    engine.dispose()


def login(env, username="tester", password=PASSWORD, **kwargs):
    return env.client.post("/api/v1/auth/login", json={"username": username, "password": password}, **kwargs)


def csrf(env):
    return {"X-CSRF-Token": env.client.cookies[settings.auth_csrf_cookie_name]}


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_argon2id_password_security(password_hash):
    assert password_hash != PASSWORD
    assert password_hash.startswith("$argon2id$")
    assert "m=65536,t=3,p=4" in password_hash
    assert verify_password(PASSWORD, password_hash)
    assert not verify_password("wrong", password_hash)
    assert not verify_password(PASSWORD, None)
    assert not verify_password(PASSWORD, "broken-hash")
    assert hash_password(PASSWORD) != password_hash  # random salt


def test_unknown_user_performs_password_verification(monkeypatch):
    verifier = Mock(return_value=True)
    monkeypatch.setattr(passwords, "_hasher", SimpleNamespace(verify=verifier))
    assert not verify_password("anything", None)
    assert verifier.call_args.args[0].startswith("$argon2id$")


def test_login_cookies_hashes_logs_and_expiry(env, password_hash, caplog):
    response = login(env, username="  tester  ", headers={"user-agent": "x" * 400})
    assert response.status_code == 200
    assert response.json() == {"user_id": 1, "username": "tester", "account_status": "ACTIVE", "roles": ["LAB_STAFF"]}
    assert response.headers["cache-control"] == "no-store"
    session_token = response.cookies[settings.auth_session_cookie_name]
    csrf_token = response.cookies[settings.auth_csrf_cookie_name]
    assert session_token != csrf_token and len(session_token) == 43
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    for cookie in cookies:
        assert "Secure" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
        assert "Max-Age=28800" in cookie and "Domain=" not in cookie
    assert "HttpOnly" in cookies[0] and "HttpOnly" not in cookies[1]
    with env.factory() as db:
        session = db.scalar(select(AuthSession))
        assert session.token_hash == hash_token(session_token)
        assert session.csrf_token_hash == hash_token(csrf_token)
        assert session.expires_at - session.created_at == timedelta(minutes=480)
        assert session.revoked_at is None and session.user_agent == "x" * 255
        assert session.ip_address == "192.0.2.10"
        assert db.get(UserAccount, 1).last_login_at == session.created_at
        log = db.scalar(select(LoginLog))
        assert log.user_id == 1 and log.status == "SUCCESS" and log.username_attempted == "tester"
        assert log.ip_address == "192.0.2.10"
        audit = db.scalar(select(AuditLog))
        assert audit.action == "AUTH_LOGIN" and audit.old_value is None and audit.new_value is None
    for secret in (PASSWORD, password_hash, session_token, csrf_token):
        assert secret not in response.text and secret not in caplog.text
    assert "password" not in response.text
    assert "token" not in response.text


@pytest.mark.parametrize("username,password,account_status,user_id", [
    ("tester", "wrong", "ACTIVE", 1),
    ("missing", PASSWORD, "ACTIVE", None),
    ("tester", PASSWORD, "INACTIVE", 1),
    ("tester", PASSWORD, "LOCKED", 1),
])
def test_login_denials_are_identical_and_logged(env, username, password, account_status, user_id):
    with env.factory.begin() as db:
        db.get(UserAccount, 1).account_status = account_status
    response = login(env, username, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password."}
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    with env.factory() as db:
        log = db.scalar(select(LoginLog))
        assert log.status == "FAILED" and log.user_id == user_id
        assert log.username_attempted == username and log.ip_address == "192.0.2.10"
        assert db.get(UserAccount, 1).last_login_at is None
        assert count(db, AuthSession) == count(db, AuditLog) == 0


@pytest.mark.parametrize("payload", [
    {}, {"username": " ", "password": PASSWORD},
    {"username": "x" * 61, "password": PASSWORD},
    {"username": "tester", "password": ""},
    {"username": "tester", "password": {"private": PASSWORD}},
    {"username": "tester", "password": PASSWORD * 100},
    {"username": "tester", "password": PASSWORD, "roles": ["SYSTEM_ADMIN"]},
])
def test_validation_never_echoes_password(env, payload, caplog):
    response = env.client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 422
    assert PASSWORD not in response.text + caplog.text
    assert "input" not in response.text
    with env.factory() as db:
        assert count(db, LoginLog) == 0


def test_invalid_json_never_echoes_body(env):
    response = env.client.post("/api/v1/auth/login", content='{"password":"' + PASSWORD,
                               headers={"content-type": "application/json"})
    assert response.status_code == 422 and PASSWORD not in response.text
    request = LoginRequest(username="tester", password=PASSWORD)
    assert PASSWORD not in repr(request)


@pytest.mark.parametrize("headers", [
    {"origin": "https://attacker.invalid"}, {"origin": "null"}, {"sec-fetch-site": "cross-site"},
])
def test_cross_origin_login_rejected(env, headers):
    assert login(env, headers=headers).status_code == 403
    with env.factory() as db:
        assert count(db, AuthSession) == 0


def test_same_origin_login_and_forwarded_header_not_trusted(env):
    response = login(env, headers={"origin": "https://testserver", "x-forwarded-for": "203.0.113.99"})
    assert response.status_code == 200
    with env.factory() as db:
        assert db.scalar(select(LoginLog)).ip_address == "192.0.2.10"


@pytest.mark.parametrize("state", ["missing", "unknown", "expired", "revoked", "inactive", "locked"])
def test_invalid_sessions_rejected(env, state):
    if state != "missing":
        assert login(env).status_code == 200
    if state == "unknown":
        env.client.cookies.clear()
        env.client.cookies.set(settings.auth_session_cookie_name, "unknown")
    if state in {"expired", "revoked", "inactive", "locked"}:
        with env.factory.begin() as db:
            session = db.scalar(select(AuthSession))
            if state == "expired":
                session.expires_at = utc_now()
            elif state == "revoked":
                session.revoked_at = utc_now()
            else:
                db.get(UserAccount, 1).account_status = state.upper()
    response = env.client.get("/api/v1/auth/me")
    assert response.status_code == 401 and response.json() == {"detail": "Authentication required."}


def test_me_safe_fields_permissions_and_no_csrf_requirement(env):
    assert login(env).status_code == 200
    env.client.cookies.delete(settings.auth_csrf_cookie_name)
    response = env.client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "user_id": 1, "username": "tester", "account_status": "ACTIVE",
        "roles": ["LAB_STAFF"], "permissions": ["TEST_READ"], "staff": None, "patient": None,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("identity", ["staff", "patient"])
def test_me_linked_identity_allowlist(env, identity):
    model, link = (Staff, StaffAccountLink) if identity == "staff" else (Patient, PatientAccountLink)
    with env.factory.begin() as db:
        for number in (1, 2):
            db.add(model(**{
                f"{identity}_id": number, f"{identity}_code": f"SYNTH-{number}",
                "first_name": "Linked" if number == 1 else "Unrelated", "middle_name": "M",
                "last_name": "Identity", "email": "private@example.invalid", "contact_number": "private",
            }))
        db.flush()
        db.add(link(**{f"{identity}_id": 1, "user_id": 1}))
    assert login(env).status_code == 200
    response = env.client.get("/api/v1/auth/me")
    summary = response.json()[identity]
    expected_keys = {f"{identity}_id", f"{identity}_code", "first_name", "middle_name", "last_name"}
    if identity == "staff":
        expected_keys.add("position_title")
    assert set(summary) == expected_keys and summary["first_name"] == "Linked"
    assert "private" not in response.text and "Unrelated" not in response.text
    assert "password" not in response.text


@pytest.mark.parametrize("path", ["/role", "/permission", "/user", "/api/v1/auth/logout"])
def test_unsafe_dependencies_require_csrf(env, path):
    assert login(env).status_code == 200
    assert env.client.post(path).status_code == 403
    assert env.client.post(path, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert env.client.post(path, headers=csrf(env)).status_code == 200


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_unsafe_methods_require_csrf(env, method):
    assert login(env).status_code == 200
    assert env.client.request(method, "/permission").status_code == 403
    assert env.client.request(method, "/permission", headers=csrf(env)).status_code == 200


def test_csrf_is_bound_to_the_session(env):
    assert login(env).status_code == 200
    old_csrf = csrf(env)
    assert login(env).status_code == 200
    assert env.client.post("/api/v1/auth/logout", headers=old_csrf).status_code == 403
    assert env.client.post("/api/v1/auth/logout", headers=csrf(env)).status_code == 200


def test_logout_revokes_preserves_logs_and_clears_secure_cookies(env):
    assert login(env).status_code == 200
    old_session = env.client.cookies[settings.auth_session_cookie_name]
    response = env.client.post("/api/v1/auth/logout", headers=csrf(env))
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert not env.client.cookies
    for cookie in response.headers.get_list("set-cookie"):
        assert "Max-Age=0" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Path=/" in cookie
    with env.factory() as db:
        assert db.scalar(select(AuthSession)).revoked_at is not None
        assert count(db, LoginLog) == 1
        assert {row.action for row in db.scalars(select(AuditLog))} == {"AUTH_LOGIN", "AUTH_LOGOUT"}
    env.client.cookies.set(settings.auth_session_cookie_name, old_session)
    assert env.client.get("/api/v1/auth/me").status_code == 401
    assert env.client.post("/api/v1/auth/logout").status_code == 401


def test_relogin_rotates_and_revokes_previous_session(env):
    first = login(env).cookies[settings.auth_session_cookie_name]
    assert login(env, password="wrong").status_code == 401
    assert env.client.get("/api/v1/auth/me").status_code == 200
    second = login(env).cookies[settings.auth_session_cookie_name]
    assert first != second
    with env.factory() as db:
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(first))).revoked_at is not None
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(second))).revoked_at is None


def test_rbac_and_changes_without_new_session(env):
    assert login(env).status_code == 200
    for path in ("/role", "/permission", "/alternative-role", "/alternative-permission"):
        assert env.client.get(path).status_code == 200
    assert env.client.head("/permission").status_code == 200
    with env.factory.begin() as db:
        db.delete(db.get(RolePermission, 1))
    assert env.client.get("/permission").status_code == 403
    assert env.client.get("/api/v1/auth/me").json()["permissions"] == []
    with env.factory.begin() as db:
        db.add(RolePermission(role_id=1, permission_id=1))
    assert env.client.get("/permission").status_code == 200
    with env.factory.begin() as db:
        db.get(Role, 1).is_active = False
    assert env.client.get("/role").status_code == 403
    assert env.client.get("/permission").status_code == 403
    assert env.client.get("/api/v1/auth/me").json()["roles"] == []


def test_wrong_role_and_system_admin_permission_override(env):
    with env.factory.begin() as db:
        db.get(Role, 1).role_code = "SYSTEM_ADMIN"
        db.delete(db.get(RolePermission, 1))
    assert login(env).status_code == 200
    assert env.client.get("/role").status_code == 403
    assert env.client.get("/permission").status_code == 200
    assert env.client.get("/api/v1/auth/me").json()["permissions"] == []
    with env.factory.begin() as db:
        db.get(Role, 1).is_active = False
    assert env.client.get("/permission").status_code == 403


def test_no_role_or_permission_codes_is_configuration_error():
    with pytest.raises(ValueError):
        dependencies.require_role()
    with pytest.raises(ValueError):
        dependencies.require_permission()


@pytest.mark.parametrize("failure_model", [AuthSession, LoginLog, AuditLog])
def test_failed_login_transaction_leaves_no_partial_success(env, failure_model, caplog):
    def fail(session, context, instances):
        if any(isinstance(row, failure_model) for row in session.new):
            raise SQLAlchemyError("synthetic private database details")
    event.listen(env.factory, "before_flush", fail)
    try:
        response = login(env)
    finally:
        event.remove(env.factory, "before_flush", fail)
    assert response.status_code == 503
    assert "private" not in response.text + caplog.text
    assert "set-cookie" not in response.headers
    with env.factory() as db:
        assert count(db, AuthSession) == count(db, LoginLog) == count(db, AuditLog) == 0
        assert db.get(UserAccount, 1).last_login_at is None


def test_logout_failure_rolls_back_revocation(env):
    assert login(env).status_code == 200
    def fail(session, context, instances):
        raise SQLAlchemyError("synthetic failure")
    event.listen(env.factory, "before_flush", fail)
    try:
        response = env.client.post("/api/v1/auth/logout", headers=csrf(env))
    finally:
        event.remove(env.factory, "before_flush", fail)
    assert response.status_code == 503 and "set-cookie" not in response.headers
    with env.factory() as db:
        assert db.scalar(select(AuthSession)).revoked_at is None
        assert count(db, AuditLog) == 1
    assert env.client.get("/api/v1/auth/me").status_code == 200


def test_bootstrap_admin_atomic_and_hashed(env):
    with env.factory() as db:
        result = bootstrap_admin.create_admin(db, "  first-admin  ", PASSWORD)
    with env.factory() as db:
        user = db.get(UserAccount, result["user_id"])
        assert user.username == "first-admin" and user.account_status == "ACTIVE"
        assert verify_password(PASSWORD, user.password_hash)
        assert user.password_hash.startswith("$argon2id$")
        assert user.staff_link is None and user.last_login_at is None
        assert {assignment.role.role_code for assignment in user.user_roles} == {"SYSTEM_ADMIN"}
        assert count(db, Role) == 5
        assert db.scalar(select(AuditLog)).action == "AUTH_BOOTSTRAP_ADMIN"
    with env.factory() as db, pytest.raises(ValueError, match="already exists"):
        bootstrap_admin.create_admin(db, "first-admin", "Another-password-123")
    with env.factory() as db:
        assert verify_password(PASSWORD, db.get(UserAccount, result["user_id"]).password_hash)


@pytest.mark.parametrize("username,password", [("", PASSWORD), ("a" * 61, PASSWORD), ("admin", "short"), ("admin", "")])
def test_bootstrap_rejects_invalid_input_without_changes(env, username, password):
    with env.factory() as db, pytest.raises(ValueError):
        bootstrap_admin.create_admin(db, username, password)
    with env.factory() as db:
        assert count(db, UserAccount) == count(db, Role) == 1
        assert count(db, AuditLog) == 0


def test_bootstrap_assignment_failure_rolls_back_roles_account_audit(env):
    def fail(session, context, instances):
        if any(isinstance(row, UserRole) for row in session.new):
            raise SQLAlchemyError("synthetic failure")
    event.listen(env.factory, "before_flush", fail)
    try:
        with env.factory() as db, pytest.raises(SQLAlchemyError):
            bootstrap_admin.create_admin(db, "first-admin", PASSWORD)
    finally:
        event.remove(env.factory, "before_flush", fail)
    with env.factory() as db:
        assert count(db, UserAccount) == count(db, Role) == 1
        assert count(db, AuditLog) == 0


def test_core_roles_idempotent_preserves_existing_roles(env):
    with env.factory.begin() as db:
        role = db.get(Role, 1)
        role.role_name = "Custom name"
        role.is_active = False
        assert len(ensure_core_roles(db)) == 4
        assert ensure_core_roles(db) == []
    bootstrap_roles.main()
    with env.factory() as db:
        assert count(db, Role) == 5 and count(db, UserRole) == 1
        assert db.get(Role, 1).role_name == "Custom name" and not db.get(Role, 1).is_active


def test_bootstrap_refuses_disabled_admin_role(env):
    with env.factory.begin() as db:
        db.add(Role(role_code="SYSTEM_ADMIN", role_name="Disabled", is_active=False))
    with env.factory() as db, pytest.raises(ValueError, match="inactive"):
        bootstrap_admin.create_admin(db, "first-admin", PASSWORD)
    with env.factory() as db:
        assert count(db, Role) == 2 and count(db, UserAccount) == 1


def test_interactive_bootstrap_no_password_output(env, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "first-admin")
    prompt = Mock(side_effect=[PASSWORD, PASSWORD])
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", prompt)
    bootstrap_admin.main([])
    output = capsys.readouterr()
    assert "Created administrator: first-admin" in output.out
    assert PASSWORD not in output.out + output.err and "$argon2" not in output.out + output.err
    assert prompt.call_count == 2


def test_bootstrap_username_option_and_no_insecure_getpass_fallback(env, monkeypatch, capsys):
    import warnings
    def insecure(prompt):
        warnings.warn("cannot hide input", bootstrap_admin.getpass.GetPassWarning)
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", insecure)
    with pytest.raises(SystemExit) as result:
        bootstrap_admin.main(["--username", "first-admin"])
    assert result.value.code == 1
    assert "secure interactive terminal" in capsys.readouterr().err
    with env.factory() as db:
        assert count(db, UserAccount) == 1


def test_production_cookie_settings_validation():
    config = Settings(_env_file=None, environment="production")
    assert config.auth_cookie_secure and config.auth_cookie_samesite == "strict"
    for changes in (
        {"auth_session_ttl_minutes": 0}, {"auth_cookie_secure": False},
        {"auth_cookie_samesite": "none"}, {"auth_session_cookie_name": "bad;name"},
        {"auth_csrf_cookie_name": "rhu_session"},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, environment="production", **changes)


def test_openapi_and_existing_application_routes():
    from app.main import app
    schema = app.openapi()
    for route, method in (("login", "post"), ("logout", "post"), ("me", "get")):
        assert "Authentication" in schema["paths"][f"/api/v1/auth/{route}"][method]["tags"]
    for route in ("/api/v1/health", "/api/v1/ready"):
        assert "get" in schema["paths"][route]
    assert "password_hash" not in str(schema)
    assert schema["components"]["securitySchemes"]["APIKeyCookie"]["in"] == "cookie"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/health").status_code == 200
