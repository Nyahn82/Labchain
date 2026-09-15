# Phase 3B — Identity and administrative APIs

Phase 3B adds identity records, controlled staff accounts, account status and role
management using the existing normalized schema. No schema migration is needed.
The single Alembic head remains `20260915_01`; all five migrations are unchanged.

**Patient account activation is NOT part of Phase 3B.** There is no patient
registration or `/patients/{id}/account` endpoint. `PATIENT_ACCOUNT_LINK` is read
only for an existing account's safe identity summary and is never written here.
Laboratory operations and frontend development are outside this phase.

## Endpoints and authorization

Every path below starts with `/api/v1`. Every endpoint requires an authenticated,
unexpired, unrevoked session on an ACTIVE account. All POST, PATCH and PUT requests
also require the session-bound `X-CSRF-Token` header. Missing authentication returns
401; missing permission or invalid CSRF returns 403.

| Resource | Create | List/detail | Update | Permissions |
| --- | --- | --- | --- | --- |
| Patients | POST `/patients` | GET `/patients`, `/patients/{patient_id}` | PATCH `/patients/{patient_id}` | `PATIENT_CREATE`, `PATIENT_READ`, `PATIENT_UPDATE` |
| Staff | POST `/staff` | GET `/staff`, `/staff/{staff_id}` | PATCH `/staff/{staff_id}` | `STAFF_CREATE`, `STAFF_READ`, `STAFF_UPDATE` |
| Referring facilities | POST `/referring-facilities` | GET `/referring-facilities`, `/referring-facilities/{referring_facility_id}` | PATCH `/referring-facilities/{referring_facility_id}` | `REFERRING_FACILITY_CREATE`, `REFERRING_FACILITY_READ`, `REFERRING_FACILITY_UPDATE` |
| Requesting physicians | POST `/physicians` | GET `/physicians`, `/physicians/{physician_id}` | PATCH `/physicians/{physician_id}` | `PHYSICIAN_CREATE`, `PHYSICIAN_READ`, `PHYSICIAN_UPDATE` |

| Administrative operation | Permission |
| --- | --- |
| POST `/staff/{staff_id}/account` | `ACCOUNT_CREATE`; nonempty initial roles also require `ROLE_ASSIGN` for a non-superuser |
| GET `/users`, `/users/{user_id}` | `ACCOUNT_READ` |
| PATCH `/users/{user_id}/status` | `ACCOUNT_STATUS_UPDATE` |
| PUT `/users/{user_id}/roles` | `ROLE_ASSIGN` |
| GET `/roles`, `/permissions` | `ROLE_READ` |

An active `SYSTEM_ADMIN` role bypasses ordinary permission checks, using the
existing Phase 3A dependency. It does not bypass authentication, CSRF, validation,
transactional checks or last-administrator protection. OpenAPI uses Patients,
Staff, Physicians, Referring Facilities and Administration tags and dedicated
Pydantic response schemas. Creates return 201; reads and updates return 200.

## Permission bootstrap

```bash
cd /opt/rhu-labchain
.venv/bin/python -m app.cli.bootstrap_permissions
```

The application catalog contains 17 stable codes:

```text
PATIENT_READ                  PATIENT_CREATE                  PATIENT_UPDATE
STAFF_READ                    STAFF_CREATE                    STAFF_UPDATE
PHYSICIAN_READ                PHYSICIAN_CREATE                PHYSICIAN_UPDATE
REFERRING_FACILITY_READ       REFERRING_FACILITY_CREATE       REFERRING_FACILITY_UPDATE
ACCOUNT_READ                  ACCOUNT_CREATE                  ACCOUNT_STATUS_UPDATE
ROLE_READ                     ROLE_ASSIGN
```

Each has a human-readable name and description in
`app/services/permission_catalog.py`. The CLI inserts only missing permissions
and commits once. Repeated runs preserve existing names, descriptions, unrelated
permissions and all role assignments/grants. It never deletes permissions or
automatically grants permissions to roles. Run one bootstrap at a time; if a
concurrent bootstrap hits uniqueness enforcement, the failed command rolls back
and can be retried. Database errors produce a generic message and nonzero exit.

Existing roles can be bootstrapped separately with
`.venv/bin/python -m app.cli.bootstrap_roles`. Role-permission editing APIs are
outside Phase 3B; grant policy remains an explicitly controlled administrative
setup task. SYSTEM_ADMIN needs no blanket permission grants.

## Pagination and search

Patient, staff, physician, facility and user lists return:

```json
{"items": [], "page": 1, "page_size": 20, "total": 0}
```

`page` must be at least 1. `page_size` defaults to 20 and accepts 1–100. Ordering is
ascending primary key. `total` is the count after applying filters; an out-of-range
page returns empty items. `search` is a trimmed, case-insensitive substring of up
to 200 characters. SQL wildcard characters in search are escaped and treated
literally. Matching follows database collation. Separate count/page queries use
the existing request transaction; concurrent writes may be visible on a later
request.

| List | Search fields | Optional exact filters |
| --- | --- | --- |
| Patients | patient_code, first_name, middle_name, last_name | patient_code, sex |
| Staff | staff_code, first_name, middle_name, last_name | staff_code, is_active |
| Facilities | facility_name | — |
| Physicians | first_name, middle_name, last_name, license_number | referring_facility_id, is_active |
| Users | username | account_status |

Roles and permissions are small read-only catalogs returned as arrays ordered by
code and ID. Role discovery includes inactive roles; account metadata lists all
assigned role codes. Effective authorization uses active roles only.

## Identity validation and patient data handling

Patient create requires `patient_code`, `first_name`, `last_name`. Optional fields
are `middle_name`, `suffix`, `birth_date`, `sex`, `civil_status`, `nationality`,
`contact_number`, `email` and `address`. Patient age is neither accepted nor stored.
If a later consumer needs current age, it must calculate it from `birth_date` and
the current date; Phase 3B exposes the birth date, not an age snapshot.

Staff create requires `staff_code`, `first_name`, `last_name`. Optional fields are
`middle_name`, `suffix`, `position_title`, `license_number`, `contact_number`,
`email`, `is_active` (default true). Credentials belong only to `USER_ACCOUNT`.

Text fields are trimmed with casing preserved. Supplied text must be nonblank;
use null to clear nullable fields. Field lengths follow existing VARCHAR bounds;
addresses are limited to 16,000 characters to fit MySQL TEXT even with four-byte
UTF-8 characters. Supplied emails undergo syntax validation without DNS lookups.
Sex accepts exactly `M`, `F`, `Other` or null. IDs must be positive signed BIGINT
values. Request schemas reject unknown fields, generated IDs, timestamps, age,
passwords and password hashes in identity records.

PATCH updates only submitted fields. Omitted fields retain their values. Explicit
null is accepted only for nullable fields. Required names/codes and `is_active`
cannot be set to null. Empty PATCH requests return the current record and write
an audit entry with an empty changed-field list. Patient/staff `updated_at` changes
when a field value changes.

Expected unique or business conflicts return 409, missing records 404, invalid
fields or relationships 422. Input errors never echo the request body; the error
message is deliberately generic to avoid reflecting PII or credentials. Unexpected
database failures return a generic 503. Private responses use `Cache-Control:
no-store`. Safe account summaries exclude contact details, passwords, credential
hashes, session hashes and CSRF hashes.

## Staff, physician and facility lifecycle

No identity DELETE endpoints exist. Staff and physicians are deactivated by
PATCH with `is_active: false`. Existing relationships are preserved. Staff record
activity and account status are separate: staff deactivation prevents new account
creation; disable the linked USER_ACCOUNT separately to revoke login access.
This follows Phase 3A's account-based authentication policy.

Facility create requires `facility_name`; optional fields are `facility_type`,
`address`, `contact_number`. Facilities have no active flag in the existing schema.
Physician create requires `first_name`, `last_name`; optional fields are
`middle_name`, `suffix`, `license_number`, `specialization`,
`referring_facility_id`, `contact_number`, `is_active` (default true). A nonnull
facility ID must refer to an existing facility or the API returns 422. PATCH can
clear the relationship with null. Facilities/physicians remain available for
existing references after updates; no laboratory operations are added.

## Staff account creation

```json
{"username": "synthetic-staff", "password": "Synthetic-only-password-123!", "role_codes": ["LAB_STAFF"]}
```

The staff row must exist, be active and have no existing account. Username is
trimmed, 1–60 characters and unique. Passwords retain their exact content and
must contain 12–1024 characters, matching the Phase 3A bootstrap policy. The
existing Argon2id security service hashes the password. Requests use SecretStr;
plaintext credentials are never logged, audited or returned.

Unknown or inactive roles return 422; role codes are case-sensitive and duplicate
codes are normalized. An empty role list is allowed. The account is ACTIVE, with
one STAFF_ACCOUNT_LINK and one USER_ROLE per selected role. Each assignment has
the authenticated actor's `assigned_by` and current UTC `assigned_at`. Account,
link, role assignments and audit entry commit together. Any failure rolls back
the entire operation, including uniqueness races. Duplicate username or an
existing staff account returns 409; inactive staff also returns 409.

## Role assignment and administrator protections

PUT replaces the complete role set; an empty list removes all assignments where
allowed. Retained roles receive new assignment provenance as part of replacement.
Unknown/inactive roles are rejected before deletion. All assignments and the audit
event share a transaction. Permissions are re-read server-side; client-supplied
actor IDs or authorization claims are rejected.

Delegated non-superusers need ROLE_ASSIGN, cannot assign SYSTEM_ADMIN, cannot
manage an account assigned SYSTEM_ADMIN, and can assign only roles whose effective
permissions are a subset of their own. The same grant checks apply to initial
roles during staff account creation. ACCOUNT_CREATE alone permits creating a
roleless account. Only SYSTEM_ADMIN may change administrator account status.
These rules prevent account creation or role replacement from becoming an
indirect privilege-escalation path.

A usable administrator means an ACTIVE USER_ACCOUNT assigned the active
SYSTEM_ADMIN role, matching Phase 3A authentication. A staff link or current
session is not required. A LOCKED/INACTIVE account cannot count as a replacement
administrator. Removing SYSTEM_ADMIN or disabling/locking the last usable
administrator returns 409, including self-management. Once another usable
administrator exists, these operations are allowed.

Administrative transactions lock the existing SYSTEM_ADMIN ROLE row first as a
shared database mutex across workers, then lock and refresh the relevant accounts
and assignments. Last-administrator checks use current `SELECT ... FOR UPDATE`
reads, so an older MySQL REPEATABLE READ snapshot opened by authentication cannot
cause two concurrent operations to remove both remaining administrators. This
protection covers the application write paths; direct database maintenance must
preserve the same invariant. No schema additions or process-local locks are used.

## Account disabling and session revocation

PATCH status accepts only ACTIVE, INACTIVE or LOCKED. Changing to INACTIVE/LOCKED
revokes every unrevoked auth_session for that user, including expired rows, in the
same transaction as status and audit updates. Repeating the request revokes any
remaining unrevoked rows. Reactivation does not restore old sessions; a fresh
login is required. Existing Phase 3A checks continue to reject disabled accounts
on every new request. An already-running request may finish.

Login now locks its USER_ACCOUNT before issuing a session. Login and disabling
therefore serialize on the same row: a session issued just before disabling is
revoked; a login following disabling is denied. No unrelated sessions are revoked.

## Audit strategy and transaction boundaries

Successful creates/updates write PATIENT_CREATE/UPDATE, STAFF_CREATE/UPDATE,
PHYSICIAN_CREATE/UPDATE, REFERRING_FACILITY_CREATE/UPDATE, STAFF_ACCOUNT_CREATE,
ACCOUNT_STATUS_UPDATE and USER_ROLES_UPDATE events. Every event records actor,
action, entity type, record ID, UTC time and validated client IP when available.

Identity events contain changed field names only. Account creation records staff
and role IDs; role replacement records old/new role IDs; status changes record
old/new status. Complete identity records, names, contact details, birth dates,
passwords, hashes and session/CSRF tokens never enter audit values. Reads do not
produce administrative mutation audit entries.

Authentication begins the request's SQLAlchemy transaction. The mutation context
owns its single commit, with rollback on any exception. Response schemas are
built before commit; no successful mutation response is returned until commit
succeeds. Audit failure also rolls back the underlying mutation. No service
independently commits account creation, links, role rows or session revocation.

## Synthetic curl examples

These examples assume a previously authenticated synthetic test administrator.
Use an HTTPS cookie jar from `/api/v1/auth/login`; send the current `rhu_csrf`
cookie value in `X-CSRF-Token`. Do not use real patient information for smoke tests.

```bash
LABCHAIN_URL=https://labchain.online
LABCHAIN_JAR=/tmp/labchain-synthetic.cookies
# Set LABCHAIN_CSRF from the current synthetic test session's rhu_csrf cookie.

curl --fail-with-body -b "$LABCHAIN_JAR" "$LABCHAIN_URL/api/v1/patients?page=1&page_size=20&search=SYNTH"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"patient_code":"P-SYNTH-3B","first_name":"Synthetic","last_name":"Example","birth_date":"2000-02-29","sex":"Other"}' \
  "$LABCHAIN_URL/api/v1/patients"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"staff_code":"S-SYNTH-3B","first_name":"Synthetic","last_name":"Staff"}' \
  "$LABCHAIN_URL/api/v1/staff"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"facility_name":"Synthetic Referral Clinic"}' \
  "$LABCHAIN_URL/api/v1/referring-facilities"

# Set these numeric IDs from the synthetic create responses above.
# LABCHAIN_STAFF_ID, LABCHAIN_FACILITY_ID
curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"first_name\":\"Synthetic\",\"last_name\":\"Physician\",\"referring_facility_id\":$LABCHAIN_FACILITY_ID}" \
  "$LABCHAIN_URL/api/v1/physicians"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"username":"synthetic-staff-3b","password":"Synthetic-only-password-123!","role_codes":["LAB_STAFF"]}' \
  "$LABCHAIN_URL/api/v1/staff/$LABCHAIN_STAFF_ID/account"

# Set LABCHAIN_USER_ID from the account create response.
curl --fail-with-body -X PUT -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"role_codes":["LAB_STAFF"]}' "$LABCHAIN_URL/api/v1/users/$LABCHAIN_USER_ID/roles"

curl --fail-with-body -X PATCH -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"account_status":"INACTIVE"}' "$LABCHAIN_URL/api/v1/users/$LABCHAIN_USER_ID/status"
```

## Verification and Hostinger deployment

Run from the reviewed Phase 3B checkout already placed at `/opt/rhu-labchain`.
Do not replace production `.env` or change Nginx, Certbot, UFW, service definitions,
domain or ports. No `alembic upgrade` is necessary for this phase.

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/alembic heads
.venv/bin/alembic current
# Both should identify 20260915_01 before bootstrapping.
.venv/bin/python -m app.cli.bootstrap_permissions
sudo systemctl restart rhu-labchain-node1
sudo systemctl is-active rhu-labchain-node1
curl --fail --silent --show-error https://labchain.online/api/v1/health
curl --fail --silent --show-error https://labchain.online/api/v1/ready
```

These are deployment instructions; implementation/testing does not execute the
production bootstrap or restart the production service. `python -m pytest` is
used so the repository root is on the module path.

The full suite includes all Phase 2/3A regressions, Phase 3B HTTPS API tests,
fault-injected rollback checks and real MySQL concurrency tests. The latter start
a disposable MySQL instance under `/tmp/rhu-phase3b-mysql-*` with its own data
folder, Unix socket, no host configuration, no TCP networking and MySQL X disabled.
They terminate that instance and delete its temporary data after testing. They
never connect to production MySQL. If `mysqld` is unavailable those tests are
explicitly skipped; the remaining tests continue to block network connections.

Phase 3B ends here. Patient activation and laboratory-master APIs require separate
implementation phases.
