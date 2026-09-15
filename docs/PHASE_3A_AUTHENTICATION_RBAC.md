# Phase 3A — browser authentication and RBAC

## Repository audit and scope

The initial working tree contained an unfinished authentication implementation.
Its baseline was **134 passed, 4 failed**. The repository had 46 Phase 2A–2D
models, four migrations and one head, `20260914_04`. Existing health/readiness,
landing page and static routes were already present.

The incomplete work lacked the session migration and documentation; its SQLite
HTTP tests used separate in-memory connections. The administrator bootstrap
committed roles separately and failed on existing role codes. Other findings
included optional CSRF enforcement on future routes, unbounded username/user-agent
values, direct trust of forwarded IP headers, password-bearing validation errors,
and missing protection against caching authentication responses.

Phase 3A repairs those issues and adds exactly one infrastructure table.
All 46 normalized tables and all four deployed migration files remain unchanged.
Repository inspection establishes the migration chain; it does not establish the
revision currently applied to the production database. No production migration,
administrator creation, service restart or configuration change was performed.
The old deployment documents describe earlier phases and are historical; use the
Phase 3A procedure below for this release.

## Architecture and HTTP contract

FastAPI remains a modular monolith. MySQL is authoritative for accounts,
sessions, roles and permissions. Password verification and database work run in
synchronous endpoints/dependencies through FastAPI's worker threads.

| Method and route | Result |
| --- | --- |
| `POST /api/v1/auth/login` | Validate credentials, create session, set cookies, return safe account fields |
| `POST /api/v1/auth/logout` | Require session and CSRF, revoke session, clear both cookies, return `{"status":"ok"}` |
| `GET /api/v1/auth/me` | Return safe account, active roles, assigned permissions and linked identity summaries |

Login accepts JSON `{"username":"...","password":"..."}`. Username whitespace is
trimmed before enforcing 1–60 characters; passwords are never trimmed and accept
1–1024 characters at login. Unknown fields are rejected. Invalid bodies produce
422 with a generic response, excluding the submitted input. Cross-origin browser
login attempts produce 403; the Origin header, when present, must match the
request origin. `Sec-Fetch-Site: cross-site` is rejected. JSON clients without
these browser headers can log in. There is no cross-origin CORS configuration.

Invalid credentials, unknown users, INACTIVE accounts and LOCKED accounts all
return 401 with `Invalid username or password.` Unknown users still incur an
Argon2 verification using a random process-local dummy hash. This reduces the
obvious timing difference; it is not a guarantee of indistinguishable timing.
Malformed input rejected before credential evaluation is not a LOGIN_LOG attempt.

Successful login JSON contains only `user_id`, `username`, `account_status`,
`roles`. `/me` also contains `permissions`, `staff`, `patient`. Identity summaries
use explicit response models: IDs, codes and names; staff also includes
`position_title`. Unlinked identities are null. Email, contacts, birth dates,
clinical information, password fields and internal hashes are excluded.

Authentication responses, including handled failures, use `Cache-Control: no-store`.
OpenAPI retains Authentication tags, a password input format and a cookie security
scheme. Swagger's cookie handling does not replace a same-origin browser client;
unsafe authenticated requests must also send the CSRF header.

## Password security

Passwords use `argon2-cffi==25.1.0`, an equivalent maintained Argon2id implementation
to the suggested pwdlib solution. Parameters are Argon2id, 64 MiB memory, three
iterations, four lanes, a random 16-byte salt and a 32-byte hash. The encoded hash
is stored only in `USER_ACCOUNT.password_hash`. Successfully verified hashes with
outdated parameters are rehashed inside the login transaction.

The implementation uses the library's documented high-level API and verification
exceptions: [argon2-cffi API reference](https://argon2-cffi.readthedocs.io/en/stable/api.html).
No default password or administrator is seeded. `httpx==0.28.1` is added for tests.
Existing framework/database dependency pins are preserved.

## Opaque server-side sessions

Each login generates independent session and CSRF secrets with
`secrets.token_urlsafe(32)` (256 random bits each). The browser receives plaintext
secrets only as cookies. MySQL stores only SHA-256 hex digests of these random
secrets. SHA-256 is used for token lookup, never password hashing. Tokens are
never returned in JSON, put in localStorage, or recorded in audit events.

| `auth_session` column | Type and constraints |
| --- | --- |
| `session_id` | BIGINT, primary key, auto increment, not null |
| `user_id` | BIGINT, not null, indexed FK → `user_account.user_id` |
| `token_hash` | CHAR(64), not null, unique |
| `csrf_token_hash` | CHAR(64), not null |
| `created_at` | DATETIME, not null |
| `expires_at` | DATETIME, not null, indexed |
| `revoked_at` | DATETIME, nullable, indexed |
| `ip_address` | VARCHAR(45), nullable |
| `user_agent` | VARCHAR(255), nullable |

The table uses InnoDB and utf8mb4 with no delete cascades. User-agent values are
limited to 255 characters. IP addresses come from the validated ASGI client
address. Uvicorn handles forwarding only from its configured trusted proxy peers;
the application does not independently trust X-Forwarded-For. Accurate audit IPs
require the existing trusted-proxy configuration to be correct.

All application-generated authentication times are naive UTC values for MySQL
DATETIME. Expiration is absolute (default eight hours), checked on every request:
`expires_at > now` and `revoked_at IS NULL`. Cookie Max-Age matches the configured
TTL but is not trusted for server-side validity. Account status is checked on each
request too, so INACTIVE/LOCKED accounts cannot continue using existing sessions.
Permission and account changes become visible on the next request; an operation
already in progress may finish using the state read for that request.

Successful re-login revokes the current browser's previous session and generates
new secrets. Failed re-login leaves its existing valid session untouched. Logout
revokes only the current session. Other devices retain their own sessions.

## Cookies and CSRF

**Authentication cookies require HTTPS in production.** Do not disable Secure
cookies in production; configuration validation rejects that setting when
`ENVIRONMENT=production`.

Both cookies are host-only (no Domain), have `Path=/`, `Secure`, and default
`SameSite=Strict`. The session cookie is HttpOnly. The CSRF cookie is intentionally
readable by frontend JavaScript. On unsafe requests the future frontend must read
`rhu_csrf` and send its value as `X-CSRF-Token`. The header's SHA-256 hash must match
the current session's stored CSRF hash via `hmac.compare_digest`.

`get_current_session` performs this check automatically for all methods except
GET, HEAD and OPTIONS. Consequently `get_current_user`, `require_role` and
`require_permission` inherit it, preventing future protected routes from forgetting
CSRF validation. Missing/invalid CSRF returns 403; invalid authentication returns
401 first. Logout clears both cookies using the same path and security attributes.

The CSRF cookie delivers the secret to JavaScript; the server validates the header
against the database, not against an untrusted cookie value. `/me` requires neither
a CSRF header nor a CSRF cookie.

## Transactions and security logs

A successful login commits the new session, previous-session revocation (if any),
`last_login_at`, optional password rehash, SUCCESS LOGIN_LOG and AUTH_LOGIN AUDIT_LOG
in one transaction. Cookies are issued only after that commit succeeds. A denied
credential attempt commits its FAILED LOGIN_LOG before returning 401. Unknown
usernames have a null user_id. Successful and denied known-account attempts have
the account ID. No lockout counters are introduced.

Logout commits revocation and AUTH_LOGOUT together. Database errors roll back
pending changes and return generic 503 responses. SQLAlchemy parameter rendering
is disabled, and the authentication boundary never returns raw database errors.

LOGIN_LOG history is retained. `logout_time` is not populated because the schema
has no reliable session-to-login-log relationship. AUTH_LOGOUT identifies the
session by its numeric ID. Audit events contain no passwords, hashes, tokens,
cookie values or complete request bodies. No request-body logger is introduced.
External logging/monitoring integrations must preserve this policy.

## Reusable RBAC

Roles are queried through USER_ROLE → ROLE, restricted to active roles.
Permissions follow USER_ROLE → ROLE → ROLE_PERMISSION → PERMISSION. The database
is queried afresh each request; roles and permissions are not embedded in tokens
or persisted as session authorization snapshots. Returned codes are sorted and
permissions are deduplicated.

```python
from fastapi import Depends
from app.dependencies.auth import get_current_user, require_role, require_permission

# Examples for future routes; no domain endpoints are introduced in this phase.
# user = Depends(get_current_user)
# user = Depends(require_role("LAB_STAFF", "LAB_SUPERVISOR"))
# user = Depends(require_permission("FUTURE_PERMISSION_CODE"))
```

Multiple arguments mean **any** matching code is sufficient. Empty argument lists
are configuration errors. Authenticated users without access receive 403.

An **active SYSTEM_ADMIN role bypasses application permission checks**. It does
not bypass explicit role checks, session validity, ACTIVE account status or CSRF.
`/me.permissions` lists only assigned permission codes; it does not manufacture
wildcards or enumerate every potential administrator permission. There is no
`is_superuser` column. Future domain modules must additionally enforce record
ownership, patient boundaries and workflow rules where appropriate.

## Administrator and core-role bootstrap

Run on the VPS in a secure interactive terminal:

```bash
cd /opt/rhu-labchain
.venv/bin/python -m app.cli.bootstrap_admin
# Or supply only the username:
.venv/bin/python -m app.cli.bootstrap_admin --username first-admin
```

The command requests and confirms a hidden password of 12–1024 characters, refuses
getpass's echoing fallback, refuses duplicate usernames and creates an ACTIVE
account. Missing core roles, account, SYSTEM_ADMIN assignment and
AUTH_BOOTSTRAP_ADMIN event commit together. Failure rolls everything back.
Existing usernames are never overwritten. An inactive existing SYSTEM_ADMIN role
causes an explicit refusal rather than silently reactivating it. The initial
administrator may have no staff link.

There is no password CLI flag, password environment variable or default password.
For controlled Python callers, `create_admin(db, username, password)` accepts a
fresh SQLAlchemy Session and owns its transaction.

To ensure only the five core roles, without assigning users:

```bash
.venv/bin/python -m app.cli.bootstrap_roles
```

`ensure_core_roles(db)` is the shared idempotent service. It flushes but does not
commit, allowing the caller to own the transaction. It adds missing SYSTEM_ADMIN,
LAB_STAFF, LAB_SUPERVISOR, DOCTOR and PATIENT codes, preserving existing names,
descriptions and active flags. Concurrent bootstraps may encounter uniqueness
conflicts; run one bootstrap at a time or retry the failed command.

## Environment settings

No production `.env` changes are required if defaults are accepted. The following
optional values are documented in `.env.example`; do not replace the private file
with that example or overwrite existing database credentials.

```dotenv
AUTH_SESSION_TTL_MINUTES=480
AUTH_SESSION_COOKIE_NAME=rhu_session
AUTH_CSRF_COOKIE_NAME=rhu_csrf
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=strict
```

TTL accepts 1–525600 minutes. Cookie names must be different and contain 1–64
letters, digits, underscores or hyphens. SameSite accepts strict or lax; retain
strict for this same-origin application. `none` is not supported. Cookie names
are read when the application starts, so changing them requires a restart and
forces browsers to log in with the new names. Existing sessions retain their
original expiry if the TTL setting later changes.

## Migration and Hostinger deployment

New revision: `20260915_01`. Parent: `20260914_04`. Upgrade creates only
auth_session; downgrade drops only auth_session and loses all stored sessions.
No administrator or role data is seeded by the migration. Application startup
does not create tables or run migrations automatically.

The commands below are for the operator after the reviewed Phase 3A source files
are present in `/opt/rhu-labchain`. They reuse the existing virtual environment,
service, loopback port and HTTPS configuration. Run in Bash and stop on any failed
check. They were documented, not executed against production during development.

### 1. Dependencies and isolated checks

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/alembic heads
.venv/bin/alembic current
```

Expect repository head `20260915_01`. Before the first upgrade, the applied
database revision must be `20260914_04`; if it differs, investigate before
continuing. `alembic current` is read-only but uses the production connection.
The automated suite uses synthetic configuration and denies network connections.

### 2. Back up the database outside the public directory

Assumes the existing sudo/root MySQL maintenance access works. This uses MySQL
socket authentication without putting credentials in shell history. Use your
established private backup process if maintenance authentication differs.

```bash
umask 077
mkdir -p "$HOME/labchain-backups"
phase3a_backup="$HOME/labchain-backups/rhu_labchain-before-phase3a-$(date -u +%Y%m%dT%H%M%SZ).sql"
sudo mysqldump --single-transaction --no-tablespaces rhu_labchain > "$phase3a_backup"
test -s "$phase3a_backup"
```

Retain a known restorable backup and the previous application release. MySQL DDL
is not transactionally rolled back like application writes; a failed migration
needs inspection rather than a blind retry or manual Alembic stamp.

### 3. Upgrade, bootstrap and restart

```bash
cd /opt/rhu-labchain
.venv/bin/alembic upgrade 20260915_01
.venv/bin/alembic current
.venv/bin/alembic heads
.venv/bin/alembic check
.venv/bin/python -m app.cli.bootstrap_admin
sudo systemctl restart rhu-labchain-node1
systemctl is-active rhu-labchain-node1
curl --fail --silent --show-error https://labchain.online/api/v1/health
curl --fail --silent --show-error https://labchain.online/api/v1/ready
```

Both revision commands should report `20260915_01`; `alembic check` should report
no new upgrade operations. Skip bootstrap if an administrator has already been
created; the command intentionally refuses reuse of an existing username.
The service restart does not edit its systemd unit. Nginx, certificates, firewall,
ports, domain and private environment settings require no Phase 3A edits.

Confirm login, `/me` and CSRF-protected logout over HTTPS using the API; no frontend
login page is delivered. Avoid commands that print Set-Cookie headers or place
passwords in shell arguments. `curl /ready` proves connectivity, while the Alembic
checks establish schema state.

### Rollback

Coordinate rollback with application code: the Phase 3A application cannot run
its authentication endpoints after auth_session is dropped. Stop the existing
service before a planned schema rollback:

```bash
cd /opt/rhu-labchain
sudo systemctl stop rhu-labchain-node1
.venv/bin/alembic downgrade 20260914_04
.venv/bin/alembic current
```

Then restore the saved Phase 2D application release through your normal release
process and start the existing service:

```bash
sudo systemctl start rhu-labchain-node1
curl --fail --silent --show-error https://labchain.online/api/v1/health
curl --fail --silent --show-error https://labchain.online/api/v1/ready
```

Downgrade invalidates all sessions. It retains USER_ACCOUNT, role assignments,
LOGIN_LOG and AUDIT_LOG, including records created in Phase 3A. Do not downgrade
below Phase 2D or delete administrator/history records as part of this rollback.

## Validation and remaining limitations

Final local validation on 2026-09-15: **197 passed, 2 warnings** in the complete
`python -m pytest -q` suite. `pip check` reports no broken requirements.
`alembic heads` reports exactly `20260915_01 (head)`. `git diff --check` passes.


The complete suite covers password hashing; secure HTTPS cookies; input and error
redaction; successful/failed login logs; session expiry, revocation and rotation;
CSRF through session/user/role/permission dependencies; safe linked identities;
live authorization changes; administrator override; transactional bootstrap and
role idempotency; and injected write failures to verify rollback.

Migration tests verify one head, offline MySQL DDL, model/migration agreement,
foreign keys, uniqueness, no cascades, upgrade/downgrade preservation and byte-for-
byte unchanged Phase 2A–2D migration history. Previous workbook/schema and health
regressions remain in the complete suite.

HTTP tests use synthetic SQLite tables copied from model metadata, substituting
INTEGER only for generated primary keys in the copied schema. Migration tests use
the actual migrations and explicit BIGINT fixture IDs. No test accesses production.
MySQL DDL is compiled offline; execution against an isolated MySQL 8 instance and
an actual deployed HTTPS browser smoke test remain release validation tasks.

Known limitations/future work:

- No rate limiting, automatic lockout, MFA, password reset or email verification.
  Argon2 work consumes memory/CPU; deployment needs appropriately sized resources
  and future request throttling.
- No idle timeout, device listing, revoke-all workflow or expired-session cleanup
  job. Expired/revoked rows are retained; plan retention and cleanup separately.
- CSRF/HttpOnly do not remove the need to prevent XSS in future frontend code.
- Host-only cookies and strict SameSite assume a same-origin frontend. A future
  cross-origin client needs an explicit security design.
- Username case/accent matching follows the existing MySQL collation; this phase
  does not change it. SQLite tests do not reproduce every MySQL collation rule.
- Proxy trust, UTC clock synchronization and external log redaction remain
  deployment responsibilities. IP/user-agent fields are context, not identity.
- The current TestClient stack emits two upstream deprecation warnings involving
  httpx and AnyIO. They do not fail the tests; dependency migration is separate work.

No patient/staff management, clinical APIs, reports, blockchain processes or
frontend dashboard/login page are introduced by this phase.

## File inventory relative to the Phase 2D commit

Some of these new files were already present as unfinished local work at the
start of the audit; they were reviewed and corrected in place.

New files:

- `app/api/auth.py`
- `app/cli/__init__.py`
- `app/cli/bootstrap_admin.py`
- `app/cli/bootstrap_roles.py`
- `app/dependencies/auth.py`
- `app/models/auth_session.py`
- `app/schemas/auth.py`
- `app/security/passwords.py`
- `app/security/tokens.py`
- `app/services/auth_service.py`
- `app/services/rbac_service.py`
- `migrations/versions/20260915_01_phase_3a_auth_session.py`
- `tests/test_phase_3a_authentication_rbac.py`
- `tests/test_phase_3a_migration.py`
- `docs/PHASE_3A_AUTHENTICATION_RBAC.md`

Modified files:

- `.env.example`
- `app/config.py`
- `app/database.py`
- `app/main.py`
- `app/models/__init__.py`
- `requirements.txt`
- `tests/conftest.py`
- `tests/test_phase_2a_migration.py`
- `tests/test_phase_2d_migration.py`
- `tests/test_phase_2d_models.py`

Earlier-phase test changes distinguish phase-specific scope from the current
repository head and additional routes. Exact current table scope and unchanged
migration history are separately asserted; previous domain checks are retained.
