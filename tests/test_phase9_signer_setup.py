"""API-only signer setup tests; production networking is blocked by conftest."""
from copy import deepcopy
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import phase9_e2e_validation as e2e
from scripts import phase9_signer_setup as setup


OPERATOR = {"user_id": 20, "username": "operator", "account_status": "ACTIVE",
            "roles": ["SYSTEM_ADMIN"], "permissions": [], "staff": None}
WITNESS = {"user_id": 21, "username": "existing-signer", "account_status": "ACTIVE",
           "roles": ["LAB_SIGNER"], "permissions": ["REPORT_SIGN"], "staff": None}
CREATED = {"user_id": 22, "username": "p9signer", "account_status": "ACTIVE",
           "roles": ["LAB_SIGNER"], "permissions": ["REPORT_SIGN"],
           "staff": {"staff_id": 1, "staff_code": "P9SIGN01"}, "patient": None}
SECRET = "PRIVATE-test-password"


class Identity:
    def __init__(self, me):
        self.me = deepcopy(me)

    def get(self, path):
        assert path == "/auth/me"
        return deepcopy(self.me)

    def login(self, *args, **kwargs):
        if kwargs:
            assert kwargs == {"username": "p9signer", "password": SECRET}
        return deepcopy(self.me)


class API:
    def __init__(self, spec, *, execute=False):
        self.base = e2e.BASE
        self.execute = execute
        self.session_cookie, self.csrf_cookie = "rhu_session", "rhu_csrf"
        self.spec = deepcopy(spec)
        self.inventory = deepcopy([OPERATOR, WITNESS])
        self.staff = {"staff_id": 1, "staff_code": "P9SIGN01", "is_active": True}
        self.roles = [{"role_id": 1, "role_code": "SYSTEM_ADMIN", "is_active": True},
                      {"role_id": 2, "role_code": "LAB_SIGNER", "is_active": True}]
        self.created = deepcopy(CREATED)
        self.calls = []
        self.fail_create = False
        self.before_post = None

    def login(self, *args, **kwargs):
        return deepcopy(OPERATOR)

    def get(self, path):
        return self.request("GET", e2e.API + path)

    def request(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path))
        if path == "/openapi.json":
            return deepcopy(self.spec)
        path = path.removeprefix(e2e.API)
        if method == "GET":
            if path == "/auth/me":
                return deepcopy(OPERATOR)
            if path == "/staff/1":
                return deepcopy(self.staff)
            if path == "/roles":
                return deepcopy(self.roles)
            if path == "/permissions":
                return [{"permission_code": "REPORT_SIGN"}]
            if path.startswith("/users?"):
                page = int(parse_qs(urlsplit(path).query)["page"][0])
                return {"items": deepcopy(self.inventory[(page - 1) * 100:page * 100]),
                        "total": len(self.inventory), "page": page, "page_size": 100}
            if path.startswith("/users/"):
                uid = int(path.split("/")[-1])
                return deepcopy(next(a for a in self.inventory if a["user_id"] == uid))
        assert self.execute and method == "POST" and path == "/staff/1/account"
        assert kwargs["expected"] == (201,)
        assert payload == {"username": "p9signer", "password": SECRET, "role_codes": ["LAB_SIGNER"]}
        if self.before_post:
            self.before_post()
        if self.fail_create:
            raise e2e.ValidationError("Network request failed; outcome may be uncertain; request was not retried.")
        self.inventory.append(deepcopy(self.created))
        return deepcopy(self.created)


@pytest.fixture
def api():
    from app.main import app
    return API(app.openapi())


@pytest.fixture
def witness():
    return Identity(WITNESS)


def writes(api):
    return [(method, path) for method, path in api.calls if method != "GET"]


def prepare(api, witness, monkeypatch):
    api.execute = True
    okay, evidence = setup.preflight(api, witness)
    assert okay
    monkeypatch.setattr(e2e, "hidden_input", lambda _: SECRET)
    return evidence


def test_default_preflight_no_writes_or_password_prompt(api, monkeypatch, tmp_path):
    monkeypatch.setattr(e2e, "Client", lambda *a, **kw: api)
    monkeypatch.setattr(e2e, "hidden_input", lambda _: pytest.fail("No new credential in preflight"))
    path = tmp_path / "intent.json"
    assert setup.parse_args([]).execute is False
    assert setup.main(["--intent-file", str(path)]) == 1  # No role evidence, fail closed.
    assert not writes(api) and not path.exists()


def test_supported_witness_preflight_succeeds_without_writes(api, witness, monkeypatch):
    clients = iter([api, witness])
    monkeypatch.setattr(e2e, "Client", lambda *a, **kw: next(clients))
    assert setup.main(["--preflight", "--role-verifier-login"]) == 0
    assert not writes(api)


def test_execute_gate_precedes_prompts_and_reads(api, witness, tmp_path, monkeypatch):
    monkeypatch.setattr(e2e, "hidden_input", lambda _: pytest.fail("Must fail before prompting"))
    with pytest.raises(e2e.ValidationError, match="--execute"):
        setup.execute(api, witness, {}, tmp_path / "intent.json")
    assert api.calls == []


@pytest.mark.parametrize("argv", [["--execute", "--preflight"], ["--password", SECRET]])
def test_cli_rejects_unsafe_arguments(argv):
    with pytest.raises(SystemExit):
        setup.parse_args(argv)


@pytest.mark.parametrize("conflict", ["staff", "username", "normalized_username", "inactive_staff"])
def test_existing_targets_stop_before_post(api, witness, conflict, tmp_path, monkeypatch):
    evidence = prepare(api, witness, monkeypatch)
    if conflict == "staff":
        api.inventory.append({**CREATED, "username": "other", "account_status": "INACTIVE"})
    elif conflict == "inactive_staff":
        api.staff["is_active"] = False
    else:
        name = "p9signer" if conflict == "username" else "P9SÍGNER"
        api.inventory.append({**CREATED, "username": name, "staff": None})
    with pytest.raises(e2e.ValidationError, match="preflight changed"):
        setup.execute(api, witness, evidence, tmp_path / "intent.json")
    assert not writes(api)


def test_account_inventory_includes_later_pages_and_inactive_links(api, witness):
    api.inventory = [{**OPERATOR, "user_id": 100 + i, "username": f"user{i}"} for i in range(100)]
    api.inventory[0] = deepcopy(WITNESS)
    api.inventory.append({**CREATED, "username": "inactive-link", "account_status": "INACTIVE"})
    assert not setup.preflight(api, witness)[0]
    assert ("GET", e2e.API + "/users?page=2&page_size=100") in api.calls
    assert not writes(api)


def test_changing_pagination_total_fails_closed(api, monkeypatch):
    original = api.get
    api.inventory *= 60
    api.inventory = [{**a, "user_id": i + 100} for i, a in enumerate(api.inventory)]
    def changed(path):
        body = original(path)
        if "page=2&" in path:
            body["total"] += 1
        return body
    monkeypatch.setattr(api, "get", changed)
    with pytest.raises(e2e.ValidationError, match="changed during pagination"):
        setup.accounts(api)


@pytest.mark.parametrize("change", ["admin", "patient", "broad", "missing", "multiple", "inactive", "hidden_role", "same_operator"])
def test_only_exact_minimum_active_single_role_can_be_selected(api, witness, change):
    if change in {"admin", "patient"}:
        witness.me["roles"] = ["SYSTEM_ADMIN" if change == "admin" else "PATIENT"]
    elif change == "broad":
        witness.me["permissions"].append("ACCOUNT_CREATE")
    elif change == "missing":
        witness.me["permissions"] = []
    elif change == "multiple":
        witness.me["roles"].append("OTHER")
    elif change == "inactive":
        api.roles[1]["is_active"] = False
    elif change == "hidden_role":
        api.inventory[1]["roles"].append("INACTIVE_ROLE")
    else:
        witness.me["user_id"] = OPERATOR["user_id"]
    assert not setup.preflight(api, witness)[0]
    assert not writes(api)


def test_catalog_is_not_permission_membership(api, capsys):
    okay, evidence = setup.preflight(api)
    assert not okay and evidence is None
    assert "permission membership not exposed" in capsys.readouterr().out


def test_actual_schema_and_absent_role_mutation_routes(api):
    schemas = setup.inspect_contract(api)
    assert set(schemas["StaffAccountCreate"]["required"]) == {"username", "password", "role_codes"}
    for path, methods in api.spec["paths"].items():
        if "/roles" in path or "/permissions" in path:
            mutations = set(methods) & {"post", "put", "patch", "delete"}
            assert not mutations or (path == e2e.API + "/users/{user_id}/roles" and mutations == {"put"})


def test_create_minimal_signer_then_verify_without_other_writes(api, witness, monkeypatch, tmp_path, capsys):
    evidence = prepare(api, witness, monkeypatch)
    path = tmp_path / "intent.json"
    def recorded():
        intent = json.loads(path.read_text())
        assert intent["status"] == "PENDING"
        assert intent["permissions"] == ["REPORT_SIGN"]
    api.before_post = recorded
    uid = setup.execute(api, witness, evidence, path, client_factory=lambda *a, **kw: Identity(CREATED))
    assert uid == 22
    assert writes(api) == [("POST", e2e.API + "/staff/1/account")]
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "VERIFIED" and receipt["role_codes"] == ["LAB_SIGNER"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert SECRET not in path.read_text() + capsys.readouterr().out
    assert "password" not in path.read_text()


def test_password_confirmation_mismatch_blocks_write(api, witness, monkeypatch, tmp_path):
    evidence = prepare(api, witness, monkeypatch)
    answers = iter([SECRET, "different-password"])
    monkeypatch.setattr(e2e, "hidden_input", lambda _: next(answers))
    with pytest.raises(e2e.ValidationError, match="confirmation"):
        setup.execute(api, witness, evidence, tmp_path / "intent.json")
    assert not writes(api)


def test_rechecks_state_after_password_prompt(api, witness, monkeypatch, tmp_path):
    evidence = prepare(api, witness, monkeypatch)
    def prompt(_):
        api.inventory.append({**CREATED, "staff": None})
        return SECRET
    monkeypatch.setattr(e2e, "hidden_input", prompt)
    with pytest.raises(e2e.ValidationError, match="state changed"):
        setup.execute(api, witness, evidence, tmp_path / "intent.json")
    assert not writes(api)


def test_uncertain_post_is_never_retried(api, witness, monkeypatch, tmp_path, capsys):
    evidence = prepare(api, witness, monkeypatch)
    api.fail_create = True
    path = tmp_path / "intent.json"
    with pytest.raises(e2e.ValidationError, match="not retried"):
        setup.execute(api, witness, evidence, path)
    assert api.calls[-1] == ("POST", e2e.API + "/staff/1/account")
    assert json.loads(path.read_text())["status"] == "PENDING"
    with pytest.raises(FileExistsError):
        setup.execute(api, witness, evidence, path)
    assert len(writes(api)) == 1
    assert SECRET not in path.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("change", ["wrong_staff", "admin", "inactive", "same_id", "extra_permission", "login_failure"])
def test_post_create_verification_stops_without_repair_writes(api, witness, monkeypatch, tmp_path, change):
    evidence = prepare(api, witness, monkeypatch)
    me = deepcopy(CREATED)
    if change == "wrong_staff":
        api.created["staff"]["staff_id"] = 2
    elif change == "admin":
        api.created["roles"] = ["SYSTEM_ADMIN"]
    elif change == "inactive":
        api.created["account_status"] = "INACTIVE"
    elif change == "same_id":
        api.created["user_id"] = OPERATOR["user_id"]
    elif change == "extra_permission":
        me["permissions"].append("REPORT_APPROVE")
    else:
        me["account_status"] = "LOCKED"
    path = tmp_path / "intent.json"
    with pytest.raises(e2e.ValidationError):
        setup.execute(api, witness, evidence, path, client_factory=lambda *a, **kw: Identity(me))
    assert len(writes(api)) == 1
    assert json.loads(path.read_text())["status"] != "VERIFIED"


def test_unexpected_failure_withholds_secret_details(api, monkeypatch, capsys):
    def failed(*args, **kwargs):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(api, "login", failed)
    monkeypatch.setattr(e2e, "Client", lambda *a, **kw: api)
    assert setup.main([]) == 1
    assert SECRET not in capsys.readouterr().out
    assert not writes(api)
