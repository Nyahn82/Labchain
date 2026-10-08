#!/usr/bin/env python3
"""Provision only the synthetic staff-1 signer, using existing supported APIs.

Defaults to read-only preflight (normal login session/audit effects excepted).
The current API cannot create roles or expose role-permission memberships. A
reusable role must be proven by an existing single-role account's /auth/me.
Without that evidence this tool refuses to provision, including with --execute.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import unicodedata

if __package__:
    from . import phase9_e2e_validation as e2e
else:
    import phase9_e2e_validation as e2e

USERNAME = "p9signer"
MINIMUM = {"REPORT_SIGN"}
OPERATOR_PERMISSIONS = {"STAFF_READ", "ACCOUNT_READ", "ROLE_READ", "ACCOUNT_CREATE", "ROLE_ASSIGN", "REPORT_SIGN"}
DEFAULT_INTENT = Path(__file__).resolve().parents[1] / ".phase9-runs" / "signer-setup.json"


def canonical_username(value):
    e2e.require(isinstance(value, str), "Account response has an invalid username.")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).casefold().strip()


def role_code(value):
    e2e.require(isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_-]{0,39}", value),
                "Role code cannot be safely selected by this helper.")
    return value


def roles_and_permissions(client):
    roles = client.get("/roles")
    permissions = client.get("/permissions")
    e2e.require(isinstance(roles, list) and isinstance(permissions, list), "Invalid RBAC discovery response.")
    by_code = {}
    for role in roles:
        code = role_code(e2e.obj(role).get("role_code"))
        e2e.identifier(role.get("role_id"))
        e2e.require(type(role.get("is_active")) is bool and code not in by_code, "Ambiguous role metadata.")
        by_code[code] = role
    codes = [e2e.obj(p).get("permission_code") for p in permissions]
    e2e.require(codes.count("REPORT_SIGN") == 1, "REPORT_SIGN must exist exactly once in the permission catalog.")
    # Catalog membership is NOT evidence that a role has this permission.
    return by_code


def accounts(client):
    """Exhaustive, unfiltered, bounded pagination includes inactive/locked links."""
    result = []
    seen = set()
    total = None
    for page in range(1, 101):
        body = e2e.obj(client.get(f"/users?page={page}&page_size=100"))
        current_total = body.get("total")
        e2e.require(type(current_total) is int and 0 <= current_total <= 10000,
                    "Account inventory is too large or malformed; manual review required.")
        if total is None:
            total = current_total
        e2e.require(total == current_total and body.get("page") == page and body.get("page_size") == 100,
                    "Account inventory changed during pagination; stop and retry preflight only.")
        rows = body.get("items")
        e2e.require(isinstance(rows, list) and len(rows) <= 100, "Invalid account page.")
        for row in rows:
            uid = e2e.identifier(e2e.obj(row).get("user_id"))
            e2e.require(uid not in seen, "Duplicate account in paginated inventory.")
            canonical_username(row.get("username"))
            seen.add(uid)
            result.append(row)
        e2e.require(len(result) <= total, "Account total is inconsistent.")
        if len(result) == total:
            return result
        e2e.require(bool(rows), "Incomplete account inventory; provisioning refused.")
    raise e2e.ValidationError("Account pagination limit reached; provisioning refused.")


def available_target(client, inventory):
    staff = e2e.matches(client.get("/staff/1"), staff_id=1, staff_code="P9SIGN01", is_active=True)
    for account in inventory:
        link = account.get("staff")
        e2e.require(link is None or isinstance(link, dict), "Invalid staff-account link response.")
        e2e.require(not isinstance(link, dict) or link.get("staff_id") != 1,
                    "Staff 1 is already linked to an account. STOP and reconcile; no existing link will be changed.")
        e2e.require(canonical_username(account["username"]) != USERNAME,
                    "Username p9signer already exists. STOP and reconcile; no second account will be created.")
    return staff


def inspect_contract(client):
    spec = e2e.obj(client.request("GET", "/openapi.json"))
    paths = spec.get("paths", {})
    for route in ("/auth/me", "/staff/{staff_id}", "/users", "/users/{user_id}", "/roles", "/permissions"):
        e2e.require("get" in paths.get(e2e.API + route, {}), "Required account discovery endpoint is missing.")
    schemas = spec.get("components", {}).get("schemas", {})
    for method, route, name in (("post", "/staff/{staff_id}/account", "StaffAccountCreate"),
                                ("put", "/users/{user_id}/roles", "RoleReplacement")):
        operation = paths.get(e2e.API + route, {}).get(method, {})
        ref = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", "")
        e2e.require(ref == "#/components/schemas/" + name, "Account/role request contract changed; review required.")
    e2e.require(set(schemas.get("StaffAccountCreate", {}).get("required", [])) == {"username", "password", "role_codes"},
                "StaffAccountCreate required fields changed; review required.")
    e2e.require(set(schemas.get("RoleReplacement", {}).get("required", [])) == {"role_codes"},
                "RoleReplacement required fields changed; review required.")
    return schemas


def operator_ready(me):
    e2e.matches(me, account_status="ACTIVE")
    uid = e2e.identifier(me.get("user_id"))
    e2e.require(e2e.permitted(me, OPERATOR_PERMISSIONS), "Operator lacks account-discovery or account/role-grant authority.")
    e2e.require(canonical_username(me.get("username")) != USERNAME, "Operator must not be the synthetic signer.")
    return uid


def verify_role(client, verifier, operator_id, roles):
    e2e.require(verifier is not None,
                "Role permissions cannot be established from GET /roles or /permissions. "
                "Use --role-verifier-login with an existing single-role REPORT_SIGN-only account. "
                "There is no supported role creation, permission-grant, or role-membership API; "
                "provisioning is blocked without verified role evidence.")
    me = e2e.obj(verifier.get("/auth/me"))
    e2e.matches(me, account_status="ACTIVE")
    uid = e2e.identifier(me.get("user_id"))
    e2e.require(uid != operator_id, "Role verifier must be separate from the operator.")
    assigned = me.get("roles")
    e2e.require(isinstance(assigned, list) and len(assigned) == 1, "Role verifier must have exactly one active role.")
    code = role_code(assigned[0])
    e2e.require(code not in {"SYSTEM_ADMIN", "PATIENT"}, "Administrator/patient roles must never be assigned to the signer.")
    e2e.require(code in roles and roles[code]["is_active"] is True, "Verified role is missing or inactive.")
    e2e.require(isinstance(me.get("permissions"), list) and set(me["permissions"]) == MINIMUM,
                "Reusable role must grant exactly REPORT_SIGN; missing or additional authority is not accepted.")
    account = client.get(f"/users/{uid}")
    e2e.matches(account, user_id=uid, account_status="ACTIVE", roles=[code])
    # AccountResponse includes inactive role assignments too; do not hide any.
    canonical_username(account.get("username"))  # Preserve account-shape validation.
    # An existing p9signer may prove its role after trusted Phase 12 bootstrap.
    # available_target still refuses an occupied username/staff link, and
    # check_new_account still requires a new identity distinct from the witness.
    return {"role_code": code, "role_id": roles[code]["role_id"], "verifier_id": uid,
            "permissions": sorted(MINIMUM)}


def preflight(client, verifier=None):
    failures = []
    evidence = None

    def check(label, action):
        try:
            result = action()
            e2e.emit("PASS", label)
            return result
        except e2e.ValidationError as exc:
            failures.append(str(exc))
            e2e.emit("FAIL", label + ": " + str(exc))

    operator_id = check("Operator account authority", lambda: operator_ready(e2e.obj(client.get("/auth/me"))))
    check("Supported account/role schemas", lambda: inspect_contract(client))
    inventory = check("Complete account inventory", lambda: accounts(client))
    if inventory is not None:
        check("Synthetic staff available and username unused", lambda: available_target(client, inventory))
    roles = check("Role and permission catalog", lambda: roles_and_permissions(client))
    if roles is not None:
        for code, role in sorted(roles.items()):
            e2e.emit("INFO", f"Role {code}: active={role['is_active']}; permission membership not exposed by role API.")
        if inventory is not None:
            # Do not print usernames, staff names, or unrelated identity data.
            candidates = sum(1 for a in inventory if a.get("account_status") == "ACTIVE"
                             and isinstance(a.get("roles"), list) and len(a["roles"]) == 1
                             and a["roles"][0] not in {"SYSTEM_ADMIN", "PATIENT"})
            e2e.emit("INFO", f"Existing active single-role non-admin/non-patient accounts: {candidates} (permissions unverified).")
        if operator_id is not None:
            evidence = check("Least-privilege reusable role", lambda: verify_role(client, verifier, operator_id, roles))
    e2e.emit("INFO", "Minimum signer permission: REPORT_SIGN. Login and /auth/me need no additional permission.")
    e2e.emit("INFO", "The E2E operator reads reports; the separate signer only signs. REPORT_READ is not needed for this runner.")
    e2e.emit("INFO", "No role creation/grant route exists. PHASE9_SIGNER will not be invented or bootstrapped.")
    e2e.emit("INFO", "Preflight makes no provisioning writes; login has normal session/audit effects.")
    return not failures, evidence


def check_new_account(body, operator_id, evidence, *, user_id=None):
    e2e.matches(body, username=USERNAME, account_status="ACTIVE", roles=[evidence["role_code"]])
    uid = e2e.identifier(body.get("user_id"))
    e2e.require(uid not in {operator_id, evidence["verifier_id"]}, "New signer must be separate from existing identities.")
    if user_id is not None:
        e2e.require(uid == user_id, "Created account identifier changed.")
    e2e.matches(body.get("staff"), staff_id=1, staff_code="P9SIGN01")
    e2e.require(body.get("patient") is None, "Signer must not be linked to a patient.")
    return uid


def execute(client, verifier, evidence, intent_path, *, client_factory=e2e.Client):
    e2e.require(client.execute, "Signer provisioning requires --execute.")
    # Recheck everything before prompting for a new credential and again before POST.
    okay, current = preflight(client, verifier)
    e2e.require(okay and current == evidence, "Provisioning preflight changed; no write sent.")
    operator_id = operator_ready(e2e.obj(client.get("/auth/me")))
    password = e2e.hidden_input("New p9signer password (12+ characters): ")
    confirmation = e2e.hidden_input("Confirm new p9signer password: ")
    try:
        e2e.require(password == confirmation and 12 <= len(password) <= 1024,
                    "Password confirmation or schema length requirement failed; no write sent.")
        confirmation = None
        okay, current = preflight(client, verifier)
        e2e.require(okay and current == evidence, "Role, staff, or username state changed; no write sent.")
        e2e.require(operator_ready(e2e.obj(client.get("/auth/me"))) == operator_id, "Operator identity changed; no write sent.")
        schemas = inspect_contract(client)
        payload = {"username": USERNAME, "password": password, "role_codes": [evidence["role_code"]]}
        e2e.validate_payload(payload, schemas["StaffAccountCreate"], schemas)
        path = Path(intent_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Fixed default receipt means rerunning an uncertain POST cannot duplicate it.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as receipt:
            state = {"action": "CREATE_PHASE9_SIGNER", "status": "PENDING", "base": client.base,
                     "staff_id": 1, "username": USERNAME, "role_codes": [evidence["role_code"]],
                     "permissions": sorted(MINIMUM)}
            def record():
                receipt.seek(0)
                json.dump(state, receipt, indent=2)
                receipt.truncate()
                receipt.flush()
                os.fsync(receipt.fileno())
            record()
            e2e.emit("INFO", "Intent recorded: create ACTIVE p9signer linked to staff 1, role " + evidence["role_code"] + ", permission REPORT_SIGN only.")
            body = client.request("POST", e2e.API + "/staff/1/account", payload, expected=(201,))
            payload = None
            uid = check_new_account(e2e.obj(body), operator_id, evidence)
            state.update(status="CREATED_UNVERIFIED", user_id=uid)
            record()
            check_new_account(e2e.obj(client.get(f"/users/{uid}")), operator_id, evidence, user_id=uid)
            signer = client_factory(client.base, session_cookie=client.session_cookie, csrf_cookie=client.csrf_cookie)
            me = signer.login("New synthetic signer", username=USERNAME, password=password)
            check_new_account(e2e.obj(me), operator_id, evidence, user_id=uid)
            e2e.require(set(me.get("permissions", [])) == MINIMUM, "Created signer has unexpected effective permissions; stop and reconcile.")
            # Revalidate the role witness and target after creation too; no reports touched.
            e2e.require(verify_role(client, verifier, operator_id, roles_and_permissions(client)) == evidence,
                        "Role evidence changed during creation; stop and reconcile.")
            check_new_account(e2e.obj(client.get(f"/users/{uid}")), operator_id, evidence, user_id=uid)
            state["status"] = "VERIFIED"
            record()
            e2e.emit("PASS", f"Signer verified: user_id={uid}, staff_id=1, ACTIVE, REPORT_SIGN only; login works.")
            return uid
    finally:
        password = confirmation = None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--base-url", default=e2e.BASE)
    parser.add_argument("--session-cookie", default="rhu_session")
    parser.add_argument("--csrf-cookie", default="rhu_csrf")
    parser.add_argument("--role-verifier-login", action="store_true",
                        help="Secure login to an existing single-role account proving exactly REPORT_SIGN")
    parser.add_argument("--intent-file", type=Path, default=DEFAULT_INTENT,
                        help="Exclusive non-secret receipt; never reuse/delete after an uncertain write")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        client = e2e.Client(args.base_url, execute=args.execute, session_cookie=args.session_cookie, csrf_cookie=args.csrf_cookie)
        client.login("Operator")
        verifier = None
        if args.role_verifier_login:
            verifier = e2e.Client(args.base_url, session_cookie=args.session_cookie, csrf_cookie=args.csrf_cookie)
            verifier.login("Existing single-role permission verifier")
        okay, evidence = preflight(client, verifier)
        e2e.require(okay, "Signer setup preflight failed; no account or role was changed.")
        if args.execute:
            execute(client, verifier, evidence, args.intent_file)
        else:
            e2e.emit("PASS", "Signer setup preflight complete. --execute was not supplied; zero provisioning writes.")
        return 0
    except e2e.ValidationError as exc:
        e2e.emit("FAIL", str(exc))
        return 1
    except FileExistsError:
        e2e.emit("FAIL", "Provisioning intent file already exists. Reconcile the earlier attempt; no POST retried.")
        return 1
    except (EOFError, KeyboardInterrupt):
        e2e.emit("FAIL", "Interrupted; reconcile any recorded intent before continuing.")
        return 1
    except Exception:
        e2e.emit("FAIL", "Unexpected error; details withheld. Reconcile any recorded intent; no write retried.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
