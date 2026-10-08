"""Explicit v1 grant policy. No implicit hierarchy or runtime authorization changes."""
from types import MappingProxyType
from hashlib import sha256
import json

from sqlalchemy import select

from app.models import Permission, Role, RolePermission, UserRole
from app.services.permission_catalog import PERMISSION_CATALOG

ROLE_PERMISSION_MATRIX_VERSION = "1.0.0"
_STAFF = (
    "PATIENT_READ", "PATIENT_CREATE", "PATIENT_UPDATE", "PHYSICIAN_READ",
    "LAB_MASTER_READ", "LAB_ORDER_READ", "LAB_ORDER_CREATE", "PAYMENT_READ",
    "SPECIMEN_READ", "SPECIMEN_REGISTER", "SPECIMEN_COLLECT", "SPECIMEN_RECEIVE",
    "LAB_RESULT_READ", "LAB_RESULT_ENTER", "REPORT_READ", "REPORT_DOWNLOAD", "REPORT_PRINT",
)
_SUPERVISOR_ADDITIONS = (
    "LAB_ORDER_CANCEL", "SPECIMEN_REJECT", "REJECTION_REASON_MANAGE", "LAB_RESULT_REVIEW",
    "LAB_RESULT_VERIFY", "REPORT_GENERATE", "REPORT_TEMPLATE_READ", "SIGNATORY_READ",
    "SIGNATORY_MANAGE", "REPORT_APPROVE", "REPORT_RELEASE", "REPORT_REVISE", "REPORT_REVOKE",
    "ANALYTICS_VIEW", "BLOCKCHAIN_STATUS_VIEW",
)
ROLE_PERMISSION_MATRIX = MappingProxyType({
    "LAB_SIGNER": frozenset({"REPORT_SIGN"}),
    "LAB_STAFF": frozenset(_STAFF),
    "LAB_SUPERVISOR": frozenset(_STAFF + _SUPERVISOR_ADDITIONS),
})
UNMANAGED_ROLES = frozenset({"SYSTEM_ADMIN", "PATIENT", "DOCTOR"})


class MatrixError(ValueError):
    """Safe operator-facing refusal; never include SQL or private parameters."""


def validate_matrix():
    catalog = [row[0] for row in PERMISSION_CATALOG]
    forbidden = {
        "REPORT_SIGN", "ACCOUNT_READ", "ACCOUNT_CREATE", "ACCOUNT_STATUS_UPDATE", "ROLE_READ",
        "ROLE_ASSIGN", "AUTH_ACTIVITY_VIEW", "SESSION_MANAGE", "ACCOUNT_MFA_RESET",
        "PATIENT_ACCOUNT_ACTIVATE", "PAYMENT_RECORD", "LAB_DEPARTMENT_MANAGE", "SAMPLE_TYPE_MANAGE",
        "TEST_CATALOG_MANAGE", "TEST_PANEL_MANAGE", "REFERENCE_RANGE_MANAGE",
        "INTERPRETATION_RULE_MANAGE", "BLOCKCHAIN_EXPLORER_VIEW", "BLOCKCHAIN_INTEGRITY_VERIFY",
    }
    if (len(catalog) != len(set(catalog)) or len(_STAFF) != len(set(_STAFF))
            or len(_STAFF + _SUPERVISOR_ADDITIONS) != len(set(_STAFF + _SUPERVISOR_ADDITIONS))
            or set(ROLE_PERMISSION_MATRIX) != {"LAB_SIGNER", "LAB_STAFF", "LAB_SUPERVISOR"}
            or ROLE_PERMISSION_MATRIX["LAB_SIGNER"] != {"REPORT_SIGN"}
            or len(ROLE_PERMISSION_MATRIX["LAB_STAFF"]) != 17
            or len(ROLE_PERMISSION_MATRIX["LAB_SUPERVISOR"]) != 32
            or not ROLE_PERMISSION_MATRIX["LAB_STAFF"] <= ROLE_PERMISSION_MATRIX["LAB_SUPERVISOR"]
            or forbidden & ROLE_PERMISSION_MATRIX["LAB_SUPERVISOR"]
            or any(not codes <= set(catalog) for codes in ROLE_PERMISSION_MATRIX.values())):
        raise MatrixError("Invalid declared role permission matrix.")


validate_matrix()


def inspect_matrix(db, *, locked=False):
    """SELECT-only snapshot. Locking reads avoid stale MySQL repeatable-read snapshots."""
    validate_matrix()

    def rows(statement):
        if locked:
            statement = statement.with_for_update()
        return db.execute(statement).all()

    permissions = rows(select(Permission.permission_id, Permission.permission_code)
                       .order_by(Permission.permission_id))
    catalog = {row[0] for row in PERMISSION_CATALOG}
    by_code = {code: pid for pid, code in permissions}
    by_id = {pid: code for pid, code in permissions}
    errors = []
    coordination = rows(select(Role.role_id).where(Role.role_code == "SYSTEM_ADMIN"))
    if len(coordination) != 1:
        errors.append("Administrative coordination role is missing or ambiguous.")
    if len(by_code) != len(permissions) or set(by_code) != catalog:
        errors.append("Permission catalog/database code sets differ; bootstrap/refine metadata separately.")
    roles = rows(select(Role.role_id, Role.role_code, Role.is_active)
                 .where(Role.role_code.in_(sorted(ROLE_PERMISSION_MATRIX))).order_by(Role.role_code))
    role_map = {code: (rid, active) for rid, code, active in roles}
    plan = []
    for code, expected in ROLE_PERMISSION_MATRIX.items():
        rid, active = role_map.get(code, (None, False))
        if rid is None or not active:
            errors.append(f"Managed role {code} is missing or inactive.")
        grants = [] if rid is None else rows(select(
            RolePermission.role_permission_id, RolePermission.permission_id)
            .where(RolePermission.role_id == rid).order_by(RolePermission.permission_id))
        assignments = [] if rid is None else rows(select(UserRole.user_role_id, UserRole.user_id)
            .where(UserRole.role_id == rid).order_by(UserRole.user_role_id))
        current = [by_id.get(pid, "UNKNOWN_PERMISSION") for _, pid in grants]
        extra = sorted(set(current) - expected)
        if extra or len(current) != len(set(current)):
            errors.append(f"Unexpected or duplicate grants on {code}; automatic removal is forbidden.")
        plan.append({
            "role_code": code, "role_id": rid, "active": bool(active),
            "current_count": len(current), "expected_count": len(expected),
            "current_grants": sorted(current), "missing_grants": sorted(expected - set(current)),
            "unexpected_grants": extra, "assignment_count": len(assignments),
            "assignment_fingerprint": sha256(json.dumps([list(r) for r in assignments]).encode()).hexdigest(),
            "grant_rows": [{"role_permission_id": gid, "permission_id": pid} for gid, pid in grants],
        })
    return {"matrix_version": ROLE_PERMISSION_MATRIX_VERSION,
            "permission_count": len(permissions), "permissions": dict(sorted(by_code.items())),
            "coordination_role_id": coordination[0][0] if len(coordination) == 1 else None,
            "roles": plan, "errors": errors, "safe_to_execute": not errors,
            "action": "REFUSED" if errors else ("ADD_GRANTS" if any(r["missing_grants"] for r in plan) else "NO_CHANGES")}


def preflight(factory):
    with factory() as db:
        return inspect_matrix(db)


def execute_matrix(factory, plan, *, record_prepared=None):
    """Own the entire transaction; only INSERT managed RolePermission rows.

    A competing execution invalidates an earlier plan and must be explicitly
    preflighted again. There are no retries or grant deletions.
    """
    if not plan["safe_to_execute"]:
        raise MatrixError("Preflight is unsafe; no grants added.")
    additions = []
    with factory.begin() as db:
        # Same administrative mutex as account/role management, then sorted roles,
        # permission IDs, grant IDs and assignment IDs. No metadata is modified.
        admin = db.scalar(select(Role.role_id).where(Role.role_code == "SYSTEM_ADMIN").with_for_update())
        if admin is None:
            raise MatrixError("Administrative coordination role is missing.")
        list(db.scalars(select(Role.role_id).where(Role.role_code.in_(sorted(ROLE_PERMISSION_MATRIX)))
                        .order_by(Role.role_code).with_for_update()))
        current = inspect_matrix(db, locked=True)
        if current != plan or not current["safe_to_execute"]:
            raise MatrixError("State changed since preflight; rerun preflight. No grants added.")
        for role in current["roles"]:
            for code in role["missing_grants"]:
                row = RolePermission(role_id=role["role_id"], permission_id=current["permissions"][code])
                db.add(row)
                db.flush()
                additions.append({"role_permission_id": row.role_permission_id,
                    "role_id": role["role_id"], "role_code": role["role_code"],
                    "permission_id": row.permission_id, "permission_code": code})
        # Durable evidence is recorded before commit. Failure to record rolls back.
        if record_prepared is not None:
            record_prepared(additions)
    return additions
