# Phase 10 — Account suspension and authentication activity

Implementation only. No production migrations, records, permission grants, bootstrap,
service restarts, frontend deployment, commits or pushes were performed.

## Existing architecture reused

`UserAccount` owns authentication state independently of clinical `Patient` and
`Staff` records, with one-to-one association tables. `AuthSession` stores opaque
session/CSRF hashes, creation/expiry/revocation times, IP and user-agent. Existing
login and session dependencies already accept only ACTIVE accounts. MFA completion
also checks account eligibility under a lock. Public login continues to return
`Invalid username or password.` for wrong credentials and all ineligible states.

`LoginLog` records success/failure, including unresolved usernames; `AuditLog` is the
append-only historical source for logout, account changes, MFA and password events.
No new table or authentication mechanism was introduced. Existing SYSTEM_ADMIN
bypass and the serialized last-active-administrator guard are retained.

## Schema and compatibility

Migration `20261005_01_phase_10_account_suspension.py` follows `20260924_01`.
It appends SUSPENDED and DISABLED to the existing enum, retaining the existing
ACTIVE, INACTIVE and LOCKED values in their original order. **No existing row is
mapped, rewritten or reinterpreted.** INACTIVE remains a legacy access-denied state;
the new UI uses DISABLED for administrative deactivation.

Nullable fields added to `user_account`:

- `suspended_at`: UTC DATETIME.
- `suspended_by_user_id`: indexed BIGINT FK to user_account; ON DELETE SET NULL.
- `suspension_reason`: VARCHAR(500), trimmed and required on suspension.

The reason and current suspension metadata appear only in the existing authorized
administration account response, never public login, auth/me or patient APIs.
Reactivation or another permitted transition clears current suspension fields;
the original reason remains in the immutable ACCOUNT_SUSPENDED audit record.
Activity responses deliberately omit all audit JSON, including reasons.

Downgrade performs a mandatory online check before DDL. It refuses if any account
still has SUSPENDED/DISABLED status or populated suspension metadata. It never
silently maps states or drops populated metadata. Offline downgrade is refused.
MySQL DDL is nontransactional: back up and quiesce writers before a later migration;
inspect partially completed DDL before retrying a failed deployment.

No session/login linkage, new tables, or speculative activity indexes were added.
Existing user FK indexes and exact session PK joins are reused. Large-history
performance should be measured with representative query plans before adding
indexes; SQL COUNT and merged sorting can remain expensive despite bounded results.

## Explicit status transitions

| Current | Allowed destinations through PATCH /users/{id}/status |
| --- | --- |
| ACTIVE | SUSPENDED (reason required), LOCKED, DISABLED, legacy INACTIVE |
| SUSPENDED | ACTIVE, DISABLED |
| LOCKED | ACTIVE (explicit unlock), DISABLED |
| DISABLED | ACTIVE (explicit enable) |
| INACTIVE | ACTIVE (legacy enable), DISABLED |

All other transitions, including no-op repeats, return 409. Unknown states and
invalid/missing reasons return 422. The dedicated suspend endpoint accepts only
ACTIVE → SUSPENDED. The dedicated reactivate endpoint accepts only
SUSPENDED → ACTIVE; it cannot unlock LOCKED or enable DISABLED/INACTIVE. The UI
labels unlocking and enabling separately from temporary reactivation.

Suspension always revokes sessions (`revoke_sessions` defaults to true; false is
rejected). Administration acquires the existing SYSTEM_ADMIN role mutex, rechecks
actor authorization, locks the target account, changes status, revokes all
unrevoked sessions and pending MFA challenges, and writes audit records in one
transaction. Login already locks the same account row, so a concurrent successful
login cannot leave a usable session after suspension commits. Audit failure rolls
back the status and revocation together. Previously revoked sessions never revive.

All self-status changes are rejected. The existing final usable SYSTEM_ADMIN guard
also protects role removal. Non-admin operators cannot manage administrator account
states or sessions. Patient-role or patient-linked actors cannot use the new
activity/session APIs or account-status mutations, even with accidental grants.
Requests already executing before revocation are not forcibly cancelled; subsequent
requests fail existing session/account checks.

## Patient isolation and frontend

Suspending a portal account writes only authentication/session/challenge/audit
records. It never changes the clinical patient, identifiers, orders, reports,
activation links or laboratory history. Authorized staff retain normal patient
workflows. The dialog explicitly says **Suspend Portal Account** and explains this
separation. Staff accounts use **Suspend Account**.

`/#/administration/activity` has All, Staff, Patients, Failed Logins and Active
Sessions views. Account detail shows status, last login, current suspension
metadata, active session count, recent activity, session revoke and bulk logout.
Each section independently honors its permission. Staff and patient detail pages
link to the associated administration account through bounded `/users` association
filters. Blockchain Monitor remains a separate navigation item.

Activity/session tables expose only explicit fields. User-agent text is displayed
as escaped text in a collapsible detail, without claiming a physical device.
Loading, empty, error, confirmation and permission-denied states are provided.

## API and permissions

All paths below are under `/api/v1`. Existing server-side session authorization,
CSRF enforcement on unsafe methods and `Cache-Control: no-store` apply.

| Endpoint | Permission |
| --- | --- |
| GET /users, GET /users/{id} | existing ACCOUNT_READ |
| PATCH /users/{id}/status | existing ACCOUNT_STATUS_UPDATE |
| POST /users/{id}/suspend | existing ACCOUNT_STATUS_UPDATE |
| POST /users/{id}/reactivate | existing ACCOUNT_STATUS_UPDATE |
| GET /admin/auth-activity | new AUTH_ACTIVITY_VIEW |
| GET /admin/sessions | AUTH_ACTIVITY_VIEW or new SESSION_MANAGE |
| GET /admin/users/{id}/sessions | AUTH_ACTIVITY_VIEW or SESSION_MANAGE |
| POST /admin/sessions/{id}/revoke | SESSION_MANAGE |
| POST /admin/users/{id}/sessions/revoke-all | SESSION_MANAGE |

SYSTEM_ADMIN retains its existing permission bypass (patient actors are still
excluded). Only catalog definitions were added; no permissions or grants were
written to production. ACCOUNT_READ does not implicitly grant history/session
visibility. SESSION_MANAGE alone permits the Sessions view but not activity.

Suspend body: `{"reason":"Required administrative reason"}`. Optional
`revoke_sessions` accepts only true. Reactivate and revocation actions need no body.
Existing status PATCH accepts `account_status` and a reason only for SUSPENDED.
`/users` additionally accepts `staff_id` and `patient_id` for precise association
lookup without browser-side scans of all accounts.

Activity filters: account_type STAFF/PATIENT, activity_type, status
SUCCESS/FAILED/RECORDED, user_id, search (current username or linked display name,
100 characters, literal wildcard escaping), exact IP (45 characters), date_from,
date_to. Aware datetimes normalize to UTC; naive inputs mean UTC. Reversed date
ranges are rejected. Page defaults to 1, maximum 10,000; page_size defaults to 20,
maximum 100. Session filters: account_type, user_id, search, state (default ACTIVE),
with the same pagination bounds. All filtering/counting/pagination is SQL-side;
only a bounded page is loaded into application memory.

## Trustworthy activity projection

The projection uses SQL UNION ALL of LoginLog and an allowlist of AuditLog events,
then safe identity joins and bounded pagination. Stable IDs are `login:<id>` and
`audit:<id>`, sorted by timestamp, source and source ID. AUTH_LOGIN audit rows are
omitted to avoid duplicating LoginLog evidence. Unknown login attempts retain null
user identity; **attempted usernames are never returned or searchable**.

AuditLog.user_id is the actor, not necessarily the target. Account events resolve
subjects from user_account record_id; session events resolve subjects from the
exact AuthSession record_id. Current linked names and account types are labels,
not historical identity snapshots. No clinical fields are selected.

| Persisted source | Display activity |
| --- | --- |
| LoginLog.SUCCESS / FAILED | LOGIN_SUCCESS / LOGIN_FAILED |
| AUTH_LOGOUT | LOGOUT |
| AUTH_SESSION_REVOKED / AUTH_ALL_SESSIONS_REVOKED | SESSION_REVOKED |
| ACCOUNT_SUSPENDED / ACCOUNT_REACTIVATED | same names |
| ACCOUNT_LOCKED / ACCOUNT_DISABLED | same names |
| Legacy ACCOUNT_STATUS_UPDATE | ACCOUNT_LOCKED or ACCOUNT_DISABLED when explicitly recorded; otherwise ACCOUNT_STATUS_UPDATED |
| PASSWORD_CHANGE | PASSWORD_CHANGED |
| MFA_CHALLENGE_SUCCESS / MFA_CHALLENGE_FAILED | MFA_SUCCESS / MFA_FAILED |
| ACCOUNT_MFA_RESET | MFA_RESET |

INACTIVE is not relabeled DISABLED in historical records. Audit JSON, suspension
reasons, attempted usernames, passwords, tokens/hashes, CSRF secrets, MFA material
and clinical records are excluded from activity/session responses. Account status
mutations emit their explicit event and an AUTH_ALL_SESSIONS_REVOKED event when
access is removed. Other explicit status actions retain ACCOUNT_STATUS_UPDATE.

Logout uses the persisted AUTH_LOGOUT event's exact AuthSession ID. LoginLog has
no guaranteed session FK; its logout_time is left untouched. No “latest login”
heuristic or new relationship is added merely to populate that column. Login and
most account/MFA events have no reliably linked user-agent; they show Not recorded.

## Session administration

Sessions expose integer ID, user label/type, created/expiry/revocation timestamps,
IP, user-agent, current-session flag and state. There is no invented last-activity
time. REVOKED takes precedence over EXPIRED; otherwise an unexpired row is ACTIVE.
Session state describes persisted row lifetime, not an assertion about physical
device activity. Account access still requires ACTIVE account state.

Single-session revoke and bulk revoke serialize on the target account row. They
revoke active unexpired rows, return `revoked_count`, and append a minimal audit
event including that count, even for an idempotent zero-count request. Bulk revoke
also invalidates pending MFA challenges. The current session cannot be revoked
through these admin controls, and bulk revoke of the actor's own account is rejected;
the normal Log out action remains available. Other accounts can sign in again
when active; suspension is the action that blocks further authentication.

## Changed files

Backend implementation:
`app/models/auth.py`, `app/schemas/administration.py`,
`app/services/administration_service.py`, `app/api/administration.py`,
`app/schemas/auth_activity.py`, `app/services/auth_activity_service.py`,
`app/api/auth_activity.py`, `app/services/permission_catalog.py`, `app/main.py`.

Migration: `migrations/versions/20261005_01_phase_10_account_suspension.py`.

Frontend: `frontend/src/pages/AuthActivity.tsx`, `frontend/src/pages/People.tsx`,
`frontend/src/App.tsx`, `frontend/src/layouts/Shell.tsx`,
`frontend/src/styles/main.css`.

Tests: `tests/test_phase_10_auth_activity.py`, `tests/test_phase_10_migration.py`,
`tests/mysql_phase10_probe.py`, `frontend/src/test/auth-activity.test.tsx`.
Updated regression expectations/fixtures: `tests/test_phase_3b_identity_admin.py`,
`tests/test_phase_2a_models.py`, `tests/test_phase_2a_migration.py`,
`tests/phase8b_schema.py`, `tests/test_phase_8b_migration.py`,
`tests/mysql_phase8b_probe.py`, `frontend/src/test/workflows.test.tsx`.
Historical migration files remain unchanged; old probes are pinned to their own
revision rather than inadvertently testing the new head as Phase 8B.

## Validation and later deployment

Validation completed across focused runs:

- 43 Phase 10 authentication/activity/session tests passed.
- 73 existing administration regression tests passed (including the corrected
  nine-revision chain assertion).
- 29 additional migration/model checks passed, including offline MySQL DDL,
  SQLite preservation/downgrade guards, native disposable MySQL schema parity,
  login/suspension serialization, and guarded native downgrade.
- 62 relevant frontend tests passed across auth-activity, workflows and auth.
- `npm run build` passed: TypeScript and Vite, 1,918 modules.
- Patch whitespace and changed Python compilation checks passed.

That is 145 distinct focused backend cases passing across the validation runs.
The first disposable MySQL initialization hit its 60-second fixture timeout; the
Phase 10 fixture now limits memory and allows 180 seconds for initialization.
The native test then passed. Initial implementation/test-compatibility failures
were corrected and their affected checks rerun. Existing test-client deprecation
warnings remain unrelated to Phase 10.

Backend tests use synthetic settings and a network guard. Native MySQL tests use a private
/tmp datadir, a validated Unix socket, no host defaults and no TCP listener; they
never use production credentials. The full backend suite was not run.

Later, with separate deployment authorization:

1. Review changes and back up the database; verify deployed migration is 20260924_01.
2. Quiesce application writers and apply `alembic upgrade 20261005_01` through the
   normal migration procedure. Do not start the new backend against the old schema.
3. Publish the reviewed backend and locally built frontend together; restart only
   through the approved maintenance procedure.
4. If non-SYSTEM_ADMIN operators need access, register the two permission catalog
   entries using the existing permission-metadata process and explicitly review
   grants. Do not run bootstrap_roles or grant broad access automatically.
5. Smoke-check generic login failures, authorized/private activity and session
   access, CSRF rejection, and a separately approved test account lifecycle.
6. Preserve audit history. Do not downgrade if new states/metadata remain; the guard
   deliberately requires a reviewed data-preservation decision.

Known limits: no historical device inference or last-activity tracking, no recovery
of unpersisted events, no logout_time backfill, bounded offset pagination (new events
can move pages), and no representative-volume production query-plan benchmark.
