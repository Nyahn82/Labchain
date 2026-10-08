# Phase 12B — RBAC matrix and trusted initial signer

Implementation only. No production role/grant/account bootstrap, deployment,
restart, E2E workflow or complete backend regression was run for this change.
Existing endpoint authorization and SYSTEM_ADMIN bypass semantics are unchanged.

## Approved policy, version 1.0.0

`app/services/role_permission_matrix.py` defines immutable explicit sets and
validates catalog membership, counts, duplicate declarations and exclusions.
Only LAB_STAFF, LAB_SUPERVISOR and LAB_SIGNER are managed by the grant command.
There is no runtime role inheritance and no automatic future-permission inclusion.

LAB_STAFF has exactly these 17 permissions:

```text
PATIENT_READ
PATIENT_CREATE
PATIENT_UPDATE
PHYSICIAN_READ
LAB_MASTER_READ
LAB_ORDER_READ
LAB_ORDER_CREATE
PAYMENT_READ
SPECIMEN_READ
SPECIMEN_REGISTER
SPECIMEN_COLLECT
SPECIMEN_RECEIVE
LAB_RESULT_READ
LAB_RESULT_ENTER
REPORT_READ
REPORT_DOWNLOAD
REPORT_PRINT
```

LAB_SUPERVISOR has exactly those 17 plus these 15, totaling 32:

```text
LAB_ORDER_CANCEL
SPECIMEN_REJECT
REJECTION_REASON_MANAGE
LAB_RESULT_REVIEW
LAB_RESULT_VERIFY
REPORT_GENERATE
REPORT_TEMPLATE_READ
SIGNATORY_READ
SIGNATORY_MANAGE
REPORT_APPROVE
REPORT_RELEASE
REPORT_REVISE
REPORT_REVOKE
ANALYTICS_VIEW
BLOCKCHAIN_STATUS_VIEW
```

LAB_SIGNER has exactly `{REPORT_SIGN}`. It is a permanent supported role named
**Laboratory Signer**, described as **Identity-bound laboratory report signing
capability.** `ensure_core_roles` creates missing metadata only, preserving
existing metadata and active flags. It assigns no permissions or accounts.
An existing inactive LAB_SIGNER remains inactive and grant execution refuses it.

Unmanaged roles remain unchanged:

- SYSTEM_ADMIN uses its existing application permission bypass. No explicit
  grant rows are needed or added.
- PATIENT has zero approved explicit grants. Its portal depends on the PATIENT
  role, patient-account link, ownership, MFA/session and report lifecycle checks.
- DOCTOR has zero approved explicit grants. A requesting physician master record
  is not a login identity; there is no physician-account ownership relationship
  or scoped doctor portal. Laboratory-wide access is not approved.

The grant bootstrap does not remove even unexpected pre-existing grants on
unmanaged roles. Operators must separately verify their approved empty sets;
any drift requires explicit investigation, not automatic reconciliation.

Routine staff cannot reject specimens in this policy. Supervisors receive the
bundled rejection-reason management permission needed by the existing selector.
SIGNATORY_MANAGE also includes profile changes, not only report assignments.
REPORT_DOWNLOAD includes historical revoked PDFs. LAB_ORDER_READ includes
embedded specimen/payment details. These existing behaviors are unchanged.
Payment recording, patient activation, account/security administration, general
clinical master-data mutations and technical blockchain explorer access are not
part of the staff/supervisor matrix. REPORT_SIGN is not part of either role.

## Grant preflight and execution

These are future operator commands, not commands executed during implementation.
Run from `/opt/rhu-labchain` with the reviewed code and intended database settings.
Obtain a verified production database backup and a protected RBAC state export
before any production write. Use the established protected backup credentials;
never put passwords in command arguments or documentation. Freeze concurrent
administrative/RBAC changes during rollout and initial signer provisioning.

```bash
cd /opt/rhu-labchain
# Metadata only; separately authorized production write:
.venv/bin/python -m app.cli.bootstrap_roles
# SELECT-only, also the default if no mode is supplied:
.venv/bin/python -m app.cli.bootstrap_role_permissions --preflight
# Only after reviewing preflight and backup:
.venv/bin/python -m app.cli.bootstrap_role_permissions --execute
```

No permission-catalog bootstrap is needed when the database already has all 62
current codes. The grant command refuses any catalog/database code-set mismatch,
including unknown codes. Resolve metadata separately; the grant command never
creates or updates permission metadata. Permission has no is_active column, so
validation checks code membership/existence and role active state instead.

Preflight performs SELECTs only, with no receipt, flush, commit or API login. It
prints matrix version; permission count and IDs/codes; each managed role's ID,
active flag, current/expected counts, current/missing/extra grants and assignment
count; assignment fingerprints; validation errors; and whether execution is safe. No credentials or
unrelated account information are printed. Assignment counts include inactive
accounts because the grants can affect those accounts if reactivated later.

Missing/inactive roles, missing permissions, catalog inconsistency or unexpected
managed-role grants cause refusal. There is no automatic removal or broad
reconciliation option. Partial valid states add only missing rows. An exact
state returns `NO_CHANGES` under execution, without duplicate grants.

Execution prints its preflight plan first, then opens a new transaction. It locks
the SYSTEM_ADMIN coordination row used by existing account administration,
managed roles in code order, permission rows by ID, and managed grants and
assignment rows in deterministic order. Locking reads reread current state under
MySQL REPEATABLE READ. A changed plan aborts before additions. A concurrent
bootstrap winner invalidates the other caller's old plan; the loser must run
preflight again rather than silently adopt changed state.

Only managed-role RolePermission rows are inserted. No UPDATE/DELETE is issued.
Role/permission metadata, UserRole, UserAccount, Staff, Patient and unmanaged
grants are untouched. All additions commit together; insertion, constraint,
receipt or precommit failure rolls everything back. Database uniqueness remains
the final duplicate guard. A second fresh execution is a no-op.

## Execution evidence and scoped rollback

Grant receipts default to `.phase9-runs/rbac-<operation-id>.json` (gitignored),
or an explicit `--receipt-file`. Creation is exclusive, no-follow and mode 0600.
The file and directory entry are flushed before mutation. It contains no secrets:
operation ID/time, matrix version, the preflight plan, added row primary keys,
role IDs/codes, permission IDs/codes, and execution state.

- PENDING: intent exists; do not infer commit status from this alone.
- PREPARED: inserted row IDs were recorded durably before commit. A crash here
  can mean rollback or successful commit with an unfinished receipt update.
- COMMITTED: the database commit returned successfully and the receipt updated.

No automatic rollback helper is included. Manual rollback must be reviewed:

1. Preserve the receipt and take a fresh backup. Stop conflicting RBAC changes.
2. Verify matrix version, database identity, role/permission IDs/codes, and every
   recorded RolePermission primary key against current data.
3. Verify relevant managed-role metadata, current grants and user assignments
   against the preflight/committed state and available audit/backup evidence.
   Compare the recorded assignment fingerprints as well as counts. Refuse
   rollback if history/state cannot be established or later changes occurred.
4. In one transaction with the same coordination/role locks, remove **only** rows
   whose exact primary key, role ID and permission ID match this operation's
   recorded additions. Never remove a pre-existing grant or delete by role alone.
5. Verify the intended prior state and commit; roll back on any discrepancy.

A PREPARED receipt is evidence of intended rows, not proof of commit. If the
outcome is ambiguous, investigate; never blanket-delete grants or restore the
whole database over later clinical activity. Auto-increment IDs may be consumed
by rolled-back inserts; gaps are expected.

## Trusted first synthetic signer

`scripts/phase12_initial_signer_setup.py` is a one-purpose bridge for the first
synthetic account. It is not a general account bootstrap and does not create
staff/signatory/workflow data. It does not sign reports or call Fabric.

Default `--preflight` uses local SELECT-only SessionLocal evidence to require:

- Existing active LAB_SIGNER with a complete grant set of exactly REPORT_SIGN.
- Exactly one REPORT_SIGN permission record.
- Existing active staff 1 with exact code P9SIGN01.
- Existing active signatory 1 linked to staff 1.
- No account link for staff 1 and no existing p9signer username, including
  conservative case/accent-equivalent conflicts.

The operator then authenticates through the normal HTTPS API using hidden
username/password prompts, including the existing MFA flow when required.
There are no credential command-line arguments. Unknown argument errors do not
echo supplied values. A mistyped credential flag is rejected without echoing it.

The operator must be ACTIVE SYSTEM_ADMIN or have the existing helper's account,
role and staff discovery/create/assign authority including REPORT_SIGN, plus
SIGNATORY_READ for signatory discovery. Patient operators are refused. The live
API contract, role metadata, account inventory, staff and signatory are checked.
The operator's API session cookie is hashed in memory and matched to a live
AuthSession in the local database, together with current user/role/permission
state. This prevents trusting local evidence for an unrelated API deployment.
Cookie values and hashes are never output or stored in receipts.

API authentication has normal session, last-login and audit effects even during
preflight. "No writes" here means no provisioning/workflow writes and no SQL
writes by this tool; it cannot mean zero authentication side effects.

```bash
# Future commands; not run as part of implementation:
.venv/bin/python scripts/phase12_initial_signer_setup.py --preflight
.venv/bin/python scripts/phase12_initial_signer_setup.py --execute
```

Execute completes preflight, prompts for the new password twice with hidden
input, checks the current 12–1024 character rule and local/live schemas, and
reruns critical local/API checks after password input. It writes an exclusive
0600 intent before exactly one POST `/api/v1/staff/1/account` with username
p9signer and role_codes `["LAB_SIGNER"]`. It never inserts account, UserRole or
StaffAccountLink rows through SQL. Transport failures, malformed success,
unexpected status or other uncertainty are never automatically retried.

The default fixed intent is `.phase9-runs/phase12-initial-signer.json`. It holds
only operation ID/time, target staff ID/code, username, role, expected permissions,
result state and confirmed created user ID. It never stores passwords, cookies,
CSRF tokens, private clinical data or operator identity. States are PENDING,
CREATED_UNVERIFIED and VERIFIED. An existing intent blocks execution; do not
change the path or delete the receipt to bypass an uncertain result.

After creation, the account response and account GET must have the expected
identity and all assigned roles. A separate p9signer login and explicit
`GET /auth/me` must prove ACTIVE, roles exactly `["LAB_SIGNER"]`, permissions
exactly `["REPORT_SIGN"]`, staff 1/P9SIGN01, and patient null. Local grant/target
evidence is checked again. Any mismatch stops without automatic repairs.
An account may exist after a failed verification; reconcile it manually.

Read checks and HTTP creation cannot form one cross-system transaction. Avoid
concurrent RBAC/identity changes. Existing backend account creation performs its
normal transactional checks; post-create verification detects observed drift
but cannot undo a grant change between requests. This implementation does not
add an authorization endpoint or weaken existing route checks.

## Phase 9 compatibility and cleanup

The old API-only `phase9_signer_setup.py` still requires an authenticated
single-role REPORT_SIGN-only witness. It never trusts a role name or catalog
entry alone. A verified p9signer can now serve as role evidence; the old helper
still refuses provisioning when p9signer or staff 1 is already occupied and
requires a new account to differ from operator/witness identities. Consequently,
its overall provisioning preflight is expected to fail on the occupied target
after successful first-signer setup, even though the role-evidence check passes.

The E2E runner is unchanged. Its subsequent, separately authorized preflight is:

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --preflight --signer-login
```

No E2E execution is part of Phase 12B implementation. REPORT_SIGN-only accounts
still lack a signing-only frontend workspace; the runner supplies the known
assignment ID. Do not add REPORT_READ to make the frontend available.

After authorized E2E validation, use a separate administrator to verify the
receipt's user ID is exactly the synthetic staff-1 account, preserve evidence,
and call the existing supported status endpoint:

```text
PATCH /api/v1/users/<confirmed-signer-user-id>/status
{"account_status":"DISABLED"}
```

Use normal authenticated API/CSRF handling. This revokes sessions; do not delete
signed evidence, clinical data, staff links, or the permanent LAB_SIGNER role.
The administrator must not target itself. Re-enabling an existing disabled
signer is a separate reviewed account-management operation, not rerunning the
first-signer utility. Failed/uncertain setup also requires identity reconciliation
before a supported disable operation; never guess the target user ID.

## Release and validation

No migration, permission-catalog expansion, endpoint authorization changes or
frontend rebuild is required. Grant changes take effect on subsequent backend
requests; refresh frontend authentication state. The metadata/CLI-only change
does not inherently require restarting the running application.

The implementation requires focused policy/bootstrap, RBAC, administration,
Phase 5 reporting, Phase 9 safeguards and Phase 10 account-protection tests,
plus native MySQL uniqueness, locking, concurrency, rollback and idempotency.
Native tests start a separate --no-defaults, --skip-networking MySQL instance in
/tmp. They never use production credentials/databases. The full backend suite
must be run and pass before release, under separate authorization; it was not
run during this implementation.

### Implementation validation, 2026-10-08 UTC

- Requested focused regression: **497 passed**, with two existing dependency
  deprecation warnings, in 285.93 seconds.
- Final targeted rerun after the last safety changes: **97 passed** in 57.38
  seconds. This includes **all 5 native MySQL probes**, with no skips. These
  runs overlap; the counts are not an additive unique-test total.
- `python -m compileall app scripts tests`: passed.
- `git diff --check`: passed, including the existing tracked working-tree changes.
- Separate whitespace/EOF checks on all 13 Phase 12B files, including untracked
  files: passed. Pre-existing Phase 12A/runtime changes were preserved.

```bash
.venv/bin/python -m pytest \
  tests/test_phase12_rbac_matrix.py tests/test_phase12_initial_signer.py \
  tests/test_phase_3a_authentication_rbac.py tests/test_phase_3b_identity_admin.py \
  tests/test_phase9_signer_setup.py tests/test_phase9_e2e_validation.py \
  tests/test_phase_5a_reports.py tests/test_phase_5b_release.py \
  tests/test_phase_10_auth_activity.py -vv -ra --tb=long

.venv/bin/python -m pytest \
  tests/test_phase12_rbac_matrix.py tests/test_phase12_initial_signer.py \
  tests/test_phase12_mysql.py tests/test_phase9_signer_setup.py -vv -ra --tb=long

.venv/bin/python -m compileall app scripts tests
git diff --check
```
