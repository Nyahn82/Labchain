# Phase 6A — patient activation and secure portal APIs

Phase 6A provides staff-controlled account activation and server-side ownership
checks for released laboratory reports. Patients use the existing Argon2id login,
opaque server-side sessions, Secure cookies and CSRF implementation.

**Phase 6A does NOT implement MFA. MFA is Phase 6B.** Password reset, account
recovery, email/SMS delivery, patient self-edit, patient search, internal order or
specimen workflow access, unreleased results, blockchain runtime and frontend
work are outside this phase.

## Migration and configuration

The one new migration is
`migrations/versions/20260916_01_phase_6a_patient_activation.py`:

* revision: `20260916_01`
* down_revision: `20260915_01` (the repository head inspected before development)
* only new table: `patient_activation_token`

| Column | Definition |
| --- | --- |
| activation_token_id | BIGINT, primary key, auto increment |
| patient_id | BIGINT NOT NULL, indexed FK to patient.patient_id |
| token_hash | CHAR(64) NOT NULL, UNIQUE |
| issued_by_user_id | BIGINT NOT NULL, indexed FK to user_account.user_id |
| created_at | DATETIME NOT NULL, UTC |
| expires_at | DATETIME NOT NULL, indexed, UTC |
| used_at | nullable DATETIME, UTC |
| revoked_at | nullable DATETIME, UTC |

The table uses existing InnoDB/utf8mb4 conventions, named constraints and no
cascading deletes. History remains after use, expiry or revocation. No plaintext
token or password column exists. Prior migrations are unchanged. Downgrade drops
only this table and therefore destroys its activation history; do not use a
production downgrade as a routine deployment rollback.

The existing Settings system and `.env.example` add:

```dotenv
PATIENT_ACTIVATION_TTL_MINUTES=30
```

The default is 30 minutes; accepted values are 1–1440. Application environment
variables override `.env`. Production `.env` was not modified. No dependency is
added and no production domain is hardcoded. Existing Phase 5B report storage and
public verification settings remain required for report release/download.

## Controlled activation workflow

Authorized RHU staff first verify the patient's identity through the RHU's
operational process. Staff call `POST /api/v1/patients/{patient_id}/activation-token`
with an authenticated session, valid CSRF header and PATIENT_ACCOUNT_ACTIVATE.
SYSTEM_ADMIN keeps the existing permission bypass. This is controlled
provisioning, not public signup or demographic matching.

The service locks the patient row, verifies that PATIENT_ACCOUNT_LINK is absent,
revokes previous unused/unexpired/non-revoked tokens for that patient, generates
`secrets.token_urlsafe(24)` (192 random bits; 32 URL-safe characters), and stores
only the lowercase SHA-256 token hash with issuer, issue time and expiration.
Issuance and its audit event commit together. Reissuance failure rolls back the
revocation of the previous token as well as the new token.

The 201 response returns activation_token exactly once, expires_at and
patient_code to the authorized staff caller, with `Cache-Control: no-store`.
There is no token retrieval endpoint. Staff must hand over the token through the
approved RHU process. This phase does not send email/SMS or create activation
URLs containing the token. Public redemption submits it in a JSON request body.

`GET /api/v1/patients/{patient_id}/activation-status` allows
PATIENT_ACCOUNT_ACTIVATE or existing ACCOUNT_READ. It returns only one status:
NOT_ACTIVATED, TOKEN_ACTIVE, TOKEN_EXPIRED or ACTIVATED. It never returns either
plaintext tokens or their hashes. An existing account link takes precedence even
if the linked account is disabled; reissuance is not an account recovery bypass.

The permission bootstrap idempotently adds PATIENT_ACCOUNT_ACTIVATE and preserves
all existing permissions/grants. It does not assign that permission to staff roles.

## Public redemption and login

`POST /api/v1/patient/activate` is public and does not consume or depend on an
existing cookie session, so it does not require CSRF. Cookies already present do
not select the account or patient being activated. Global CSRF behavior on
existing authenticated unsafe routes is unchanged.

```json
{
  "activation_token": "OPAQUE_TOKEN_HANDED_OVER_BY_RHU_STAFF",
  "username": "synthetic.patient",
  "password": "Synthetic-password-123!"
}
```

Inputs are allowlisted. Username normalization uses the existing `Username` type:
trim surrounding whitespace, retain case, length 1–60. MySQL's existing unique
username constraint/collation remains the final uniqueness authority. Passwords
use the existing creation policy of 12–1024 characters and the existing Argon2id
hashing service. Password/token request fields use SecretStr; validation responses
do not echo submitted values. Browser-selected patient IDs, roles, account IDs,
status, token hashes and other unexpected fields are rejected.

Redemption locates the hash, locks the patient before the token, and re-reads the
token/link using current locking reads. Expired, used, revoked, unknown and
already-linked tokens all return HTTP 400 with:

```json
{"detail":"Invalid or expired activation token."}
```

For a valid token, the service requires the canonical active PATIENT role,
checks username availability, hashes the password and atomically creates:

* ACTIVE USER_ACCOUNT;
* the authoritative one-to-one PATIENT_ACCOUNT_LINK;
* exactly one USER_ROLE assignment, for PATIENT;
* token used_at;
* PATIENT_ACCOUNT_ACTIVATE audit.

USER_ROLE.assigned_by is the token's issuing staff account, documenting the
source of provisioning authority; assigned_at is the activation event time. The
public caller cannot choose a role. No staff or administrator role is assigned.
Missing/inactive PATIENT configuration returns a generic 503 without consuming
the token. A duplicate username returns 409; a database uniqueness conflict also
returns controlled 409. Any account/link/role/audit/commit failure rolls back the
whole activation, leaving the token unused.

The 201 response contains only user_id, username, ACTIVE account_status and the
PATIENT role. Activation does not log in automatically or issue new auth tokens.
Patients then use `POST /api/v1/auth/login`, which continues to write LOGIN_LOG,
issue the existing session and CSRF cookies, and support normal logout. There is
no second password-authentication flow, JWT or localStorage token.

## Concurrency and abuse boundary

Issuance and redemption serialize on the same patient row, including in the
absence of a token/link row. Current reads prevent a previously opened MySQL
REPEATABLE READ snapshot from accepting a superseded token. The existing
patient/account uniqueness constraints and token-hash UNIQUE constraint remain
final protection. Deadlock victims retry the entire rolled-back operation using
the existing bounded retry helper. Competing issuance leaves one usable token;
competing redemption creates at most one account/link and consumes the token once.

The repository has no application rate-limit mechanism to reuse. **Production
edge/application rate limiting for `/api/v1/patient/activate` is required before
public rollout**, including controls on repeated invalid requests and expensive
password hashing. No new distributed limiter or infrastructure dependency is
introduced. Nginx is not changed. The existing login endpoint's rate-limit
boundary also remains an operational responsibility. Do not enable request-body
logging for activation/login credentials.

## Portal ownership boundary

Every portal route requires a valid authenticated account with the active PATIENT
role and a valid account link. SYSTEM_ADMIN does not bypass this role/link
requirement. A PATIENT account without a link receives a controlled 403.

`get_current_patient` derives identity by joining the authenticated user to
PATIENT_ACCOUNT_LINK and PATIENT. Browser patient IDs/codes never select that
identity. List/filter inputs reject unexpected parameters such as patient_id.

`owned_reports` and `require_patient_report_ownership` centralize:

```text
authenticated USER_ACCOUNT.user_id
  -> PATIENT_ACCOUNT_LINK.user_id
  -> PATIENT_ACCOUNT_LINK.patient_id
  == LAB_ORDER.patient_id
  <- LAB_REPORT.order_id
  AND LAB_REPORT.report_status == RELEASED
```

Detail/download first qualify the report through that join, acquire the same
order-before-report locks used by Phase 5B, then repeat the entire ownership and
RELEASED predicate with a current locking read. Replacing the report ID cannot
bypass ownership. Nonexistent, another patient's, GENERATED, APPROVED and REVOKED
reports all return the same HTTP 404 `{"detail":"Report not found."}`. No
ownership-specific explanation is exposed. Requests are authorized before
response delivery; revocation does not retract bytes already delivered to a client.

Patient outputs use independent explicit schemas rather than exposing staff
ReportDetail responses. Internal actor IDs, template IDs, live source-result IDs,
staff identifiers, signature paths, PDF paths, remarks, authentication hashes and
verification tokens/hashes are omitted. Other patients' data, administrative
searches and internal specimen/order workflows are not exposed.

## Portal routes

All routes use the existing `/api/v1` prefix and return `Cache-Control: no-store`.

| Method and path | Behavior |
| --- | --- |
| GET `/patient/me` | Only linked patient's allowed demographic/contact fields |
| GET `/patient/reports` | Only own RELEASED report summaries |
| GET `/patient/reports/{report_id}` | Own released historical snapshot detail; audited |
| GET `/patient/reports/{report_id}/pdf` | Own released, integrity-checked PDF; audited |
| GET `/patient/access-history` | Only allowed current-user access events; paginated |

The profile contains patient_id, patient_code, first/middle/last names, suffix,
birth_date, sex, civil_status, nationality, contact_number, email and address.
There is no PATCH patient/me endpoint. Identity changes stay with authorized RHU
staff. Existing general administrative endpoints retain their RBAC checks.

Report list accepts page (default 1), page_size (default 20, maximum 100),
date_from/date_to (inclusive UTC release dates) and search (maximum 200 characters,
escaped literal matching of report_code/order_code). Reversed dates and unknown
query fields are rejected. Ordering is released_at DESC, report_id DESC. Each
summary contains report_id, report_code, version_no, released_at, order_code,
issuing_facility and stored verification_status. A metadata status is not a
fresh artifact-integrity guarantee; the PDF route performs that check.

Report detail contains safe metadata, facility display information, historical
patient and result snapshots, printable signatories and release information.
Historical clinical content uses Phase 5A snapshots, not mutable patient/test
values. Facility and staff display metadata have the existing Phase 5B semantics;
the immutable final PDF remains the exact released artifact. Result ordering is
the existing snapshot sort order.

## PDF integrity and audit behavior

Patient download accepts only an owned RELEASED report with exactly one
AUTHENTIC, non-revoked verification record. It reuses Phase 5B safe storage reads,
SHA-256 calculation and constant-time comparison with the stored final-artifact
hash. Missing, unsafe, unreadable, altered or unavailable verification/artifact
state returns controlled HTTP 409 and commits REPORT_INTEGRITY_MISMATCH with HIGH
severity. No path is returned and no PDF is streamed on failure.

Successful delivery streams the same validated bytes without reopening the file,
using application/pdf, a server-owned attachment filename and no-store headers.
No report file is regenerated or modified. Access-audit failure prevents response
delivery. PDFs remain memory-buffered as in Phase 5B.

| Event | Audit content |
| --- | --- |
| PATIENT_ACTIVATION_TOKEN_ISSUE | Issuing user, patient reference, event time |
| PATIENT_ACCOUNT_ACTIVATE | Newly activated user/account reference, event time |
| PATIENT_REPORT_VIEW | Current user, entity_type LAB_REPORT, report reference |
| PATIENT_REPORT_DOWNLOAD | Current user, entity_type LAB_REPORT, report reference |
| REPORT_INTEGRITY_MISMATCH | Existing HIGH severity/fixed failure-code policy |

Activation and successful patient-access audits have no old_value/new_value
payload. No activation token, token hash, password, password hash, session/CSRF
token, patient demographic details or report results are duplicated into audit
JSON. Existing request-IP auditing remains internal and is not included in portal
history. Lists do not create access-audit noise. Existing auth/login continues
its own single LOGIN_LOG path.

Access history accepts page/page_size and exposes only action, timestamp and safe
report_code. It filters both the authenticated user and the allowlisted
PATIENT_REPORT_VIEW/PATIENT_REPORT_DOWNLOAD actions with entity_type LAB_REPORT,
and rechecks account-linked report ownership. Staff events and other users' events
are excluded. Ordering is timestamp DESC, audit_id DESC. Previously accessed
revoked reports may retain safe references in history, without restoring detail
or PDF access. No audit JSON or IP addresses are returned.

## Revocation and supersession

A report revoked through Phase 5B immediately leaves the normal patient list;
subsequent detail/PDF requests return neutral 404. Its public QR continues to say
REVOKED. Staff historical access remains available with the existing permissions.
When V2 is released and automatically revokes V1, V2 appears in the patient list
and V1 disappears. Historical database records and PDFs remain intact. Draft or
approved successors never appear in the patient portal.

## Hostinger deployment commands (operator steps, not executed by development)

Deploy the reviewed code into `/opt/rhu-labchain` using the existing release
process. Keep a database backup before applying the additive migration. Do not
change Nginx, Certbot, UFW, ports or the systemd unit. No new report directories
are needed. The existing Phase 5B private PDF storage must remain available.

Run as `rhuadmin` and stop on any error:

```bash
cd /opt/rhu-labchain
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -vv -ra --tb=long
python -m alembic heads
python -m alembic current
```

The new repository head is `20260916_01`; the expected deployed predecessor is
`20260915_01`. If current is different, investigate deployment history first.
The existing private `.env` may optionally set PATIENT_ACTIVATION_TTL_MINUTES=30;
the same default applies if absent. Preserve all existing settings and do not
copy `.env.example` over production `.env`. Development did not edit it.

```bash
python -m alembic upgrade 20260916_01
python -m alembic current
python -m app.cli.bootstrap_roles
python -m app.cli.bootstrap_permissions
sudo systemctl restart rhu-labchain-node1.service
systemctl is-active rhu-labchain-node1.service
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/ready
curl --fail --silent --show-error https://labchain.online/api/v1/health
curl --silent --show-error -i https://labchain.online/api/v1/patient/me
```

The final unauthenticated request should return 401 without patient data. Role
bootstrap adds missing core roles but preserves an existing inactive PATIENT
role; an administrator must resolve that configuration before activation.
Assign PATIENT_ACCOUNT_ACTIVATE only to designated provisioning staff through
existing authorized administration APIs. Do not grant clinical/staff report or
master-data permissions to PATIENT merely to make portal access work. Configure
the activation rate-limit boundary through separately authorized deployment work
before rollout; this phase does not edit the edge configuration.

## Synthetic API examples

Use staging and synthetic data only. `staff.cookies` contains a staging staff
session and `STAFF_CSRF` its CSRF cookie value. Avoid entering real passwords or
activation tokens into shell history or sharing credential-bearing files.

```bash
STAGING_ORIGIN=https://staging.example.test
curl --fail-with-body -b staff.cookies -H "X-CSRF-Token: $STAFF_CSRF" \
  -X POST "$STAGING_ORIGIN/api/v1/patients/101/activation-token"
curl --fail-with-body -b staff.cookies \
  "$STAGING_ORIGIN/api/v1/patients/101/activation-status"
```

For a synthetic activation, save the following JSON to a private temporary file
named `synthetic-activation.json`, substituting the one-time staging token:

```json
{"activation_token":"STAGING_TOKEN","username":"synthetic.patient","password":"Synthetic-password-123!"}
```

Save a separate `synthetic-login.json` with only username and password. Neither
file belongs in source control. Then:

```bash
chmod 600 synthetic-activation.json synthetic-login.json
curl --fail-with-body -H 'Content-Type: application/json' \
  --data-binary @synthetic-activation.json "$STAGING_ORIGIN/api/v1/patient/activate"
curl --fail-with-body -c patient.cookies -H 'Content-Type: application/json' \
  --data-binary @synthetic-login.json "$STAGING_ORIGIN/api/v1/auth/login"
curl --fail-with-body -b patient.cookies "$STAGING_ORIGIN/api/v1/patient/me"
curl --fail-with-body -b patient.cookies "$STAGING_ORIGIN/api/v1/patient/reports?page_size=20"
curl --fail-with-body -b patient.cookies "$STAGING_ORIGIN/api/v1/patient/reports/201"
curl --fail-with-body -b patient.cookies \
  "$STAGING_ORIGIN/api/v1/patient/reports/201/pdf" -o synthetic-report.pdf
curl --fail-with-body -b patient.cookies "$STAGING_ORIGIN/api/v1/patient/access-history"
```

Report 201 must belong to the activated synthetic patient and be RELEASED. A
second patient's report ID must produce neutral 404 for detail and PDF even if
manually substituted. Destroy local synthetic credential files/cookies after the
staging exercise. Existing public QR verification does not require these cookies.

## Validation and remaining limitations

Final full-suite result: **989 passed, 0 failed, 0 skipped**, with two existing
Starlette/httpx/AnyIO deprecation warnings, in 846.29 seconds. The command was
`python -m pytest -vv -ra --tb=long`. Bidirectional cross-patient detail/PDF
substitution tests and all eight native MySQL scenarios passed. `pip check`
passed; Alembic has one head, `20260916_01`. No production migration or restart
was executed during development.

The complete suite is run with `python -m pytest -vv -ra --tb=long`. New tests
cover schema constraints, upgrade/downgrade preservation, frozen prior migration,
permission/CSRF boundaries, token hashing/rotation/expiry/reuse, role restrictions,
Argon2id, failure rollback, profile/output allowlists, list filters and ordering,
bidirectional cross-patient detail/PDF denial, integrity failure auditing, history
privacy, actual report supersession and staff historical access.

Eight isolated native MySQL scenarios execute the real migration chain and test
issuance/redeeming races, competing usernames, stale tokens, rollback, revoked
report state and changed account links. Their disposable servers use `/tmp`
data directories and Unix sockets with networking disabled; they do not use the
production application database.

MFA remains pending for Phase 6B. There is no automated identity proofing,
credential recovery, activation delivery or production rate limiter in this
phase. Legal/contact identity changes remain staff-managed. Phase 5B artifact
storage/hash limitations and clinical-result immutability remain unchanged.
