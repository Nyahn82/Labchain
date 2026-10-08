# Phase 9 dedicated signer setup

The helper defaults to preflight. It never links the administrator to synthetic
staff, grants SYSTEM_ADMIN, edits SQL, bootstraps roles, signs a report, creates
workflow data, or calls Fabric. **Production provisioning remains blocked**:
the current API cannot expose role-permission membership or create/grant roles,
and production has no suitable existing account with which to prove a role's
effective permission set. No provisioning execute was run for this task.

## Actual account and RBAC contracts

All paths below have prefix `/api/v1`. Cookie-authenticated unsafe methods require
the session's CSRF token in `X-CSRF-Token`. GET requires no CSRF. Authentication
uses the existing HTTPS login, optional MFA flow, and separate in-memory cookie
jars. Login has normal session, last-login, and audit effects; “no writes” in
preflight means no provisioning or workflow writes.

| Method and path | Request schema / required fields | Authority | Result |
| --- | --- | --- | --- |
| POST `/staff/{staff_id}/account` | `StaffAccountCreate`: `username`, `password`, `role_codes` | `ACCOUNT_CREATE`; when granting roles, non-admin also needs `ROLE_ASSIGN` and all granted permissions | 201 `AccountResponse`; atomic ACTIVE account, staff link and role assignments |
| PUT `/users/{user_id}/roles` | `RoleReplacement`: `role_codes` | `ROLE_ASSIGN`; non-admin cannot grant beyond own permissions or assign SYSTEM_ADMIN | 200 `AccountResponse`; replaces all assigned roles, not role permissions |
| GET `/users` | Optional `page`, `page_size` (max 100), `search`, `account_status` | `ACCOUNT_READ` | Paginated `AccountResponse`; includes inactive/locked accounts when unfiltered |
| GET `/users/{user_id}` | Path ID | `ACCOUNT_READ` | `AccountResponse`, including staff/patient identities and all assigned role codes |
| GET `/staff/{staff_id}` | Path ID | `STAFF_READ` | Staff identity and active state |
| GET `/roles` | None | `ROLE_READ` | List of `RoleResponse`: ID, code, name, description, active flag; no permissions |
| GET `/permissions` | None | `ROLE_READ` | List of `PermissionResponse`: catalog metadata; no role membership |
| GET `/auth/me` | None | Authenticated ACTIVE account | Current user's active roles, effective permissions, staff/patient identity |
| PATCH `/users/{user_id}/status` | `StatusUpdate`: `account_status` (`ACTIVE`, `INACTIVE`, `LOCKED`) | `ACCOUNT_STATUS_UPDATE` | 200 `AccountResponse`; not used by the helper |
| POST `/reports/{report_id}/sign` | `SignRequest`: `report_signatory_id` | `REPORT_SIGN` and matching staff link | Signs the existing assignment; not called by setup |

`StaffAccountCreate` inherits `RoleReplacement`; role codes are a required list
of at most 100 codes of at most 40 characters, deduplicated by the server.
Username has a 60-character limit. Password is `SecretStr`, length 12–1024.
The helper always supplies exactly one verified existing role and username
`p9signer`. The role assignment PUT is documented but not called: account creation
already grants the intended role atomically.

**There are no supported APIs or request schemas for role creation,
role-permission assignment, or reading a selected role's permission membership.**
The permission catalog does not prove grants. `bootstrap_roles` creates core
role metadata, not the required minimum grants; running it does not solve this.
No such endpoint or grant is invented by this helper.

Sources inspected: `app/api/administration.py`, `app/api/auth.py`,
`app/api/reporting.py`, `app/schemas/administration.py`,
`app/services/administration_service.py`, `app/services/rbac_service.py`,
`app/services/permission_catalog.py`, `app/services/reporting_service.py`,
`app/dependencies/auth.py`, `app/models/auth.py`, the account/identity and
reporting tests, and frontend account-management/report flows. There is no
`app/auth/` directory; authentication resides in the API/dependencies/security
and service modules. Source contracts are also checked against live OpenAPI.

## Minimum role and evidence

The minimum signer permission is **REPORT_SIGN only**. Login and `/auth/me` need
no extra permission. The E2E operator reads the report and creates its signatory
assignment; the separate signer makes only its identity checks and sign request.
`REPORT_READ` would be needed to browse the frontend reports page but is not
needed for this runner. The signing service independently checks the GENERATED
report, active signatory/staff, unsigned assignment, and matching staff-account
link. SYSTEM_ADMIN does not bypass the staff link.

If an existing appropriate role can be proven, reuse it. Because the only
supported effective-permission read is `/auth/me`, `--role-verifier-login`
authenticates an existing separate ACTIVE account with **exactly one** active
non-admin/non-patient role and effective permissions **exactly** `{REPORT_SIGN}`.
The operator checks `/users/{id}` as well, to reject additional inactive role
assignments hidden from `/auth/me`. In this implementation all effective grants
come from active roles, so that single role's grants are established without
SQL or guessing. Credentials remain in memory. The verifier is not the new
signer and need not be linked to staff 1.

If no such existing account is available, stop. A separately reviewed supported
RBAC discovery/provisioning mechanism is required before a `PHASE9_SIGNER` role
can be created or its permissions verified. This task does not expand the
production backend's authorization API. Merely naming an existing role such as
LAB_STAFF or LAB_SUPERVISOR is not evidence that it is suitable.

## Helper execution safeguards

Before the single account POST, the helper rechecks the actual schemas,
operator authority, active synthetic staff 1/P9SIGN01, all unfiltered account
pages (including inactive/locked links), unused username, and exact role
evidence. Username conflicts use conservative case/accent normalization; the
backend remains authoritative for uniqueness. Missing, inconsistent, oversized,
or incomplete discovery fails closed. No username or link is repaired.

In explicit execute mode only, the new password is entered twice using hidden
terminal input. There is no credential command-line option or file. Input
refuses an echo fallback. After the prompts all prerequisites are checked again.
A non-secret, exclusive 0600 intent receipt is flushed to disk before the POST.
Its default location is `.phase9-runs/signer-setup.json` (gitignored). Receipt
states are PENDING, CREATED_UNVERIFIED, and VERIFIED. The helper makes no retry
after an uncertain response; an existing receipt blocks another attempt.
Do not delete or change the receipt path to bypass reconciliation.

After a 201 response, GET account and a separate real login must confirm the
same new user ID, ACTIVE state, exact role, staff 1/P9SIGN01, no patient link,
and exactly REPORT_SIGN effective permission. The role witness and target are
checked again. Any failure stops without automatic rollback or further writes.
An unverified account may exist after a failed response/login; reconcile it
before attempting anything else. Do not interpret a failed POST as no mutation.

Read checks cannot make role grants immutable between requests. The backend
serializes account administration and locks/checks active roles, staff, and
uniqueness, but offers no conditional role-permission snapshot in account
creation. Avoid concurrent RBAC changes; post-create verification detects
observed drift but cannot undo an intervening grant. Provisioning cannot proceed
at all without the initial verified role evidence.

## Commands

From `/opt/rhu-labchain`, safe default (expected to report the current blocker):

```bash
.venv/bin/python scripts/phase9_signer_setup.py --preflight
```

If a qualifying existing single-role account becomes available, first verify:

```bash
.venv/bin/python scripts/phase9_signer_setup.py --preflight --role-verifier-login
```

**Future provisioning command, not authorized or run in this task.** It remains
blocked until the role evidence exists and preflight passes. Operator credentials
come first, existing role-verifier credentials second, and the new p9signer
password twice only after execute preflight succeeds:

```bash
.venv/bin/python scripts/phase9_signer_setup.py --execute --role-verifier-login
```

After separately authorized provisioning and successful verification:

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --preflight --signer-login
```

Enter the operator first, then `p9signer`. The runner rejects equal user IDs,
SYSTEM_ADMIN, missing/broader permissions, and missing/wrong staff linkage.
There is no fallback to the operator. No E2E execute belongs to this task.

## Production preflight, 2026-10-04 UTC

Command: `.venv/bin/python scripts/phase9_signer_setup.py --preflight`.

- PASS: authentication, operator authority, live account/role schemas, complete
  account inventory, active staff 1/P9SIGN01 with no account link, unused
  p9signer username, role and permission catalogs.
- Active role metadata: DOCTOR, LAB_STAFF, LAB_SUPERVISOR, PATIENT, SYSTEM_ADMIN.
  PHASE9_SIGNER does not exist. None of these role permission sets is exposed by
  the discovery APIs; their suitability must not be inferred from their names.
- Existing active single-role non-admin/non-patient account candidates: **0**.
- FAIL (expected safe stop, exit 1): no supported evidence establishes an exact
  REPORT_SIGN role. Existing-role reuse is **unverified**, not approved.
- No account, staff link, role, or permission assignment was changed. No report
  was signed, no workflow record created, and no Fabric write triggered. Only
  the normal login session/audit effects occurred.

## Validation

Focused tests use fake APIs and the repository's actual OpenAPI schemas; the
test network guard blocks production connections. They cover the preflight and
execute gates, inactive/later-page conflicts, role evidence, admin/extra-grant
rejection, password secrecy, immediate rechecks, exclusive intent receipts,
single-attempt POST behavior, post-create identity/login/permission failures,
and separate signer E2E behavior.

Result on 2026-10-04: **88 passed in 4.61s**. Python compilation,
`git diff --check`, and new-file whitespace validation all passed.

```bash
.venv/bin/python -m pytest tests/test_phase9_signer_setup.py tests/test_phase9_e2e_validation.py -vv -ra --tb=long
.venv/bin/python -m py_compile scripts/phase9_signer_setup.py scripts/phase9_e2e_validation.py tests/test_phase9_signer_setup.py tests/test_phase9_e2e_validation.py
git diff --check
```

All new files also receive a separate trailing-whitespace/EOF check because
`git diff --check` does not cover untracked files. No commit, push, deployment,
service restart, SQL mutation, or production provisioning execution is included.

## Phase 12B follow-up: trusted first signer

Phase 12B adds a separate local-evidence utility; it was not available during
the historical Phase 9 preflight above. See [Phase 12B RBAC matrix and initial
signer procedure](PHASE_12B_RBAC_MATRIX.md). The approved permanent LAB_SIGNER
role grants exactly REPORT_SIGN, independently verified from the local database
and bound to the live API deployment before any account creation.

`phase12_initial_signer_setup.py` defaults to preflight and uses hidden prompts,
an exclusive intent and the existing staff-account POST only. Its production
execution requires separate authorization. It does not weaken the API-only
helper's exact-role/effective-permission checks or the E2E runner's signer checks.

An existing verified p9signer may prove role membership through
`--role-verifier-login`. The old helper still refuses to provision another
p9signer or reuse occupied staff 1; its overall provisioning preflight therefore
refuses the occupied target after first-signer creation. Use the existing account
with E2E `--signer-login` instead, and disable the synthetic account through the
supported status API after validation. Preserve the permanent role and receipts.
