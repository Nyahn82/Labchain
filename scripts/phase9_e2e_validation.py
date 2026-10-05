#!/usr/bin/env python3
"""Opt-in synthetic LIS validation. No app imports, SQL, or Fabric client.

See docs/PHASE_9_E2E_VALIDATION.md before using --execute. Network mutations
are never retried. Local journals contain only synthetic identifiers and state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import getpass
import http.cookiejar
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings


API = "/api/v1"
BASE = "https://labchain.online"
STATES = {"NOT_ANCHORED", "PENDING", "PROCESSING", "RETRYING", "CONFIRMED", "FAILED"}
PUBLIC_FIELDS = {"status", "message", "issuing_facility", "report_date", "version",
                 "blockchain_status", "blockchain_confirmed_at"}
READ_PERMISSIONS = {
    "PATIENT_READ", "LAB_ORDER_READ", "SPECIMEN_READ", "LAB_RESULT_READ", "REPORT_READ",
    "LAB_MASTER_READ", "FACILITY_PROFILE_READ", "REFERRING_FACILITY_READ", "PHYSICIAN_READ",
    "STAFF_READ", "SIGNATORY_READ", "REPORT_TEMPLATE_READ", "BLOCKCHAIN_STATUS_VIEW",
}
WRITE_PERMISSIONS = {
    "PATIENT_CREATE", "LAB_ORDER_CREATE", "SPECIMEN_REGISTER", "SPECIMEN_COLLECT",
    "SPECIMEN_RECEIVE", "LAB_RESULT_ENTER", "LAB_RESULT_REVIEW", "LAB_RESULT_VERIFY",
    "REPORT_GENERATE", "SIGNATORY_MANAGE", "REPORT_APPROVE", "REPORT_RELEASE",
}
# Exact routes inspected in app/api and services. Paths below omit /api/v1.
CONTRACTS = [
    ("post", "/patients", "PatientCreate"),
    ("post", "/lab-orders", "OrderCreate"),
    ("post", "/lab-orders/{order_id}/specimens", "SpecimenCreate"),
    ("post", "/specimens/{specimen_id}/collect", None),
    ("post", "/specimens/{specimen_id}/receive", None),
    ("post", "/lab-order-items/{order_item_id}/result", "ResultCreate"),
    ("post", "/results/{result_item_id}/review", None),
    ("post", "/results/{result_item_id}/verify", None),
    ("post", "/lab-orders/{order_id}/reports", "GenerateRequest"),
    ("post", "/reports/{report_id}/signatories", "AssignRequest"),
    ("post", "/reports/{report_id}/sign", "SignRequest"),
    ("post", "/reports/{report_id}/approve", None),
    ("post", "/reports/{report_id}/release", None),
]
READ_ROUTES = [
    "/health", "/ready", "/auth/me", "/facility-profile", "/lab/departments/{department_id}",
    "/lab/sample-types/{sample_type_id}", "/lab/tests/{test_id}",
    "/lab/tests/{test_id}/sample-types", "/referring-facilities/{referring_facility_id}",
    "/physicians/{physician_id}", "/staff/{staff_id}", "/signatories/{signatory_id}",
    "/report-templates/{template_id}", "/patients/{patient_id}", "/lab-orders/{order_id}",
    "/specimens/{specimen_id}", "/results/{result_item_id}", "/reports/{report_id}",
    "/reports/{report_id}/verification", "/blockchain/status", "/verify/{verification_token}",
]
PLAN = (
    "PatientCreate: synthetic patient; DOB, contacts and other personal information omitted",
    "OrderCreate: ROUTINE, physician 1, test_ids=[1], panel_ids=[] -> REQUESTED",
    "Payment: SKIP (not a processing or release prerequisite; no financial record)",
    "SpecimenCreate: sample type 1 + returned order_item_id -> PENDING; order IN_PROGRESS",
    "Collect -> COLLECTED; receive -> RECEIVED (no separate acceptance operation)",
    "ResultCreate: result_value='42', returned specimen_id -> DRAFT; specimen PROCESSED",
    "Review -> REVIEWED; verify -> VERIFIED; item and order COMPLETED",
    "Generate with template 1 -> GENERATED; assign signatory 1 as LAB_IN_CHARGE",
    "Linked staff user signs -> signed_at; approve -> APPROVED; release -> RELEASED",
    "Poll staff report anchoring -> CONFIRMED via existing worker; compare queue counts",
    "Check public verification with an anonymous client; token never logged",
    "Patient portal: SKIP unless separately requested; no default activation",
)


class ValidationError(Exception):
    """Only trusted, non-secret messages may be passed to this exception."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def obj(value):
    require(isinstance(value, dict), "Unexpected response structure; stopping.")
    return value


def identifier(value):
    require(type(value) is int and 0 < value <= 9223372036854775807,
            "Missing or invalid response identifier; stopping.")
    return value


def matches(body, **expected):
    body = obj(body)
    require(all(key in body and type(body[key]) is type(value) and body[key] == value
                for key, value in expected.items()), "Response identity/state differs from the planned workflow.")
    return body


def emit(status, message):
    print(f"[{status}] {message}", flush=True)


def hidden_input(prompt):
    # getpass normally falls back to echoed stdin without a terminal. Fail closed.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise ValidationError("A secure interactive terminal is required for credentials.") from None


def timestamp_valid(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never resend credentials/CSRF or transform a POST into a GET.
        return None


class Client:
    def __init__(self, base=BASE, *, execute=False, session_cookie="rhu_session",
                 csrf_cookie="rhu_csrf", opener=None):
        parsed = urllib.parse.urlsplit(base)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and parsed.path in ("", "/")
                and not parsed.query and not parsed.fragment, "Base URL must be an HTTPS origin.")
        self.base = base.rstrip("/")
        self.execute = execute
        self.session_cookie = session_cookie
        self.csrf_cookie = csrf_cookie
        self.jar = http.cookiejar.CookieJar()
        self.opener = opener or urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method, path, payload=None, *, expected=(200,), timeout=30):
        require(path.startswith("/") and not path.startswith("//")
                and not urllib.parse.urlsplit(path).netloc, "Only relative API paths are allowed.")
        auth = path in {API + "/auth/login", API + "/auth/mfa/verify", API + "/auth/mfa/recovery"}
        unsafe = method not in {"GET", "HEAD", "OPTIONS"}
        require(not unsafe or auth or self.execute, "Workflow writes require --execute.")
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if unsafe:
            headers["Origin"] = self.base
            if not auth and path != API + "/patient/activate":
                # Select the cookie applicable to this origin/path, not another domain.
                probe = urllib.request.Request(self.base + path)
                self.jar.add_cookie_header(probe)
                from http.cookies import SimpleCookie
                cookies = SimpleCookie(probe.get_header("Cookie", ""))
                token = cookies.get(self.csrf_cookie)
                require(token is not None and token.value, "CSRF cookie unavailable; no write sent.")
                headers["X-CSRF-Token"] = token.value
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        # One attempt only, including transport failures and uncertain write outcomes.
        try:
            with self.opener.open(req, timeout=timeout) as response:
                status = response.status
                require(status in expected, "Unexpected HTTP success status; stopping.")
                raw = response.read(4 * 1024 * 1024 + 1)
                require(len(raw) <= 4 * 1024 * 1024, "Response exceeded the safe size limit.")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise ValidationError(f"HTTP {code}; response body withheld; request was not retried.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValidationError("Network request failed; outcome may be uncertain; request was not retried.") from None
        except (ValueError, UnicodeError):
            raise ValidationError("Invalid JSON response; request was not retried.") from None

    def get(self, path, **kwargs):
        return self.request("GET", API + path, **kwargs)

    def login(self, label="Staff", *, username=None, password=None):
        if username is None:
            username = input(f"{label} username: ").strip()
        if password is None:
            password = hidden_input(f"{label} password: ")
        try:
            body = obj(self.request("POST", API + "/auth/login",
                                    {"username": username, "password": password}, expected=(200, 202)))
        finally:
            password = None
        if body.get("mfa_required") is True:
            method = input("MFA method [totp/recovery]: ").strip().lower()
            require(method in {"totp", "recovery"}, "Choose a supported MFA method.")
            secret = hidden_input("MFA code (hidden): ")
            try:
                route, field = ("verify", "code") if method == "totp" else ("recovery", "recovery_code")
                self.request("POST", API + "/auth/mfa/" + route, {field: secret})
            finally:
                secret = None
        require(any(c.name == self.session_cookie and not c.is_expired() for c in self.jar),
                "Login did not issue a usable session cookie.")
        me = obj(self.get("/auth/me"))
        matches(me, account_status="ACTIVE")
        identifier(me.get("user_id"))
        emit("PASS", f"{label} authenticated; credential and cookie values withheld.")
        return me


def permitted(me, names):
    return "SYSTEM_ADMIN" in me.get("roles", []) or names <= set(me.get("permissions", []))


def signer_ready(me, operator):
    require(isinstance(me, dict), "Separate signer login required; use --signer-login.")
    matches(me, account_status="ACTIVE")
    require(identifier(me.get("user_id")) != identifier(operator.get("user_id")),
            "Operator and signer must be separate identities.")
    roles = me.get("roles")
    require(isinstance(roles, list) and len(roles) == 1
            and roles[0] not in {"SYSTEM_ADMIN", "PATIENT"}, "Signer must have one non-admin signing role.")
    require(isinstance(me.get("permissions"), list) and set(me["permissions"]) == {"REPORT_SIGN"},
            "Signer must have exactly REPORT_SIGN permission.")
    require(me.get("patient") is None, "Signer must not have a patient identity.")
    require(isinstance(me.get("staff"), dict) and me["staff"].get("staff_id") == 1
            and me["staff"].get("staff_code") == "P9SIGN01",
            "Signer is not linked to staff 1. Provision a linked account through the supported "
            "staff-account API, then use --signer-login. SYSTEM_ADMIN cannot bypass signing identity.")


def check_contracts(spec, *, revocation=False, revision=False, portal=False, activation=False):
    paths = obj(spec).get("paths", {})
    contracts = list(CONTRACTS)
    if revocation:
        contracts.append(("post", "/reports/{report_id}/revoke", "RevokeRequest"))
    if revision:
        contracts.append(("post", "/reports/{report_id}/revise", "GenerateRequest"))
    if activation:
        contracts.extend([("post", "/patients/{patient_id}/activation-token", None),
                          ("post", "/patient/activate", "ActivationRequest")])
    reads = READ_ROUTES + (["/patient/me", "/patient/reports/{report_id}", "/patient/security"] if portal else [])
    for route in reads:
        require("get" in paths.get(API + route, {}), f"Required GET route missing: {route}")
    for method, route, schema in contracts:
        operation = paths.get(API + route, {}).get(method)
        require(isinstance(operation, dict), f"Required {method.upper()} route missing: {route}")
        body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        require((body.get("$ref", "").split("/")[-1] == schema) if schema else not body,
                f"Request schema changed for {route}; review before executing.")
    # Check payload fields against deployed OpenAPI, including required/enums/bounds.
    schemas = obj(spec.get("components", {})).get("schemas", {})
    samples = {
        "PatientCreate": {"patient_code": "P9-260101120000-ABC", "first_name": "Phase9", "last_name": "Validation-P9-260101120000-ABC"},
        "OrderCreate": {"patient_id": 1, "physician_id": 1, "priority": "ROUTINE", "test_ids": [1], "panel_ids": [], "request_reason": "Synthetic validation"},
        "SpecimenCreate": {"sample_type_id": 1, "order_item_ids": [1], "remarks": "Synthetic validation"},
        "ResultCreate": {"result_value": "42", "specimen_id": 1, "remarks": "Synthetic validation"},
        "GenerateRequest": {"template_id": 1, "remarks": "Synthetic validation"},
        "AssignRequest": {"signatory_id": 1, "signatory_type": "LAB_IN_CHARGE", "sort_order": 1},
        "SignRequest": {"report_signatory_id": 1},
    }
    for name, payload in samples.items():
        require(name in schemas, "A required workflow schema is unavailable.")
        validate_payload(payload, schemas[name], schemas)


def validate_payload(value, schema, schemas):
    """Validate the OpenAPI constraints used by our fixed payloads; server remains authoritative."""
    if "$ref" in schema:
        schema = schemas[schema["$ref"].split("/")[-1]]
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                validate_payload(value, branch, schemas)
                return
            except ValidationError:
                pass
        raise ValidationError("Planned payload is incompatible with deployed schema.")
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in types:
        require(type(value) is types[kind], "Planned payload type is incompatible with deployed schema.")
    if kind == "null":
        require(value is None, "Planned payload must be null.")
    if "enum" in schema:
        require(value in schema["enum"], "Planned enum is incompatible with deployed schema.")
    if kind == "object":
        props = schema.get("properties", {})
        require(set(schema.get("required", [])) <= value.keys(), "Planned payload lacks required fields.")
        require(set(value) <= props.keys(), "Planned payload includes unsupported fields.")
        for key, item in value.items():
            validate_payload(item, props[key], schemas)
    if kind in {"string", "array"}:
        low, high = ("minLength", "maxLength") if kind == "string" else ("minItems", "maxItems")
        require(schema.get(low, 0) <= len(value) <= schema.get(high, float("inf")), "Planned payload length is invalid.")
    if kind == "array":
        for item in value:
            validate_payload(item, schema.get("items", {}), schemas)
    if kind == "integer":
        require(schema.get("minimum", -float("inf")) <= value <= schema.get("maximum", float("inf"))
                and value > schema.get("exclusiveMinimum", -float("inf")), "Planned identifier/sort order is invalid.")
    if kind == "string" and "pattern" in schema:
        require(re.search(schema["pattern"], value) is not None, "Planned string format is invalid.")


def queue_status(client):
    body = obj(client.get("/blockchain/status"))
    counts = obj(body.get("counts"))
    require(all(type(counts.get(k)) is int and counts[k] >= 0
                for k in ("pending", "processing", "confirmed", "failed", "dead")), "Invalid queue counts.")
    require(body.get("worker_health") in {"IDLE", "ACTIVE", "DEGRADED", "ERROR"}, "Invalid queue-derived state.")
    result = {k: counts[k] for k in ("pending", "processing", "confirmed", "failed", "dead")}
    emit("PASS", "Queue counts: " + json.dumps(result, sort_keys=True))
    emit("INFO", "Queue-derived state: " + body["worker_health"] + "; this is not worker or Fabric liveness.")
    if body.get("delivery_enabled") is None:
        emit("INFO", "Worker enablement is not reported by this API.")
    return result


def preflight(client, me, signer_me, args):
    failures = []

    def check(label, action):
        try:
            result = action()
            emit("PASS", label)
            return result
        except ValidationError as exc:
            failures.append(str(exc))
            emit("FAIL", label + ": " + str(exc))

    check("API health", lambda: matches(client.get("/health"), status="ok"))
    def ready():
        body = matches(client.get("/ready"), status="ready")
        matches(body.get("mysql"), connected=True, database="rhu_labchain")
    check("API/MySQL readiness", ready)
    check("Deployed routes and request schemas", lambda: check_contracts(
        client.request("GET", "/openapi.json"), revocation=args.test_revocation,
        revision=args.test_revision, portal=args.patient_portal, activation=args.activate_patient))
    permissions = READ_PERMISSIONS | WRITE_PERMISSIONS
    if args.test_revocation:
        permissions |= {"REPORT_REVOKE"}
    if args.test_revision:
        permissions |= {"REPORT_REVISE"}
    if args.activate_patient:
        permissions |= {"PATIENT_ACCOUNT_ACTIVATE"}
    check("Operator permissions", lambda: require(permitted(me, permissions), "Operator lacks required workflow permissions."))
    check("Staff role for global status", lambda: require(
        bool(set(me.get("roles", [])) & {"SYSTEM_ADMIN", "LAB_STAFF", "LAB_SUPERVISOR", "DOCTOR"})
        and "PATIENT" not in me.get("roles", []), "Use a staff-only operator account."))
    masters = [
        ("/facility-profile", {"facility_id": 1, "facility_name": "Phase 9 Validation Laboratory"}),
        ("/lab/departments/1", {"department_id": 1, "department_code": "P9LAB", "is_active": True}),
        ("/lab/sample-types/1", {"sample_type_id": 1, "sample_name": "Whole Blood (Phase 9 Validation)", "is_active": True}),
        ("/lab/tests/1", {"test_id": 1, "test_code": "P9NUM", "department_id": 1, "result_type": "NUMERIC", "default_unit": "unit", "is_active": True}),
        ("/referring-facilities/1", {"referring_facility_id": 1, "facility_name": "Phase 9 Validation Referral Facility"}),
        ("/physicians/1", {"physician_id": 1, "first_name": "Phase", "last_name": "Nine Validation", "referring_facility_id": 1, "is_active": True}),
        ("/staff/1", {"staff_id": 1, "staff_code": "P9SIGN01", "is_active": True}),
        ("/signatories/1", {"signatory_id": 1, "staff_id": 1, "is_active": True}),
        ("/report-templates/1", {"template_id": 1, "template_code": "P9REPORT", "panel_id": None,
                                 "footer_note": "Not for clinical use.", "is_active": True}),
    ]
    for path, expected in masters:
        check("Master data " + path, lambda p=path, e=expected: matches(client.get(p), **e))
    def assignment():
        rows = client.get("/lab/tests/1/sample-types")
        require(isinstance(rows, list) and any(isinstance(r, dict) and r.get("test_id") == 1
                and r.get("sample_type_id") == 1 and r.get("is_default") is True for r in rows),
                "Test 1 lacks the default sample type 1 assignment.")
    check("Test/sample compatibility", assignment)
    check("Signatory account identity", lambda: signer_ready(signer_me, me))
    counts = check("Staff blockchain telemetry", lambda: queue_status(client))
    for index, step in enumerate(PLAN, 1):
        emit("INFO", f"Plan {index}: {step}")
    emit("INFO", "Preflight performs GETs plus authentication/session bookkeeping only; no workflow writes.")
    emit("INFO", "PDF storage and worker execution can only be proven during a later authorized baseline.")
    return not failures, counts


class Journal:
    """Exclusive file + process lock; intent is fsynced before every workflow write.

    No recovery guesses: pending writes or incomplete baseline writes require
    manual API reconciliation. --resume-state only resumes released-report reads.
    """
    def __init__(self, path, *, base=BASE, create=False):
        self.path = Path(path)
        if create:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if create else 0)
        fd = os.open(self.path, flags, 0o600)
        self.file = os.fdopen(fd, "r+", encoding="utf-8")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if create:
                self.data = {"version": 1, "base": base, "run_id": new_run_id(), "ids": {},
                             "completed": [], "pending": None, "baseline_pass": False}
                self.save()
            else:
                self.data = json.load(self.file)
                require(self.data.get("version") == 1 and self.data.get("base") == base,
                        "Journal version or target origin does not match.")
                require(re.fullmatch(r"P9-\d{12}-[A-F0-9]{3}", self.data.get("run_id", "")), "Invalid run identifier.")
                require(self.data.get("pending") is None, "Journal has an uncertain write; reconcile manually. No writes replayed.")
                for key, value in obj(self.data.get("ids")).items():
                    require(key in ID_KEYS, "Unexpected journal identifier.")
                    identifier(value)
        except Exception:
            self.file.close()
            raise

    def save(self):
        self.file.seek(0)
        json.dump(self.data, self.file, indent=2)
        self.file.truncate()
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self):
        self.file.close()


ID_KEYS = {"patient_id", "order_id", "order_item_id", "specimen_id", "result_item_id",
           "report_id", "report_signatory_id", "revision_report_id", "revision_signatory_id"}


def new_run_id():
    # 19 characters: fits PatientCreate.patient_code's 20-character maximum.
    return datetime.now(timezone.utc).strftime("P9-%y%m%d%H%M%S-") + secrets.token_hex(2)[:3].upper()


class Runner:
    def __init__(self, client, signer, journal, *, timeout=300, interval=10, clock=time.monotonic, sleep=time.sleep):
        self.client, self.signer, self.journal = client, signer, journal
        self.timeout, self.interval, self.clock, self.sleep = timeout, interval, clock, sleep
        self.ids = journal.data["ids"]
        self.run_id = journal.data["run_id"]
        self.note = "Synthetic Phase 9 validation only; not for clinical use. " + self.run_id

    def write(self, step, path, payload, validate, *, expected=200, client=None):
        require(self.client.execute, "Workflow writes require --execute.")
        require(self.journal.data.get("pending") is None and step not in self.journal.data["completed"],
                "Write already attempted or completed; automatic replay refused.")
        self.journal.data["pending"] = step
        self.journal.save()
        body = (client or self.client).request("POST", API + path, payload, expected=(expected,))
        validate(body)  # Leave pending on invalid response, even if the server committed.
        self.journal.data["completed"].append(step)
        self.journal.data["pending"] = None
        self.journal.save()
        emit("PASS", step)
        return body

    def capture(self, key, body, field=None):
        self.ids[key] = identifier(obj(body).get(field or key))

    def patient(self):
        return matches(self.client.get(f"/patients/{self.ids['patient_id']}"),
                       patient_id=self.ids["patient_id"], patient_code=self.run_id,
                       first_name="Phase9", last_name="Validation-" + self.run_id)

    def order(self, state=None):
        self.patient()
        body = matches(self.client.get(f"/lab-orders/{self.ids['order_id']}"),
                       order_id=self.ids["order_id"], patient_id=self.ids["patient_id"],
                       physician_id=1, request_reason=self.note)
        if state:
            matches(body, status=state)
        items = body.get("items")
        require(isinstance(items, list) and len(items) == 1 and body.get("panels") == [], "Unexpected order composition.")
        matches(items[0], order_item_id=self.ids["order_item_id"], test_id=1, order_id=self.ids["order_id"], order_panel_id=None)
        if state:
            matches(items[0], status=state)
        return body

    def specimen(self, state):
        self.order("IN_PROGRESS")
        body = matches(self.client.get(f"/specimens/{self.ids['specimen_id']}"),
                       specimen_id=self.ids["specimen_id"], order_id=self.ids["order_id"],
                       sample_type_id=1, specimen_status=state, remarks=self.note)
        mappings = body.get("mappings")
        require(isinstance(mappings, list) and len(mappings) == 1
                and mappings[0].get("order_item_id") == self.ids["order_item_id"], "Specimen mapping mismatch.")
        return body

    def result(self, state):
        self.order("IN_PROGRESS" if state != "VERIFIED" else "COMPLETED")
        return matches(self.client.get(f"/results/{self.ids['result_item_id']}"),
                       result_item_id=self.ids["result_item_id"], order_id=self.ids["order_id"],
                       order_item_id=self.ids["order_item_id"], specimen_id=self.ids["specimen_id"],
                       status=state, result_value="42", remarks=self.note)

    def report(self, state, *, key="report_id"):
        self.order("COMPLETED")
        body = self.client.get(f"/reports/{self.ids[key]}")
        return self.check_report(body, state, key=key)

    def check_report(self, body, state, *, key="report_id"):
        matches(body, report_id=self.ids[key], order_id=self.ids["order_id"], report_status=state,
                template_id=1, facility_id=1, remarks=self.note)
        matches(body.get("patient_snapshot"), patient_code=self.run_id, patient_name="Phase9 Validation-" + self.run_id)
        lines = body.get("result_snapshots")
        require(isinstance(lines, list) and len(lines) == 1, "Report snapshot count differs from the run.")
        matches(lines[0], result_item_id=self.ids["result_item_id"], result_value_snapshot="42", panel_id_snapshot=None)
        return body

    def baseline(self):
        require(not self.ids and not self.journal.data["completed"], "New baseline requires an unused journal.")
        def created_patient(body):
            matches(body, patient_code=self.run_id, first_name="Phase9", last_name="Validation-" + self.run_id)
            self.capture("patient_id", body)
        self.write("Patient", "/patients", {"patient_code": self.run_id, "first_name": "Phase9",
                   "last_name": "Validation-" + self.run_id}, created_patient, expected=201)
        self.patient()
        def created_order(body):
            matches(body, patient_id=self.ids["patient_id"], status="REQUESTED", physician_id=1, request_reason=self.note)
            self.capture("order_id", body)
            require(isinstance(body.get("items"), list) and len(body["items"]) == 1 and body.get("panels") == [], "Unexpected new order composition.")
            matches(body["items"][0], test_id=1, order_id=self.ids["order_id"], status="REQUESTED", order_panel_id=None)
            self.capture("order_item_id", body["items"][0])
        self.write("Order", "/lab-orders", {"patient_id": self.ids["patient_id"], "physician_id": 1,
                   "priority": "ROUTINE", "test_ids": [1], "panel_ids": [], "request_reason": self.note}, created_order, expected=201)
        self.order("REQUESTED")
        emit("SKIP", "Payment: no payment gate in the supported workflow; no financial record created.")
        def created_specimen(body):
            matches(body, order_id=self.ids["order_id"], sample_type_id=1, specimen_status="PENDING", remarks=self.note)
            self.capture("specimen_id", body)
        self.write("Specimen", f"/lab-orders/{self.ids['order_id']}/specimens",
                   {"sample_type_id": 1, "order_item_ids": [self.ids["order_item_id"]], "remarks": self.note},
                   created_specimen, expected=201)
        for step, action, before, after in [("Collection", "collect", "PENDING", "COLLECTED"),
                                            ("Receipt", "receive", "COLLECTED", "RECEIVED")]:
            self.specimen(before)
            self.write(step, f"/specimens/{self.ids['specimen_id']}/{action}", None,
                       lambda b, s=after: matches(b, specimen_id=self.ids["specimen_id"], order_id=self.ids["order_id"], specimen_status=s))
        self.specimen("RECEIVED")
        def created_result(body):
            matches(body, order_id=self.ids["order_id"], order_item_id=self.ids["order_item_id"],
                    specimen_id=self.ids["specimen_id"], status="DRAFT", result_value="42", remarks=self.note)
            self.capture("result_item_id", body)
        self.write("Result", f"/lab-order-items/{self.ids['order_item_id']}/result",
                   {"result_value": "42", "specimen_id": self.ids["specimen_id"], "remarks": self.note}, created_result, expected=201)
        self.specimen("PROCESSED")
        for step, action, before, after in [("Review", "review", "DRAFT", "REVIEWED"),
                                            ("Verification", "verify", "REVIEWED", "VERIFIED")]:
            self.result(before)
            self.write(step, f"/results/{self.ids['result_item_id']}/{action}", None,
                       lambda b, s=after: matches(b, result_item_id=self.ids["result_item_id"], order_id=self.ids["order_id"], status=s))
        self.result("VERIFIED")
        def generated(body):
            self.capture("report_id", body)
            self.check_report(body, "GENERATED")
        self.write("Report generation", f"/lab-orders/{self.ids['order_id']}/reports",
                   {"template_id": 1, "remarks": self.note}, generated, expected=201)
        self.sign_approve_release()

    def sign_approve_release(self, *, revision=False):
        key = "revision_report_id" if revision else "report_id"
        assignment_key = "revision_signatory_id" if revision else "report_signatory_id"
        prefix = "Revision " if revision else ""
        report_id = self.ids[key]
        self.report("GENERATED", key=key)
        signer_ready(obj(self.signer.get("/auth/me")), obj(self.client.get("/auth/me")))
        def assigned(body):
            matches(body, report_id=report_id, signatory_id=1, signatory_type="LAB_IN_CHARGE", signed_at=None)
            self.capture(assignment_key, body, "report_signatory_id")
        self.write(prefix + "Signatory", f"/reports/{report_id}/signatories",
                   {"signatory_id": 1, "signatory_type": "LAB_IN_CHARGE", "sort_order": 1}, assigned, expected=201)
        current = self.report("GENERATED", key=key)
        require(any(s.get("report_signatory_id") == self.ids[assignment_key] and s.get("signed_at") is None
                    for s in current.get("signatories", [])), "Unsigned assignment not found.")
        signer_ready(obj(self.signer.get("/auth/me")), obj(self.client.get("/auth/me")))
        def signed(body):
            matches(body, report_signatory_id=self.ids[assignment_key], report_id=report_id, signatory_id=1)
            require(timestamp_valid(body.get("signed_at")), "Signature timestamp missing or invalid.")
        self.write(prefix + "Signature", f"/reports/{report_id}/sign",
                   {"report_signatory_id": self.ids[assignment_key]}, signed, client=self.signer)
        current = self.report("GENERATED", key=key)
        require(current.get("signatories") and all(s.get("signed_at") for s in current["signatories"]), "Unsigned report cannot be approved.")
        self.write(prefix + "Approval", f"/reports/{report_id}/approve", None,
                   lambda b: self.check_report(b, "APPROVED", key=key))
        self.report("APPROVED", key=key)
        self.write(prefix + "Release", f"/reports/{report_id}/release", None,
                   lambda b: self.check_report(b, "RELEASED", key=key))

    def poll(self, *, key="report_id", event="release", report_state="RELEASED"):
        deadline = self.clock() + self.timeout
        previous = None
        while True:
            remaining = deadline - self.clock()
            require(remaining > 0, "Blockchain confirmation timed out; no writes retried. Resume released-report checks later.")
            body = self.check_report(self.client.get(f"/reports/{self.ids[key]}", timeout=min(30, remaining)), report_state, key=key)
            anchor = obj(body.get("anchoring"))
            receipt = obj(anchor.get(event))
            status = receipt.get("status")
            require(status in STATES, "Unknown anchoring status; stopping.")
            if status != previous:
                emit("INFO", "Anchoring " + event + ": " + status)
                previous = status
            require(status not in {"FAILED", "NOT_ANCHORED"}, "Anchoring requires investigation; no retry/submission attempted.")
            if status == "CONFIRMED":
                require(anchor.get("status") == "CONFIRMED", "Other lifecycle evidence is not confirmed.")
                require(timestamp_valid(receipt.get("confirmed_at"))
                        and isinstance(receipt.get("transaction_id"), str)
                        and re.fullmatch(r"[0-9a-f]{64}", receipt["transaction_id"]) is not None,
                        "Confirmed receipt lacks valid staff evidence.")
                block = receipt.get("block_number")
                require(block is None or type(block) is int and block >= 0, "Invalid block number.")
                safe = {k: receipt.get(k) for k in ("status", "confirmed_at", "transaction_id", "block_number")}
                emit("PASS", "Staff anchoring receipt: " + json.dumps(safe, sort_keys=True))
                return safe
            remaining = deadline - self.clock()
            if remaining > 0:
                self.sleep(min(self.interval, remaining))

    def public_check(self, *, key="report_id", status="VERIFIED"):
        meta = obj(self.client.get(f"/reports/{self.ids[key]}/verification"))
        require(meta.get("verification_status") == ("AUTHENTIC" if status == "VERIFIED" else "REVOKED"), "Staff verification status mismatch.")
        url = urllib.parse.urlsplit(meta.get("verification_url", ""))
        origin = urllib.parse.urlsplit(self.client.base)
        require((url.scheme, url.netloc) == (origin.scheme, origin.netloc) and not url.query and not url.fragment
                and re.fullmatch(r"/api/v1/verify/[A-Za-z0-9_-]{43}", url.path), "Verification URL is not an approved same-origin token URL.")
        public = Client(self.client.base)  # Separate, anonymous cookie jar.
        body = public.request("GET", url.path)
        validate_public(body, status)
        emit("PASS", "Public verification and privacy allowlist; token=[masked].")

    def confirm_baseline(self):
        require("Release" in self.journal.data["completed"], "Resume requires a recorded successful release; earlier writes need manual reconciliation.")
        self.report("RELEASED")
        receipt = self.poll()
        self.public_check()
        after = queue_status(self.client)
        before = self.journal.data.get("counts_before")
        require(isinstance(before, dict), "Queue baseline missing from journal.")
        emit("INFO", "Queue delta (shared queue; not attributed solely to this run): "
             + json.dumps({k: after[k] - before[k] for k in after}, sort_keys=True))
        self.journal.data.update(baseline_pass=True, receipt=receipt, counts_after=after)
        self.journal.save()

    def lifecycle_test(self, action):
        require(self.journal.data.get("baseline_pass") is True, "Lifecycle tests require a previously confirmed baseline journal.")
        self.report("RELEASED")
        self.poll()
        require(input(f"Type {self.run_id} to {action} this synthetic report: ").strip() == self.run_id,
                "Lifecycle confirmation did not match; no write sent.")
        self.report("RELEASED")
        if action == "revoke":
            self.write("Revocation", f"/reports/{self.ids['report_id']}/revoke", {"reason": self.note},
                       lambda b: self.check_report(b, "REVOKED"))
            self.poll(event="revocation", report_state="REVOKED")
            self.public_check(status="REVOKED")
        else:
            def revised(body):
                self.capture("revision_report_id", body, "report_id")
                self.check_report(body, "GENERATED", key="revision_report_id")
                matches(body, supersedes_report_id=self.ids["report_id"])
            self.write("Revision generation", f"/reports/{self.ids['report_id']}/revise",
                       {"template_id": 1, "remarks": self.note}, revised, expected=201)
            self.sign_approve_release(revision=True)
            self.poll(key="revision_report_id")
            self.poll(event="supersession", report_state="REVOKED")
            self.public_check(key="revision_report_id")
            self.public_check(status="REVOKED")
        queue_status(self.client)

    def patient_portal(self, *, activate=False):
        require(self.client.execute and self.journal.data.get("baseline_pass"), "Patient checks require an explicit execution and confirmed baseline.")
        self.patient()
        self.report("RELEASED")
        patient = Client(self.client.base, execute=activate,
                         session_cookie=self.client.session_cookie, csrf_cookie=self.client.csrf_cookie)
        if activate:
            # Credentials/token are memory-only. No automatic TOTP enrollment or policy bypass.
            username = input("New synthetic patient username: ").strip()
            password = hidden_input("New synthetic patient password (12+ characters): ")
            require(12 <= len(password) <= 1024 and 1 <= len(username) <= 60, "Patient credentials do not meet schema bounds.")
            token_body = self.write("Patient activation token", f"/patients/{self.ids['patient_id']}/activation-token", None,
                                    lambda b: require(isinstance(obj(b).get("activation_token"), str) and b["activation_token"], "Activation token missing."), expected=201)
            try:
                self.write("Patient account activation", "/patient/activate",
                           {"activation_token": token_body["activation_token"], "username": username, "password": password},
                           lambda b: matches(b, account_status="ACTIVE", roles=["PATIENT"]), expected=201, client=patient)
                me = patient.login("Patient", username=username, password=password)
            finally:
                password = None
                token_body = None
        else:
            me = patient.login("Existing synthetic patient")
        require(me.get("roles") == ["PATIENT"], "Portal checks require a separate PATIENT-only session.")
        security = obj(patient.get("/patient/security"))
        require(security.get("mfa_required") is False or security.get("totp_enabled") is True
                and security.get("mfa_verified_for_current_session") is True,
                "Patient MFA enrollment/verification is required. Complete it in the normal portal, then rerun the gated read checks.")
        validate_patient_identity(me, self.ids["patient_id"])
        matches(patient.get("/patient/me"), patient_id=self.ids["patient_id"], patient_code=self.run_id)
        body = obj(patient.get(f"/patient/reports/{self.ids['report_id']}"))
        matches(body, report_id=self.ids["report_id"], report_status="RELEASED", verification_status="AUTHENTIC")
        matches(body.get("patient_snapshot"), patient_code=self.run_id)
        validate_patient_evidence(body)
        emit("PASS", "Patient ownership and safe blockchain confirmation checked with a separate patient session.")


def validate_public(body, status="VERIFIED"):
    body = obj(body)
    require(set(body) <= PUBLIC_FIELDS and all(not isinstance(v, (dict, list)) for v in body.values()),
            "Public response violates the privacy allowlist; contents withheld.")
    matches(body, status=status, blockchain_status="CONFIRMED")
    require(timestamp_valid(body.get("blockchain_confirmed_at")), "Public confirmation timestamp missing or invalid.")


def validate_patient_identity(me, patient_id):
    require(me.get("roles") == ["PATIENT"] and isinstance(me.get("patient"), dict)
            and me["patient"].get("patient_id") == patient_id,
            "Patient session does not belong to this synthetic patient; ownership bypass refused.")


def validate_patient_evidence(body):
    body = obj(body)
    allowed = {"report_id", "report_code", "version_no", "released_at", "order_code", "issuing_facility",
               "verification_status", "report_status", "generated_at", "facility", "patient_snapshot",
               "result_snapshots", "signatories", "blockchain_verification"}
    require(set(body) <= allowed, "Patient response violates the safe report schema; contents withheld.")
    nested = {
        "facility": {"facility_name", "facility_type", "address", "contact_number", "email", "website"},
        "patient_snapshot": {"patient_code", "patient_name", "birth_date", "age_at_report", "sex", "physician_name"},
        "result_snapshots": {"section_name_snapshot", "test_name_snapshot", "result_value_snapshot", "unit_snapshot",
                             "reference_range_snapshot", "flag_snapshot", "sort_order"},
        "signatories": {"staff_name", "signatory_type", "license_number_snapshot", "signed_at", "sort_order"},
        "blockchain_verification": {"status", "confirmed_at"},
    }
    for field, fields in nested.items():
        if field not in body:
            continue
        values = body[field] if field in {"result_snapshots", "signatories"} else [body[field]]
        require(isinstance(values, list), "Patient response has an invalid nested structure.")
        for value in values:
            require(set(obj(value)) <= fields and all(not isinstance(v, (dict, list)) for v in value.values()),
                    "Patient nested response violates its privacy allowlist; contents withheld.")
    forbidden = {"transaction_id", "block_number", "fabric_transaction_id", "fabric_block_number", "source_msp",
                 "source_node", "origin_node_id", "event_uuid", "event_id", "entity_id", "canonical_payload",
                 "lease_token", "last_error", "last_error_code", "worker_error", "msp", "msp_id",
                 "attempt_count", "retry_count", "anchoring"}
    def inspect(value):
        if isinstance(value, dict):
            require(not forbidden.intersection(value), "Patient response contains internal evidence; contents withheld.")
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    inspect(body)
    evidence = obj(body.get("blockchain_verification"))
    require(set(evidence) <= {"status", "confirmed_at"}, "Patient evidence violates the privacy allowlist.")
    matches(evidence, status="CONFIRMED")
    require(timestamp_valid(evidence.get("confirmed_at")), "Patient confirmation timestamp missing or invalid.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true", help="Read-only checks (default; login creates session/audit records)")
    mode.add_argument("--execute", action="store_true", help="Explicitly authorize synthetic workflow writes")
    parser.add_argument("--base-url", default=BASE)
    parser.add_argument("--session-cookie", default="rhu_session")
    parser.add_argument("--csrf-cookie", default="rhu_csrf")
    parser.add_argument("--signer-login", action="store_true", help="Prompt separately for the account linked to staff 1")
    parser.add_argument("--state-file", type=Path, help="New, exclusive journal path; never overwrite an existing run")
    parser.add_argument("--resume-state", type=Path, help="Resume released-report checks only; never replay incomplete writes")
    parser.add_argument("--poll-interval", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=300)
    later = parser.add_mutually_exclusive_group()
    later.add_argument("--test-revocation", action="store_true")
    later.add_argument("--test-revision", action="store_true")
    parser.add_argument("--patient-portal", action="store_true", help="Separately gated patient-session checks after baseline")
    parser.add_argument("--activate-patient", action="store_true", help="Explicitly activate only this run's patient; no automatic MFA enrollment")
    args = parser.parse_args(argv)
    if not (math.isfinite(args.poll_interval) and 5 <= args.poll_interval <= 60
            and math.isfinite(args.timeout) and 5 <= args.timeout <= 1800):
        parser.error("poll interval must be 5–60 seconds; timeout must be 5–1800 seconds")
    if args.state_file and args.resume_state:
        parser.error("choose a new state file OR a resume file")
    if (args.test_revocation or args.test_revision or args.patient_portal or args.activate_patient) and not (args.execute and args.resume_state):
        parser.error("later subphases require --execute --resume-state from a confirmed baseline")
    if args.activate_patient and not args.patient_portal:
        parser.error("--activate-patient also requires --patient-portal")
    if args.patient_portal and (args.test_revocation or args.test_revision):
        parser.error("run patient checks separately from lifecycle tests")
    return args


def main(argv=None):
    args = parse_args(argv)
    journal = None
    try:
        client = Client(args.base_url, execute=args.execute, session_cookie=args.session_cookie, csrf_cookie=args.csrf_cookie)
        me = client.login("Operator")
        signer, signer_me = None, None
        if args.signer_login:
            signer = Client(args.base_url, execute=args.execute, session_cookie=args.session_cookie, csrf_cookie=args.csrf_cookie)
            signer_me = signer.login("Linked signatory")
        okay, counts = preflight(client, me, signer_me, args)
        require(okay, "Preflight failed; no workflow writes performed. Resolve the reported prerequisites.")
        if not args.execute:
            emit("PASS", "Overall preflight: PASS. --execute was not supplied; no workflow writes.")
            return 0
        if args.resume_state:
            journal = Journal(args.resume_state, base=client.base)
        else:
            path = args.state_file or Path(__file__).resolve().parents[1] / ".phase9-runs" / (new_run_id() + ".json")
            journal = Journal(path, base=client.base, create=True)
            journal.data["counts_before"] = counts
            journal.save()
        emit("INFO", "Run: " + journal.data["run_id"] + "; journal: " + str(journal.path))
        runner = Runner(client, signer, journal, timeout=args.timeout, interval=args.poll_interval)
        if args.test_revocation or args.test_revision:
            runner.lifecycle_test("revoke" if args.test_revocation else "revise")
            emit("PASS", "Explicit lifecycle subphase complete.")
            return 0
        if not args.resume_state:
            runner.baseline()
        runner.confirm_baseline()
        if args.patient_portal:
            runner.patient_portal(activate=args.activate_patient)
        print("\nPHASE 9 E2E VALIDATION")
        for label in ("Patient", "Order", "Specimen", "Result", "Report generation", "Signatory", "Release",
                      "Outbox", "Fabric confirmation", "Staff blockchain status", "Public verification"):
            emit("PASS", label)
        emit("SKIP", "Payment (not required)")
        emit("PASS" if args.patient_portal else "SKIP", "Patient portal" + ("" if args.patient_portal else " (separately gated)"))
        print(json.dumps(runner.ids, sort_keys=True))
        emit("PASS", "Overall: PASS")
        return 0
    except ValidationError as exc:
        emit("FAIL", str(exc))
        return 1
    except (EOFError, KeyboardInterrupt):
        emit("FAIL", "Interrupted. No writes will be replayed; inspect the journal before continuing.")
        return 1
    except Exception:
        # Do not print exception repr/traceback: transport errors can contain tokens/URLs.
        emit("FAIL", "Unexpected local error; details withheld. Stop and reconcile any recorded write intent.")
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
