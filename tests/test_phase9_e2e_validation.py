"""Runner tests: synthetic responses only; conftest blocks all production network."""
from copy import deepcopy
import http.cookiejar
import io
import json
import re
import urllib.error
import warnings

import pytest

from scripts import phase9_e2e_validation as p9


ME = {"user_id": 20, "account_status": "ACTIVE", "roles": ["SYSTEM_ADMIN"],
      "permissions": [], "staff": None}
SIGNER = {"user_id": 21, "account_status": "ACTIVE", "roles": ["PHASE9_SIGNER"],
          "permissions": ["REPORT_SIGN"], "staff": {"staff_id": 1, "staff_code": "P9SIGN01"}}
QUEUE = {"counts": {"pending": 0, "processing": 0, "confirmed": 1, "failed": 0, "dead": 0},
         "worker_health": "IDLE", "delivery_enabled": None}


@pytest.fixture
def spec():
    # Source contract compatibility, not a synthetic imitation of OpenAPI.
    from app.main import app
    return app.openapi()


class FakeAPI:
    def __init__(self, spec, *, execute=False):
        self.base, self.execute = p9.BASE, execute
        self.session_cookie, self.csrf_cookie = "rhu_session", "rhu_csrf"
        self.spec = spec
        self.calls = []
        self.fail = None
        self.patient_body = None
        self.order_body = None
        self.specimen_body = None
        self.result_body = None
        self.report_body = None
        self.reports = {}
        self.next_report_id = 106
        self.poll_states = []
        self.masters = {
            "/facility-profile": {"facility_id": 1, "facility_name": "Phase 9 Validation Laboratory"},
            "/lab/departments/1": {"department_id": 1, "department_code": "P9LAB", "is_active": True},
            "/lab/sample-types/1": {"sample_type_id": 1, "sample_name": "Whole Blood (Phase 9 Validation)", "is_active": True},
            "/lab/tests/1": {"test_id": 1, "test_code": "P9NUM", "department_id": 1, "result_type": "NUMERIC", "default_unit": "unit", "is_active": True},
            "/referring-facilities/1": {"referring_facility_id": 1, "facility_name": "Phase 9 Validation Referral Facility"},
            "/physicians/1": {"physician_id": 1, "first_name": "Phase", "last_name": "Nine Validation", "referring_facility_id": 1, "is_active": True},
            "/staff/1": {"staff_id": 1, "staff_code": "P9SIGN01", "is_active": True},
            "/signatories/1": {"signatory_id": 1, "staff_id": 1, "is_active": True},
            "/report-templates/1": {"template_id": 1, "template_code": "P9REPORT", "panel_id": None, "footer_note": "Not for clinical use.", "is_active": True},
            "/lab/tests/1/sample-types": [{"test_id": 1, "sample_type_id": 1, "is_default": True}],
        }

    def login(self, *args, **kwargs):
        return deepcopy(ME)

    def get(self, path, **kwargs):
        return self.request("GET", p9.API + path, **kwargs)

    def request(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path, deepcopy(payload)))
        if self.fail == (method, path):
            raise p9.ValidationError("Synthetic request failure.")
        if path == "/openapi.json":
            return self.spec
        path = path.removeprefix(p9.API)
        if method == "GET":
            if path == "/auth/me":
                return deepcopy(ME)
            if path == "/health":
                return {"status": "ok"}
            if path == "/ready":
                return {"status": "ready", "mysql": {"connected": True, "database": "rhu_labchain"}}
            if path == "/blockchain/status":
                return deepcopy(QUEUE)
            if path in self.masters:
                return deepcopy(self.masters[path])
            if path == "/patients/101":
                return deepcopy(self.patient_body)
            if path == "/lab-orders/102":
                return deepcopy(self.order_body)
            if path == "/specimens/104":
                return deepcopy(self.specimen_body)
            if path == "/results/105":
                return deepcopy(self.result_body)
            if re.fullmatch(r"/reports/\d+", path):
                result = deepcopy(self.reports[int(path.split("/")[2])])
                if self.poll_states:
                    state = self.poll_states.pop(0)
                    result["anchoring"] = {"status": state, "release": receipt(state)}
                return result
            if re.fullmatch(r"/reports/\d+/verification", path):
                rid = int(path.split("/")[2])
                state = "REVOKED" if self.reports[rid]["report_status"] == "REVOKED" else "AUTHENTIC"
                return {"verification_status": state, "verification_url": p9.BASE + "/api/v1/verify/" + ("T" if rid == 106 else "U") * 43}
            if path.startswith("/verify/"):
                rid = 106 if path.endswith("T" * 43) else 108
                state = "REVOKED" if self.reports[rid]["report_status"] == "REVOKED" else "VERIFIED"
                return {"status": state, "blockchain_status": "CONFIRMED", "blockchain_confirmed_at": "2026-10-04T00:00:00"}
            raise AssertionError("Unexpected synthetic GET: " + path)
        assert self.execute
        assert method == "POST"
        if path == "/patients":
            self.patient_body = {**payload, "patient_id": 101}
            return deepcopy(self.patient_body)
        if path == "/lab-orders":
            self.order_body = {**payload, "order_id": 102, "status": "REQUESTED", "panels": [],
                               "items": [{"order_item_id": 103, "order_id": 102, "test_id": 1,
                                          "order_panel_id": None, "status": "REQUESTED"}]}
            return deepcopy(self.order_body)
        if path == "/lab-orders/102/specimens":
            self.order_body["status"] = self.order_body["items"][0]["status"] = "IN_PROGRESS"
            self.specimen_body = {**payload, "specimen_id": 104, "order_id": 102, "specimen_status": "PENDING",
                                  "mappings": [{"order_item_id": 103}]}
            return deepcopy(self.specimen_body)
        if path in {"/specimens/104/collect", "/specimens/104/receive"}:
            self.specimen_body["specimen_status"] = "COLLECTED" if path.endswith("collect") else "RECEIVED"
            return deepcopy(self.specimen_body)
        if path == "/lab-order-items/103/result":
            self.specimen_body["specimen_status"] = "PROCESSED"
            self.result_body = {**payload, "result_item_id": 105, "order_id": 102, "order_item_id": 103, "status": "DRAFT"}
            return deepcopy(self.result_body)
        if path in {"/results/105/review", "/results/105/verify"}:
            self.result_body["status"] = "REVIEWED" if path.endswith("review") else "VERIFIED"
            if path.endswith("verify"):
                self.order_body["status"] = self.order_body["items"][0]["status"] = "COMPLETED"
            return deepcopy(self.result_body)
        if path == "/lab-orders/102/reports":
            self.report_body = {**payload, "report_id": 106, "order_id": 102, "facility_id": 1,
                                "report_status": "GENERATED", "signatories": [],
                                "patient_snapshot": {"patient_code": self.patient_body["patient_code"],
                                                     "patient_name": "Phase9 " + self.patient_body["last_name"]},
                                "result_snapshots": [{"result_item_id": 105, "result_value_snapshot": "42", "panel_id_snapshot": None}]}
            self.reports[106] = self.report_body
            return deepcopy(self.report_body)
        if re.fullmatch(r"/reports/\d+/\w+", path):
            rid = int(path.split("/")[2])
            report = self.reports[rid]
            action = path.split("/")[-1]
            if action == "signatories":
                report["signatories"] = [{**payload, "report_id": rid, "report_signatory_id": rid + 1, "signed_at": None}]
                return deepcopy(report["signatories"][0])
            if action == "sign":
                report["signatories"][0]["signed_at"] = "2026-10-04T00:00:00"
                return deepcopy(report["signatories"][0])
            if action in {"approve", "release"}:
                report["report_status"] = "APPROVED" if action == "approve" else "RELEASED"
                report["anchoring"] = {"status": "CONFIRMED", "release": receipt("CONFIRMED")}
                if action == "release" and rid == 108:
                    self.reports[106]["report_status"] = "REVOKED"
                    self.reports[106]["anchoring"]["supersession"] = receipt("CONFIRMED")
                return deepcopy(report)
            if action == "revoke":
                report["report_status"] = "REVOKED"
                report["anchoring"]["revocation"] = receipt("CONFIRMED")
                return deepcopy(report)
            if action == "revise":
                revised = deepcopy(report)
                revised.update(report_id=108, report_status="GENERATED", signatories=[], supersedes_report_id=106)
                self.reports[108] = revised
                return deepcopy(revised)
        raise AssertionError("Unexpected synthetic write: " + path)


class FakeSigner:
    def __init__(self, api):
        self.api = api
        self.calls = []
        self.identity = deepcopy(SIGNER)

    def login(self, *args, **kwargs):
        return deepcopy(self.identity)

    def get(self, path, **kwargs):
        assert path == "/auth/me"
        return deepcopy(self.identity)

    def request(self, method, path, payload=None, **kwargs):
        assert method == "POST" and re.fullmatch(p9.API + r"/reports/\d+/sign", path)
        self.calls.append((method, path))
        return self.api.request(method, path, payload, **kwargs)


def receipt(status):
    return {"status": status, "confirmed_at": "2026-10-04T00:00:00", "transaction_id": "a" * 64,
            "block_number": 0, "last_error": "PRIVATE-WORKER-ERROR", "canonical_payload": "PRIVATE-PAYLOAD"}


@pytest.fixture
def run(tmp_path, spec):
    api = FakeAPI(spec, execute=True)
    journal = p9.Journal(tmp_path / "run.json", create=True)
    journal.data["counts_before"] = deepcopy(QUEUE["counts"])
    runner = p9.Runner(api, FakeSigner(api), journal)
    yield runner, api, journal
    journal.close()


def test_preflight_never_writes_and_checks_actual_contract(spec, capsys):
    api = FakeAPI(spec)
    okay, _ = p9.preflight(api, ME, SIGNER, p9.parse_args(["--signer-login"]))
    assert okay
    assert all(method == "GET" for method, _, _ in api.calls)
    assert "not worker or Fabric liveness" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["inactive", "wrong_code", "assignment", "signer"])
def test_preflight_catches_missing_prerequisites(spec, change):
    api = FakeAPI(spec)
    signer = deepcopy(SIGNER)
    if change == "inactive":
        api.masters["/signatories/1"]["is_active"] = False
    elif change == "wrong_code":
        api.masters["/lab/tests/1"]["test_code"] = "REAL"
    elif change == "assignment":
        api.masters["/lab/tests/1/sample-types"] = []
    else:
        signer["staff"] = None
    assert not p9.preflight(api, ME, signer, p9.parse_args([]))[0]
    assert all(method == "GET" for method, _, _ in api.calls)


def test_contract_drift_fails_before_writes(spec):
    changed = deepcopy(spec)
    changed["components"]["schemas"]["OrderCreate"]["required"].append("new_field")
    with pytest.raises(p9.ValidationError, match="required fields"):
        p9.check_contracts(changed)


class Reply:
    def __init__(self, data, status=200):
        self.status = status
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return json.dumps(self.data).encode()


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, req, **kwargs):
        self.requests.append(req)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def cookie(client, name, value):
    client.jar.set_cookie(http.cookiejar.Cookie(0, name, value, None, False, "labchain.online", True, False,
                                               "/", True, True, None, True, None, None, {}))


def test_write_gate_is_enforced_in_http_client():
    transport = Transport([])
    client = p9.Client(opener=transport)
    with pytest.raises(p9.ValidationError, match="--execute"):
        client.request("POST", p9.API + "/patients", {})
    assert not transport.requests


def test_csrf_header_on_write_only_and_missing_token_fails():
    transport = Transport([Reply({}), Reply({})])
    client = p9.Client(execute=True, opener=transport)
    with pytest.raises(p9.ValidationError, match="CSRF"):
        client.request("POST", p9.API + "/patients", {})
    cookie(client, "rhu_csrf", "PRIVATE-CSRF")
    client.get("/health")
    client.request("POST", p9.API + "/patients", {})
    assert transport.requests[0].get_header("X-csrf-token") is None
    assert transport.requests[1].get_header("X-csrf-token") == "PRIVATE-CSRF"
    assert transport.requests[1].get_header("Origin") == p9.BASE


def test_authentication_secrets_not_logged(capsys):
    transport = Transport([Reply({"user_id": 20}), Reply(ME)])
    client = p9.Client(opener=transport)
    cookie(client, "rhu_session", "PRIVATE-SESSION")
    client.login(username="admin", password="PRIVATE-PASSWORD")
    assert "PRIVATE-" not in capsys.readouterr().out
    assert transport.requests[0].get_header("X-csrf-token") is None


def test_hidden_input_refuses_echo_fallback(monkeypatch):
    def fallback(_):
        warnings.warn("Cannot control echo", p9.getpass.GetPassWarning)
        raise AssertionError("Must not reach echoed input")
    monkeypatch.setattr(p9.getpass, "getpass", fallback)
    with pytest.raises(p9.ValidationError, match="secure interactive"):
        p9.hidden_input("Password: ")


def test_mfa_uses_hidden_input_without_logging(monkeypatch, capsys):
    transport = Transport([Reply({"mfa_required": True}, 202), Reply({}), Reply(ME)])
    client = p9.Client(opener=transport)
    cookie(client, "rhu_session", "PRIVATE-SESSION")
    monkeypatch.setattr("builtins.input", lambda _: "totp")
    monkeypatch.setattr(p9.getpass, "getpass", lambda _: "123456")
    client.login(username="admin", password="PRIVATE-PASSWORD")
    assert transport.requests[1].full_url.endswith("/auth/mfa/verify")
    assert json.loads(transport.requests[1].data) == {"code": "123456"}
    assert "123456" not in capsys.readouterr().out


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError(p9.BASE, 503, "PRIVATE-ERROR", {}, io.BytesIO(b"PRIVATE-BODY")),
    urllib.error.URLError("PRIVATE-URL-TOKEN"), TimeoutError("PRIVATE-TIMEOUT"),
])
def test_post_failure_has_one_attempt_and_safe_error(error):
    transport = Transport([error])
    client = p9.Client(execute=True, opener=transport)
    cookie(client, "rhu_csrf", "PRIVATE-CSRF")
    with pytest.raises(p9.ValidationError) as caught:
        client.request("POST", p9.API + "/patients", {})
    assert len(transport.requests) == 1
    assert "PRIVATE" not in str(caught.value)


def test_redirects_never_forward_credentials():
    req = p9.urllib.request.Request(p9.BASE + "/api/v1/auth/login", data=b"secret", method="POST")
    assert p9.NoRedirect().redirect_request(req, None, 302, "", {}, "https://other.example") is None


def test_complete_baseline_tracks_returned_ids_and_never_revises(run, monkeypatch, capsys):
    runner, api, journal = run
    runner.baseline()
    monkeypatch.setattr(p9, "Client", lambda base: api)
    runner.confirm_baseline()
    assert runner.ids == {"patient_id": 101, "order_id": 102, "order_item_id": 103, "specimen_id": 104,
                          "result_item_id": 105, "report_id": 106, "report_signatory_id": 107}
    writes = [path for method, path, _ in api.calls if method == "POST"]
    assert len(writes) == len(set(writes)) == 13
    assert not any("revoke" in path or "revise" in path or "payment" in path or "activate" in path for path in writes)
    assert journal.data["baseline_pass"] is True
    text = capsys.readouterr().out
    assert "PRIVATE" not in text and "T" * 43 not in text
    stored = journal.path.read_text()
    assert "PRIVATE" not in stored and "password" not in stored and "verification_url" not in stored
    assert len(runner.run_id) <= 20


def test_failed_post_stops_later_steps_and_records_intent(run):
    runner, api, journal = run
    api.fail = ("POST", p9.API + "/lab-orders")
    with pytest.raises(p9.ValidationError):
        runner.baseline()
    writes = [path for method, path, _ in api.calls if method == "POST"]
    assert writes == [p9.API + "/patients", p9.API + "/lab-orders"]
    assert journal.data["pending"] == "Order"
    with pytest.raises(p9.ValidationError):
        runner.baseline()
    assert [path for method, path, _ in api.calls if method == "POST"] == writes


def test_wrong_response_state_stops_next_write(run, monkeypatch):
    runner, api, journal = run
    original = api.request
    def bad(method, path, *args, **kwargs):
        body = original(method, path, *args, **kwargs)
        if method == "POST" and path.endswith("/lab-orders"):
            body["status"] = "CANCELLED"
        return body
    monkeypatch.setattr(api, "request", bad)
    with pytest.raises(p9.ValidationError):
        runner.baseline()
    assert journal.data["pending"] == "Order"
    assert not any("specimens" in path for _, path, _ in api.calls)


def test_poll_pending_processing_retrying_confirmed(run):
    runner, api, _ = run
    runner.baseline()
    api.poll_states = ["PENDING", "PROCESSING", "RETRYING", "CONFIRMED"]
    tick = [0]
    runner.clock = lambda: tick[0]
    runner.sleep = lambda duration: tick.__setitem__(0, tick[0] + duration)
    assert runner.poll()["status"] == "CONFIRMED"
    assert tick[0] == 30


def test_poll_timeout_without_writes(run):
    runner, api, _ = run
    runner.baseline()
    api.calls.clear()
    api.poll_states = ["PENDING"] * 10
    tick = [0]
    runner.timeout = 20
    runner.clock = lambda: tick[0]
    runner.sleep = lambda duration: tick.__setitem__(0, tick[0] + duration)
    with pytest.raises(p9.ValidationError, match="timed out"):
        runner.poll()
    assert all(method == "GET" for method, _, _ in api.calls)
    assert tick[0] == 20


@pytest.mark.parametrize("state", ["FAILED", "NOT_ANCHORED", "PRIVATE-UNKNOWN"])
def test_poll_failure_does_not_echo_errors(run, state, capsys):
    runner, api, _ = run
    runner.baseline()
    api.poll_states = [state]
    with pytest.raises(p9.ValidationError):
        runner.poll()
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.parametrize("field", ["transaction_id", "block_number", "patient_name", "report_id", "worker_error", "canonical_payload", "nested"])
def test_public_privacy_allowlist(field):
    body = {"status": "VERIFIED", "blockchain_status": "CONFIRMED", "blockchain_confirmed_at": "2026-10-04", field: "PRIVATE"}
    with pytest.raises(p9.ValidationError, match="privacy"):
        p9.validate_public(body)


def test_public_nested_content_rejected():
    with pytest.raises(p9.ValidationError):
        p9.validate_public({"status": "VERIFIED", "message": {"patient_id": 1}, "blockchain_status": "CONFIRMED"})


def test_patient_ownership_not_bypassed_for_admin_or_other_patient():
    for me in [ME, {"roles": ["PATIENT"], "patient": {"patient_id": 999}}, {"roles": ["PATIENT"], "patient": None}]:
        with pytest.raises(p9.ValidationError, match="ownership"):
            p9.validate_patient_identity(me, 101)
    p9.validate_patient_identity({"roles": ["PATIENT"], "patient": {"patient_id": 101}}, 101)


def test_patient_receipt_and_nested_privacy():
    body = {"blockchain_verification": {"status": "CONFIRMED", "confirmed_at": "2026-10-04"}}
    p9.validate_patient_evidence(body)
    body["result_snapshots"] = [{"last_error": "PRIVATE"}]
    with pytest.raises(p9.ValidationError):
        p9.validate_patient_evidence(body)


def test_state_file_is_exclusive_and_no_uncertain_replay(tmp_path):
    path = tmp_path / "run.json"
    journal = p9.Journal(path, create=True)
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        p9.Journal(path, create=True)
    journal.data["pending"] = "Release"
    journal.save()
    journal.close()
    with pytest.raises(p9.ValidationError, match="uncertain"):
        p9.Journal(path)


@pytest.mark.parametrize("argv", [["--test-revocation"], ["--execute", "--test-revision"],
                                  ["--patient-portal"], ["--execute", "--activate-patient"],
                                  ["--preflight", "--execute"], ["--poll-interval", "nan"]])
def test_subphase_cli_gates(argv):
    with pytest.raises(SystemExit):
        p9.parse_args(argv)


def test_main_defaults_to_preflight_without_a_journal(spec, monkeypatch, tmp_path):
    api = FakeAPI(spec)
    clients = iter([api, FakeSigner(api)])
    monkeypatch.setattr(p9, "Client", lambda *a, **kw: next(clients))
    path = tmp_path / "must-not-exist.json"
    assert p9.main(["--signer-login", "--state-file", str(path)]) == 0
    assert not path.exists()
    assert all(method == "GET" for method, _, _ in api.calls)


def test_execute_blocked_before_patient_when_signer_unlinked(spec, monkeypatch):
    api = FakeAPI(spec, execute=True)
    monkeypatch.setattr(api, "login", lambda *a: {**ME, "staff": None})
    monkeypatch.setattr(p9, "Client", lambda *a, **kw: api)
    assert p9.main(["--execute"]) == 1
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.parametrize("change", ["missing", "same_user", "admin", "broad", "missing_permission", "inactive"])
def test_separate_signer_required(spec, change):
    signer = deepcopy(SIGNER)
    if change == "missing":
        signer = None
    elif change == "same_user":
        signer["user_id"] = ME["user_id"]
    elif change == "admin":
        signer["roles"] = ["SYSTEM_ADMIN"]
    elif change == "broad":
        signer["permissions"].append("ACCOUNT_CREATE")
    elif change == "missing_permission":
        signer["permissions"] = []
    else:
        signer["account_status"] = "INACTIVE"
    api = FakeAPI(spec)
    assert not p9.preflight(api, ME, signer, p9.parse_args([]))[0]
    assert all(method == "GET" for method, _, _ in api.calls)


def test_signer_permission_change_blocks_signing(run, monkeypatch):
    runner, api, _ = run
    original = api.request
    def changed(method, path, *args, **kwargs):
        body = original(method, path, *args, **kwargs)
        if method == "POST" and path.endswith("/signatories"):
            runner.signer.identity["permissions"].append("REPORT_APPROVE")
        return body
    monkeypatch.setattr(api, "request", changed)
    with pytest.raises(p9.ValidationError, match="exactly REPORT_SIGN"):
        runner.baseline()
    assert runner.signer.calls == []
    assert not any(path.endswith("/approve") for _, path, _ in api.calls)


@pytest.mark.parametrize("action", ["revoke", "revise"])
def test_later_lifecycle_requires_baseline_and_typed_confirmation(run, monkeypatch, action):
    runner, api, journal = run
    with pytest.raises(p9.ValidationError, match="previously confirmed"):
        runner.lifecycle_test(action)
    runner.baseline()
    journal.data["baseline_pass"] = True
    api.calls.clear()
    monkeypatch.setattr("builtins.input", lambda _: "incorrect")
    with pytest.raises(p9.ValidationError, match="confirmation"):
        runner.lifecycle_test(action)
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.parametrize("action", ["revoke", "revise"])
def test_later_lifecycle_synthetic_target_and_both_evidence_views(run, monkeypatch, action):
    runner, api, journal = run
    runner.baseline()
    journal.data["baseline_pass"] = True
    monkeypatch.setattr("builtins.input", lambda _: runner.run_id)
    monkeypatch.setattr(p9, "Client", lambda base: api)
    runner.lifecycle_test(action)
    assert api.reports[106]["report_status"] == "REVOKED"
    if action == "revise":
        assert runner.ids["revision_report_id"] == 108
        assert api.reports[108]["report_status"] == "RELEASED"
        assert "supersession" in api.reports[106]["anchoring"]
    else:
        assert "revocation" in api.reports[106]["anchoring"]


def test_patient_portal_stops_wrong_owner_before_report_access(run, monkeypatch):
    runner, api, journal = run
    runner.baseline()
    journal.data["baseline_pass"] = True
    patient = FakeAPI(api.spec)
    monkeypatch.setattr(patient, "login", lambda *a, **kw: {"roles": ["PATIENT"], "patient": {"patient_id": 999}})
    patient.masters["/patient/security"] = {"mfa_required": False}
    monkeypatch.setattr(p9, "Client", lambda *a, **kw: patient)
    with pytest.raises(p9.ValidationError, match="ownership"):
        runner.patient_portal()
    assert not any("/patient/reports" in path for _, path, _ in patient.calls)
    assert all(method == "GET" for method, _, _ in patient.calls)


def test_patient_mfa_enrollment_is_not_bypassed(run, monkeypatch):
    runner, api, journal = run
    runner.baseline()
    journal.data["baseline_pass"] = True
    patient = FakeAPI(api.spec)
    monkeypatch.setattr(patient, "login", lambda *a, **kw: {"roles": ["PATIENT"], "patient": None})
    patient.masters["/patient/security"] = {"mfa_required": True, "totp_enabled": False, "mfa_verified_for_current_session": False}
    monkeypatch.setattr(p9, "Client", lambda *a, **kw: patient)
    with pytest.raises(p9.ValidationError, match="MFA enrollment"):
        runner.patient_portal()
    assert all(method == "GET" for method, _, _ in patient.calls)


def test_patient_portal_success_uses_only_owned_report(run, monkeypatch):
    runner, api, journal = run
    runner.baseline()
    journal.data["baseline_pass"] = True
    patient = FakeAPI(api.spec)
    monkeypatch.setattr(patient, "login", lambda *a, **kw: {"roles": ["PATIENT"], "patient": {"patient_id": 101}})
    patient.masters.update({
        "/patient/security": {"mfa_required": True, "totp_enabled": True, "mfa_verified_for_current_session": True},
        "/patient/me": {"patient_id": 101, "patient_code": runner.run_id},
        "/patient/reports/106": {"report_id": 106, "report_status": "RELEASED", "verification_status": "AUTHENTIC",
                                 "patient_snapshot": {"patient_code": runner.run_id},
                                 "blockchain_verification": {"status": "CONFIRMED", "confirmed_at": "2026-10-04T00:00:00"}},
    })
    monkeypatch.setattr(p9, "Client", lambda *a, **kw: patient)
    runner.patient_portal()
    assert [path for _, path, _ in patient.calls] == [p9.API + suffix for suffix in
        ("/patient/security", "/patient/me", "/patient/reports/106")]
