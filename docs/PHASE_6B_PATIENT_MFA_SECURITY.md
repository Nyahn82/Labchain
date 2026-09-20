# Phase 6B — patient MFA and account security

Phase 6B adds TOTP, recovery codes, MFA login challenges, session assurance and
password changes to the existing authentication system. Patient ownership checks
remain mandatory after MFA. There is no frontend, QR image enrollment UI,
SMS/email OTP, forgotten-password email recovery, OAuth, blockchain runtime,
patient profile editing or staff-wide mandatory MFA in this phase.

## Migration and implementation inventory

The actual repository head inspected before development was `20260916_01`. The
single new migration is `20260920_01_phase_6b_patient_mfa.py`, revision
`20260920_01`, down_revision `20260916_01`. All six earlier migrations are unchanged.

| Table | Change |
| --- | --- |
| user_totp_mfa | BIGINT mfa_id PK; unique user_id FK; TEXT secret_ciphertext; binary secret_nonce; created_at, confirmed_at, enabled_at, disabled_at; nullable BIGINT last_used_counter |
| mfa_recovery_code | BIGINT recovery_code_id PK; indexed mfa_id FK; unique CHAR(64) code_hash; created_at, used_at, revoked_at |
| mfa_challenge | BIGINT challenge_id PK; indexed user_id FK; unique CHAR(64) token_hash; created_at; indexed expires_at; used_at; revoked_at; INT attempt_count; optional IP VARCHAR(45) and user-agent VARCHAR(255) |
| auth_session | Add nullable DATETIME mfa_verified_at; existing sessions start without MFA assurance |

Tables use existing InnoDB/utf8mb4 conventions and no cascading deletes. Code and
challenge history is retained. Downgrade destroys MFA state and is not a routine
production rollback procedure; coordinate application/database rollback and
session invalidation if rollback is required.

New files (13):

* `app/api/mfa.py`
* `app/api/security_cookies.py`
* `app/cli/generate_mfa_key.py`
* `app/models/mfa.py`
* `app/schemas/mfa.py`
* `app/security/mfa_crypto.py`
* `app/services/mfa_service.py`
* `migrations/versions/20260920_01_phase_6b_patient_mfa.py`
* `tests/mysql_phase6b_probe.py`
* `tests/test_phase_6b_mfa.py`
* `tests/test_phase_6b_migration.py`
* `tests/test_phase_6b_mysql.py`
* `docs/PHASE_6B_PATIENT_MFA_SECURITY.md`

Modified files (19):

* `.env.example`
* `requirements.txt`
* `app/config.py`
* `app/main.py`
* `app/api/auth.py`
* `app/api/patient_portal.py`
* `app/dependencies/auth.py`
* `app/dependencies/patient.py`
* `app/models/__init__.py`
* `app/models/auth_session.py`
* `app/services/auth_service.py`
* `app/services/administration_service.py`
* `app/services/permission_catalog.py`
* `tests/conftest.py`
* `tests/test_phase_2a_migration.py`
* `tests/test_phase_3a_migration.py`
* `tests/test_phase_3b_identity_admin.py`
* `tests/test_phase_6a_migration.py`
* `tests/test_phase_6a_patient_portal.py`

Dependencies added: `pyotp==2.10.0`, `cryptography==50.0.1`. PyOTP performs TOTP
cryptography and provisioning URI generation; cryptography provides AESGCM.
References: [PyOTP documentation](https://pyauth.github.io/pyotp/) and
[cryptography authenticated encryption documentation](https://cryptography.io/en/latest/hazmat/primitives/aead/).

## Configuration and encryption key

| Environment setting | Default / constraint |
| --- | --- |
| MFA_SECRET_ENCRYPTION_KEY | Required; canonical padded URL-safe base64 of exactly 32 random bytes |
| MFA_TOTP_ISSUER | RHU LabChain; 1–100 characters |
| MFA_CHALLENGE_TTL_MINUTES | 5; range 1–15 |
| MFA_MAX_CHALLENGE_ATTEMPTS | 5; range 1–10 |
| MFA_TOTP_VALID_WINDOW | 1; permitted values 0 or 1 |
| MFA_RECOVERY_CODE_COUNT | 8; range 1–20 |
| MFA_CHALLENGE_COOKIE_NAME | rhu_mfa_challenge; distinct from session and CSRF cookie names |
| PATIENT_MFA_REQUIRED | true |

The key is 44 ASCII characters including its final `=` padding. Missing,
noncanonical or malformed keys fail Settings validation/startup. Keys are never
truncated, padded or hashed into substitutes; there is no fallback key or
derivation from database credentials, passwords or patient information.
`.env.example` deliberately contains a blank key, not a deployable secret.

`python -m app.cli.generate_mfa_key` prints one securely generated key in the exact
required format. It does not load application settings, connect to the database,
write files or install the key. Run it in a private administrator terminal. Do not
generate a new key on every deployment. All application nodes sharing the MFA
database must use the same key.

Each enrollment uses a fresh random 12-byte nonce. AES-256-GCM encrypts the PyOTP
secret with associated data `rhu:totp:v1:<user_id>`, binding the envelope to its
account. Base64 ciphertext includes the authentication tag; the nonce is stored
as binary. Secrets are decrypted only during MFA operations. Decryption or
integrity failure produces a generic error and MFA_SECRET_UNAVAILABLE audit,
never a silently replaced secret or an exposed ciphertext.

**Back up the MFA encryption key securely**, separately from ordinary database
backups, in an access-controlled secrets backup. Losing it prevents TOTP secret
decryption. Existing recovery codes can still support recovery-code login and
disable; controlled administrator reset is also available. Compromise requires
reset/re-enrollment or a future key-rotation procedure. Automatic key rotation is
outside Phase 6B. Do not put the plaintext key in database backups, source control,
audit metadata, tickets or shared logs.

## Enrollment and limited patient sessions

A newly activated patient uses the existing POST `/api/v1/auth/login`. Without
enabled/confirmed MFA, valid password login issues an opaque session with
`mfa_verified_at = NULL`. With PATIENT_MFA_REQUIRED=true, this session permits only:

* GET `/api/v1/auth/me` — account/role basics, with no patient/staff identity or permissions
* POST `/api/v1/auth/logout`
* GET `/api/v1/patient/security`
* POST `/api/v1/patient/mfa/totp/enroll`
* POST `/api/v1/patient/mfa/totp/confirm`

Other authenticated routes are denied, including administrative routes for a
patient with additional roles. Clinical access returns 403 MFA_ENROLLMENT_REQUIRED;
enabled MFA without session assurance returns MFA_REQUIRED. Password change is
not available from a limited enrollment session. Existing public health and opaque
report-verification routes retain their public behavior.

Security routes require the active PATIENT role and a valid account link. They
never accept a caller-selected user_id. Unsafe routes require the existing CSRF
header. Staff cannot use patient enrollment routes.

Enrollment generates a PyOTP base32 secret and persists only its encrypted
envelope. It returns secret and provisioning_uri once with Cache-Control: no-store.
The URI uses the configured issuer and username, never medical name, patient code,
diagnosis or laboratory data. There is no retrieval endpoint. Re-enrolling a
pending or disabled configuration replaces the secret; enabled MFA must first be
disabled/reset. Replacement revokes remaining codes and challenges and rolls back
if its audit cannot be written.

Confirmation verifies TOTP, sets confirmed_at/enabled_at, clears disabled_at,
records the accepted counter and marks the current session MFA-verified. It revokes
other sessions and outstanding challenges, creates recovery codes and returns
them once. Repeated confirmation cannot retrieve the codes again.

## Login challenge and replay prevention

For any account with enabled TOTP, valid password login returns HTTP 202:

```json
{"mfa_required":true,"methods":["TOTP","RECOVERY_CODE"]}
```

No normal session is created yet. The current browser's previous session is
revoked and its cookies cleared. A random 256-bit opaque challenge is stored only
as SHA-256 with expiration, attempt count, IP and truncated user-agent. A new
challenge revokes that user's other outstanding challenges.

The plaintext challenge is placed only in a short-lived cookie, never in JSON:
`rhu_mfa_challenge`, HttpOnly, Secure, SameSite=Strict, Path=/, Max-Age matching TTL.
It is always Secure, including development; use HTTPS for browser testing.

POST `/api/v1/auth/mfa/verify` accepts `{"code":"123456"}`. POST
`/api/v1/auth/mfa/recovery` accepts `{"recovery_code":"..."}`. Both use the temporary
cookie before a normal session exists, so normal session CSRF is not applicable.
Both reject cross-origin browser requests using the existing login origin and
Sec-Fetch-Site checks, alongside the Strict cookie and JSON input boundary.

Verification requires a live unused/non-revoked challenge under its attempt limit,
an ACTIVE account and enabled/confirmed MFA. Failed credential checks increment
attempt_count and write a safe failure audit in one transaction. Exhaustion revokes
the challenge and clears its cookie, never permanently locking the account.
Missing, expired, used, revoked and exhausted challenges fail generically and clear
the cookie. Malformed bodies fail generic validation before credential checking.

Success consumes the challenge and creates a normal session with server-set
mfa_verified_at, sets the existing session/CSRF cookies and clears the challenge
cookie. There is no JWT, localStorage token or second password-authentication flow.

PyOTP generates six-digit, 30-second values from server UTC. Window 1 permits
adjacent counters. The service identifies the matching counter using PyOTP and
rejects counters <= last_used_counter. Counter updates are protected by row locks.
Confirmation consumes its counter too: immediately reusing that code for login or
a security change fails. After accepting a future-window counter, wait for a later
counter before another use. Client-supplied time or assurance flags are not accepted.

## Recovery and security changes

Recovery codes contain 128 random bits, displayed as four groups of eight lowercase
hexadecimal characters. Only surrounding whitespace and hyphens are ignored; case
and other characters remain significant. SHA-256 covers the complete canonical
code. Only its unique hash is stored. Each code belongs to one MFA configuration
and is single-use. There is no retrieval endpoint.

Regeneration requires an MFA-verified session, CSRF, current password and fresh
TOTP. It revokes unused old codes, creates a new set, revokes other sessions and
pending challenges, and returns new codes once. The current verified session stays
valid. These assurance requirements also apply when PATIENT_MFA_REQUIRED=false.

Disable requires an MFA-verified session, CSRF, current password, and exactly one
fresh TOTP or unused recovery code. It disables the configuration, revokes unused
codes, all sessions including current, and outstanding challenges, then clears
cookies. A fresh password login must enroll again when patient MFA is required.

Administrator reset requires ACCOUNT_MFA_RESET, with SYSTEM_ADMIN's existing
permission bypass. Authority is checked again inside the transaction. Reset
disables MFA and revokes all unused codes, outstanding challenges and sessions for
the target; no enabled MFA returns controlled 409. It never reveals/generates a
secret or changes the password. RHU must use its controlled identity-verification
process before reset. Permission bootstrap adds the permission idempotently but
does not grant it automatically to other roles.

Password change requires a normal authenticated session, CSRF and current password.
The new password follows the existing 12–1024-character policy and must differ
from the current password. Argon2id hashes it; all sessions and challenges are
revoked, cookies cleared and fresh login required. MFA remains configured.
Existing administrative account locking/inactivation also revokes MFA challenges.

## Routes and patient ownership

All paths below have prefix `/api/v1`, explicit input/output schemas and no-store
responses. Credential inputs are redacted in representations and validation errors.

| Method and path | Requirement / result |
| --- | --- |
| POST `/auth/login` (changed) | Password; HTTP 202 + challenge for enabled MFA, otherwise password session |
| GET `/auth/me` (changed) | Limited patient sessions receive authentication basics only |
| POST `/auth/mfa/verify` | Challenge cookie + TOTP; normal session on success |
| POST `/auth/mfa/recovery` | Challenge cookie + recovery code; normal session on success |
| GET `/patient/security` | PATIENT password session + account link; safe flags/count |
| POST `/patient/mfa/totp/enroll` | PATIENT session + link + CSRF; one-time secret/URI |
| POST `/patient/mfa/totp/confirm` | PATIENT session + link + CSRF + pending TOTP; one-time recovery set |
| POST `/patient/mfa/recovery-codes/regenerate` | Verified PATIENT session + CSRF + password + fresh TOTP |
| POST `/patient/mfa/disable` | Verified PATIENT session + CSRF + password + fresh second factor |
| POST `/users/{user_id}/mfa/reset` | ACCOUNT_MFA_RESET or SYSTEM_ADMIN + CSRF |
| POST `/auth/change-password` | Normal session + CSRF + current/new password |

GET `/patient/me`, `/patient/reports`, `/patient/reports/{report_id}`,
`/patient/reports/{report_id}/pdf` and `/patient/access-history` additionally use
require_patient_mfa. Phase 6A account-link ownership checks, neutral 404 responses,
released-report restrictions and PDF integrity verification remain intact. MFA
never authorizes another patient's report. Policy-off retains Phase 6A clinical
access behavior, but login still challenges accounts that have enabled MFA.

## Transactions, audit and login semantics

MFA operations serialize on the user account row and use current locking reads of
configuration, challenge, recovery and session state. This also serializes against
password changes and administrative revocation. Session-backed security mutations
recheck the current account/session under locks. Admin reset follows existing
administration lock ordering and rechecks authority. Deadlock victims retry only
rolled-back operations through the existing bounded retry helper.

One challenge cannot create two sessions; one recovery code cannot succeed twice,
even against different challenges; one accepted TOTP step cannot authenticate
twice. Credential consumption, assurance, session changes and success audits commit
atomically. Audit/database failure returns no successful credential response.
Failed challenge attempts and secret-unavailable audits commit before their
controlled error responses.

LOGIN_LOG SUCCESS represents completed login: password-only login for non-MFA
accounts (including limited patient enrollment sessions), or successful second
factor for MFA-enabled accounts. Password success awaiting MFA creates no SUCCESS
entry; MFA completion creates exactly one. Failed passwords remain FAILED. MFA
failures use AUDIT_LOG instead of misleading password-login failures.

Audit actions: PATIENT_MFA_ENROLL_START, PATIENT_MFA_ENABLED, MFA_CHALLENGE_SUCCESS,
MFA_CHALLENGE_FAILED, MFA_RECOVERY_CODE_USED,
PATIENT_MFA_RECOVERY_CODES_REGENERATED, PATIENT_MFA_DISABLED, ACCOUNT_MFA_RESET,
PASSWORD_CHANGE and MFA_SECRET_UNAVAILABLE. Events contain actor/account reference,
time and existing internal IP metadata, without secret old_value/new_value payloads.
No secret/ciphertext, encryption key, OTP, recovery code/hash, challenge value/hash,
password/hash or session/CSRF token is copied into audit values.

## Exact Hostinger deployment and key setup

These are operator steps, not actions executed by development. Deploy reviewed code
through the existing release process, keep database and secrets backups, and
coordinate migration/restart so code and schema agree. Do not alter Nginx, Certbot,
UFW, existing report files, ports or systemd units.

Run as the application owner `rhuadmin`, stopping on any error:

```bash
cd /opt/rhu-labchain
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

For the first MFA deployment only, in a private administrator terminal:

```bash
python -m app.cli.generate_mfa_key
nano /opt/rhu-labchain/.env
```

Copy the generated value directly into `MFA_SECRET_ENCRYPTION_KEY=<generated-value>`
in the existing private `.env`, without typing the secret into shell command
history or committing it. Preserve every existing setting. Add
`PATIENT_MFA_REQUIRED=true`; other MFA settings can retain the defaults above.
Securely back up the key separately and configure the same value on all nodes.
Do not replace it on subsequent deployments. Settings now require the key, so
configure it before application/migration commands. Production `.env` was not
edited during development.

```bash
python -m pytest -vv -ra --tb=long
python -m alembic heads
python -m alembic current
```

Expected repository head: `20260920_01`; expected deployed predecessor:
`20260916_01`. Investigate any other current revision before upgrading. Tests use
synthetic settings/keys and isolated databases. After taking a database backup
through the existing backup process:

```bash
python -m alembic upgrade 20260920_01
python -m alembic current
python -m app.cli.bootstrap_roles
python -m app.cli.bootstrap_permissions
sudo systemctl restart rhu-labchain-node1.service
systemctl is-active rhu-labchain-node1.service
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/ready
curl --fail --silent --show-error https://labchain.online/api/v1/health
curl --silent --show-error -i https://labchain.online/api/v1/patient/security
```

The last request must return 401 without authentication. Grant ACCOUNT_MFA_RESET
only to designated staff through the existing administration APIs. Use synthetic
patients to verify enrollment, full MFA login, replay rejection and cross-patient
denial. Migrated sessions have NULL assurance and must enroll or log in with MFA
before reports. No enrollment frontend is included; coordinate client/operational
readiness before patient rollout.

Per-challenge attempts are not an account-wide or IP-wide rate limiter. Production
edge/application abuse controls remain required for login, activation, enrollment,
confirmation and security operations. Repeated password logins can obtain new
challenges. No large limiter dependency or Nginx change is introduced. Maintain
synchronized server time and prevent credential request-body logging.

## Synthetic curl examples

Use staging, HTTPS, synthetic accounts and private credential files outside the
repository. Never put real passwords/codes into shared shell history.

```bash
umask 077
STAGING_ORIGIN=https://staging.example.test
```

Prepare `login.json` with synthetic username/password; `confirm.json` or `totp.json`
with `{"code":"123456"}` using a current authenticator code; and `recovery.json`
with `{"recovery_code":"synthetic-code"}` when testing recovery.

```bash
curl --fail-with-body -c patient.cookies -H 'Content-Type: application/json' \
  --data-binary @login.json "$STAGING_ORIGIN/api/v1/auth/login"
curl --fail-with-body -b patient.cookies "$STAGING_ORIGIN/api/v1/patient/security"
PATIENT_CSRF=$(awk '$6 == "rhu_csrf" { print $7 }' patient.cookies)
curl --fail-with-body -b patient.cookies -H "X-CSRF-Token: $PATIENT_CSRF" \
  -X POST "$STAGING_ORIGIN/api/v1/patient/mfa/totp/enroll" -o enrollment.json
curl --fail-with-body -b patient.cookies -H "X-CSRF-Token: $PATIENT_CSRF" \
  -H 'Content-Type: application/json' --data-binary @confirm.json \
  "$STAGING_ORIGIN/api/v1/patient/mfa/totp/confirm" -o recovery-codes.json
curl --fail-with-body -b patient.cookies "$STAGING_ORIGIN/api/v1/patient/reports"
```

Enrollment and recovery output files contain one-time credentials. Protect them;
provision the secret in a synthetic authenticator, delete the local enrollment
copy, and retain recovery codes only in approved secure storage. Later login:

```bash
curl --fail-with-body -b patient.cookies -c patient.cookies -H 'Content-Type: application/json' \
  --data-binary @login.json "$STAGING_ORIGIN/api/v1/auth/login"
curl --fail-with-body -b patient.cookies -c patient.cookies -H 'Content-Type: application/json' \
  --data-binary @totp.json "$STAGING_ORIGIN/api/v1/auth/mfa/verify"
```

Alternatively send recovery.json to `/auth/mfa/recovery` with the same cookie
arguments. Refresh PATIENT_CSRF from the newly issued cookies after MFA login.
Regeneration takes password/totp_code; disable takes password and exactly one of
totp_code/recovery_code; password change takes current_password/new_password.
Send JSON and CSRF to their routes. Admin reset uses an authorized staff cookie and
CSRF, with no secret body. Destroy local staging credential files after testing.

## Validation and remaining limitations

Full command: `python -m pytest -vv -ra --tb=long`.

**1,068 passed, 0 failed, 0 skipped**, with two existing Starlette/httpx/AnyIO
deprecation warnings, in **863.42 seconds (14 minutes 23 seconds)**. Temporary full
log: `/tmp/rhu-phase6b-full-20260920.log`. Dependency consistency also passed.

Coverage includes key validation/CLI/encryption, migration preservation,
enrollment, cookie/CSRF/origin boundaries, expiry/attempts, replay, recovery scoping,
regeneration, disable/reset, password change, audit rollback, session restrictions,
and real MFA followed by bidirectional cross-patient detail/PDF denial.

Five native MySQL scenarios run the full migration chain on a disposable Unix
socket with networking disabled: challenge reuse, recovery reuse, TOTP replay,
concurrent attempt exhaustion and stale revoked challenges. Historical Phase 6A
API tests explicitly use the supported policy-off setting; Phase 6B tests exercise
policy-on enrollment/assurance and unchanged account-linked ownership.

Production deployment, key generation/configuration, permission grants, rate-limit
setup and service restart were not performed. Full key rotation, account-wide
abuse throttling, delivery providers and forgotten-password recovery remain outside
this implementation. Phase 7 was not started.
