# Phase 8B-3: durable blockchain outbox delivery

This phase adds source, tests, and an uninstalled systemd unit. Delivery defaults
to disabled. Implementation and regression testing do not start the production
worker, consume production events, write to Fabric, or migrate the production DB.
Alembic remains at `20260924_01`; the Phase 8B-1 schema is sufficient.
The dedicated-account follow-up is also source-only: no production account,
external environment, service installation or runtime credential copy was made.

MySQL remains the clinical source of truth. Report release, revoke and supersede
transactions capture events atomically and never contact Fabric. Neither FastAPI
startup nor `/api/v1/ready` requires the Gateway or its identity files.

## Architecture and state

`app/cli/blockchain_worker.py` runs `DeliveryWorker` from
`app/services/blockchain_delivery_service.py`. The bridge in
`app/services/blockchain_adapter_service.py` invokes the existing Phase 8B-2 Node
adapter. `app/worker_config.py` reads process environment only and constructs its
own SQLAlchemy session factory. `app/blockchain_config.py` shares setting
definitions without constructing web settings. Immutable validation lives in
`app/services/blockchain_event_validation.py`, re-exported by the capture service
without changing canonicalization. Neither importing nor delivering an event in
the worker loads `app.config`, `app.database`, the web dotenv or MFA secrets.
No new HTTP routes, frontend status, public verification, historical
backfill, report rollback or chaincode changes are included.

| State | Meaning |
| --- | --- |
| PENDING | Committed clinical event awaiting delivery; may be delayed for a predecessor. |
| PROCESSING | A worker owns a time-limited UUIDv4 lease and is attempting delivery/reconciliation. |
| CONFIRMED | A VALID Fabric commit, or exact reconciliation against already committed matching ledger state. |
| FAILED | Retryable delivery failure; a future attempt is scheduled. This does **not** mean the clinical report failed. |
| DEAD | No automatic retry. Integrity, credentials/configuration, content conflict, dead predecessor or attempt exhaustion needs review. This does **not** reverse release, revocation or supersession in MySQL. |

## Claims, leases and fencing

Claims use short MySQL transactions at READ COMMITTED, selected only for the
worker connection and reset when it returns to the pool. Three ordered, indexed
queries prefer expired PROCESSING, then due FAILED, then due PENDING rows:

```sql
SELECT ... FROM blockchain_event FORCE INDEX (ix_blockchain_event_lease)
WHERE event_status = 'PROCESSING' AND lease_expires_at <= :now
ORDER BY lease_expires_at, event_id LIMIT 1 FOR UPDATE SKIP LOCKED;

-- Run for FAILED, then PENDING if no earlier candidate was found:
SELECT ... FROM blockchain_event FORCE INDEX (ix_blockchain_event_eligible)
WHERE event_status = :status AND next_attempt_at <= :now
ORDER BY next_attempt_at, event_id LIMIT 1 FOR UPDATE SKIP LOCKED;
```

A combined OR query with a filesort can lock multiple candidate rows before its
LIMIT in InnoDB. Separate queries use the existing indexes for both filtering and
ordering. Real concurrent tests verify independent claims while one worker's
transaction remains uncommitted. READ COMMITTED avoids unnecessary gap locks.

Under the selected row lock, immutable data and predecessor conditions are
validated. The worker generates a lowercase UUIDv4 lease token, increments
`attempt_count`, records processing/expiry/updated UTC timestamps, and commits.
Only after the connection is returned does it invoke the adapter. A batch claims
and completes **one event at a time**, so waiting batch members do not lose leases.
At most 32 blocked or corrupt candidates are handled per claim transaction.

An active lease cannot be reclaimed. Once its 120-second default expires, a new
worker can claim it with a different token. All post-Gateway updates include:

```sql
WHERE event_id = :event_id
  AND event_status = 'PROCESSING'
  AND lease_token = :owned_token
```

Zero matched rows means the worker lost ownership. Its success or failure cannot
overwrite the newer owner's state. A resumed old worker can still have caused a
remote commit; the current worker recovers it by ledger reconciliation.

Every invocation in one attempt shares a **90-second total budget**, not a fresh
90 seconds per subprocess. Invocation delayed after claim reduces that budget.
The lease must exceed the budget by at least 10 seconds. A submit reserves up to
15 seconds of the budget for a read after an uncertain outcome. If that budget
is exhausted, a later retry starts with ledger lookup. Node's own stage deadlines
remain bounded and the Python supervisor enforces the total budget. Scheduling
pauses can still outlast a lease; token fencing is the final database protection.

Graceful SIGTERM/SIGINT sets a stop flag: no further claims begin, the current
bounded attempt may finish, and the loop exits. No sleeping or remote work occurs
inside a claim/acknowledgement transaction. DB failures stop the process with a
fixed safe code; systemd can restart it. Unacknowledged claims recover on expiry.

## Integrity and lifecycle ordering

The worker reuses Phase 8B-1 `validate_event`: canonical JSON, schema, timestamp,
UUIDs, hashes and immutable columns must agree, including recomputed
`SHA256(canonical_payload) == record_hash`. Frozen source node/MSP must agree with
the worker identity and origin registry. Tampered events become DEAD with
`OUTBOX_INTEGRITY_FAILURE` before any Gateway call.

Delivery-only Core UPDATEs are explicitly restricted to the model's
`DELIVERY_FIELDS` allowlist. They bypass the ORM's immutable-payload validator
solely so corrupt rows can be quarantined without rewriting their evidence.
Immutable columns and all clinical tables remain untouched.

A release has no predecessor. Revocation/supersession must reference a release
for the same internal entity, public reference, source origin and previous hash.
They wait until that release is CONFIRMED. PENDING/PROCESSING/FAILED predecessors
cause a polling delay without incrementing the dependent attempt count; DEAD
predecessors cause `PREDECESSOR_DEAD`. Independent events can proceed while a
lifecycle event waits.

## Wire mapping and reconciliation

Only these six CreateAnchor arguments, plus the adapter action, cross stdin:

| Adapter field | Immutable source |
| --- | --- |
| anchorId | event_uuid |
| eventType | event_type |
| entityReference | entity_reference |
| contentHash | record_hash |
| previousHash | previous_hash or empty string |
| sourceNode | frozen canonical source_node |

No canonical payload, entity ID, deduplication key, actor/user ID, patient data,
report ID or PDF bytes leave through the worker request.

Each attempt first calls `anchor_exists`. If present, it reads rather than submits.
If absent, it submits through proposal, endorsement, submission and commit status.
An uncertain submit (including timeout, duplicate-anchor error or malformed
acknowledgement) is followed by a bounded read before failure is scheduled.

Reconciliation compares anchor ID, event type, entity type REPORT, entity
reference, content hash, previous hash, source node and MSP. It does **not** compare
ledger `created_at` with event `occurred_at`: proposal time differs from the
clinical occurrence time. An exact match confirms using the **original on-chain
transaction ID**. A semantic mismatch is permanent `ANCHOR_CONFLICT`, never a
rewrite. Duplicate-anchor errors alone are not evidence of a content conflict;
a matching read succeeds, and an unavailable read is retried within the limit.

Direct confirmation requires a strict successful adapter envelope, `confirmed`
true, integer validation code 0, a valid transaction ID matching the returned
anchor, and matching immutable semantics. Block number is a bounded uint64
decimal string converted to an integer, or NULL. Invalid commit receipts never
qualify as successful direct submissions.

For reconciliation, validation code **0 is inferred from committed world-state
existence**; its matching anchor was created by a valid committed transaction.
The block number remains NULL if unavailable. Both paths set confirmation time,
clear errors and leases, and perform a fenced update.

Submission is at least once: a crash can leave the remote result uncertain.
Deterministic event UUIDs, chaincode uniqueness and exact reconciliation provide
exactly-one anchor effect, not exactly-once network execution. Crashes before
submission, after commit/before MySQL acknowledgement, and stale-process returns
are covered by tests.

## Retries and terminal review

A finite allowlist validates both the adapter error code and its retryable flag.
Gateway unavailability, evaluation/endorsement failures, uncertain submission,
commit timeout and process timeout/failure are retryable. TLS certificate
validation, credentials, configuration, invalid input/response, invalid commit,
outbox integrity and semantic conflicts are permanent. Transport interruptions
classified by the adapter as unavailable/submission/commit failures can retry;
`TLS_FAILED` means validation failure and remains permanent. Invalid commit codes,
including MVCC failures, currently require review instead of automatic retry.

For attempt `n`, let `b = min(retry_max, retry_base * 2**min(max(n-1,0),30))`.
The delay is `min(retry_max, b + U[0,1] * min(0.1*b,5))` seconds. Default base is
15 seconds, cap 900 seconds, and maximum normal delivery attempts 8. Jitter and
clocks are injectable in tests. FAILED retries clear leases and set next-attempt
UTC time; no automatic retry follows DEAD.

`attempt_count` counts **claims**, including recovery claims. If a process crashes
on the final allowed delivery attempt, an expired lease may receive an additional
**read-only recovery claim**. It can confirm an existing matching anchor but can
never submit a ninth write. An absent anchor or unsuccessful recovery becomes
DEAD. Repeated process crashes during such recovery may increment the claim count
again, but never permit another submission. This preserves recovery of the last
allowed attempt without increasing the submission limit.

Stored errors are fixed allowlisted messages (at most 512 characters), never raw
exceptions or stderr. Worker logs contain event IDs/types, attempts, state changes,
safe error codes and confirmed transaction IDs. Corrupt rows log numeric event ID
only. No canonical payloads, PDF hashes, PHI, keys, certificate bodies, DB URLs,
environment dumps or gRPC metadata are logged. Subprocess stderr is bounded and
discarded. SQLAlchemy exceptions are caught without emitting SQL/parameters.

DEAD requires investigation of the fixed code, identity/configuration and ledger
state. Do not change immutable fields, delete a conflicting ledger anchor, roll
back clinical state, or blindly requeue exhausted work. There is deliberately no
automatic DEAD requeue or historical backfill command in this phase.

## Configuration

The tracked worker template is `deploy/blockchain-worker.env.example`. The real
file is `/etc/rhu-labchain/blockchain-worker.env`, owned by
`root:rhu-labchain-worker` with mode **0640**; its root-owned containing directory
has mode **0750**. Only the systemd manager loads it using `EnvironmentFile=`.
`WorkerSettings` never opens a dotenv file. FastAPI continues to use its own
unchanged private `.env`; the unit makes that file inaccessible to the worker.
The worker requires DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD, with an
operator-approved MySQL account connecting to localhost. It does not require
NODE_ID, NODE_NAME, authentication configuration or the MFA encryption key.
The preparation script never creates a DB user, grants permissions, reads the
password file or creates/edits a real DB password. The operator must configure
credentials separately; never copy the FastAPI environment wholesale.

The template uses systemd EnvironmentFile syntax, not shell commands or variable
expansion. Keep the JSON adapter argv in single quotes as shown. Delivery defaults
to false. Gateway paths remain optional to FastAPI but required by an enabled
worker. Private key **contents** never belong in environment variables or argv.

| Setting | Default / purpose |
| --- | --- |
| BLOCKCHAIN_DELIVERY_ENABLED | false; explicit operator enablement required |
| BLOCKCHAIN_GATEWAY_ENDPOINT | 127.0.0.1:7051 |
| BLOCKCHAIN_GATEWAY_TLS_CA_PATH | required absolute path when enabled |
| BLOCKCHAIN_CLIENT_MSP_ID | Org1MSP |
| BLOCKCHAIN_CLIENT_CERT_PATH | required dedicated client certificate path |
| BLOCKCHAIN_CLIENT_KEY_PATH | required dedicated client key path; owned by worker, mode 0600, parent 0700 |
| BLOCKCHAIN_CHANNEL | labchain-channel |
| BLOCKCHAIN_CHAINCODE | labchain-anchor |
| BLOCKCHAIN_SOURCE_NODE / BLOCKCHAIN_SOURCE_MSP | node1 / Org1MSP; existing capture settings |
| BLOCKCHAIN_ADAPTER_COMMAND | JSON argv array for /usr/bin/node and the project's blockchain/gateway-adapter/src/cli.js only |
| BLOCKCHAIN_WORKER_POLL_SECONDS | 2 |
| BLOCKCHAIN_WORKER_BATCH_SIZE | 1; sequential claims, maximum 100 |
| BLOCKCHAIN_WORKER_MAX_ATTEMPTS | 8; maximum configurable 100 |
| BLOCKCHAIN_WORKER_RETRY_BASE_SECONDS | 15 |
| BLOCKCHAIN_WORKER_RETRY_MAX_SECONDS | 900; maximum configurable 86400 |
| BLOCKCHAIN_WORKER_LEASE_SECONDS | 120; must be at least timeout + 10 |
| BLOCKCHAIN_ADAPTER_TIMEOUT_SECONDS | 90 total per attempt; maximum configurable 90 |

Before creating a database session factory or claiming an event, the worker
validates settings, file ownership/permissions and actual credentials. The fixed
`check-credentials.js` subprocess invokes the existing adapter's cryptographic
validator **offline** with a five-second limit: client role (never admin/peer/orderer),
EC key pairing, certificate dates, issuing CA and TLS CA. It never opens a Gateway
connection. The same validation remains enforced on every delivery invocation. The worker allows only the fixed Node
executable and project adapter script, shell=False, at most 4096 stdin bytes and
16384 bytes each of stdout/stderr. Duplicate JSON keys, malformed receipts,
unknown fields/codes and mismatched retryability fail closed. Output and time
limits terminate/reap the subprocess group. Only explicitly constructed Gateway
settings, PATH, LANG and TZ reach Node; inherited NODE_OPTIONS, LD_PRELOAD,
proxy settings and DB secrets do not. No peer, osnadmin or docker command is used.

## Dedicated service account and preparation

The production account is **rhu-labchain-worker:rhu-labchain-worker**: a locked
system account with `/usr/sbin/nologin`, no supplementary groups, no sudo and no
Docker privileges. **Keep rhuadmin in the Docker group** as the Fabric operator;
do not share its account or remove its privileges to run this worker.

The worker startup guard is retained and strengthened. It rejects real/effective
root, Docker primary/supplementary membership, readable or writable Docker control
sockets (including rootless locations), and alternate DOCKER_HOST configuration.
Missing or malformed client credentials fail before any claim. The service account
gets no exemption. Existing incompatible accounts cause preparation to stop;
the script does not silently remove group memberships or change login policy.

The source unit is `deploy/rhu-labchain-blockchain-worker.service`. It uses the
new account and external EnvironmentFile in `/opt/rhu-labchain`. It has no
capabilities or supplementary-group grants, no privilege escalation, read-only
system paths, private temporary/devices and protected kernel settings. Docker,
containerd and rootless socket locations, the web `.env`, original operator
runtime, generated Fabric crypto and administrative tooling are inaccessible.
The fixed Node subprocess inherits the same identity, capabilities and filesystem
sandbox. MemoryDenyWriteExecute is omitted to preserve Node/V8 operation.

Python bytecode writes are disabled. The repository and venv remain owned by their
existing owners; the worker needs read/execute only. No repository chown, chmod or
ACL grant is performed. Runtime identity files remain read-only inside the running
unit's ProtectSystem=strict sandbox even though their owner is the worker.
Restart is on-failure, stop timeout is 110 seconds, and KillMode=mixed allows a
bounded in-flight adapter call to finish before forced cleanup.

Only these existing CLIENT materials are copied into the external runtime:

```text
/var/lib/rhu-labchain/blockchain-worker/          # worker:worker, 0700
  fabric-client/org1/msp/
    signcerts/client-cert.pem                   # 0600
    keystore/client-key.pem                     # 0600
    cacerts/org1-ca.pem                         # public signing CA certificate, 0600
  tls/peer1-ca.crt                              # public TLS CA certificate, 0600
```

Every nested directory is 0700 and every copied file is worker-owned 0600. No CA
signing key, administrator identity, peer/orderer identity, enrollment secret or
full crypto tree is copied. The Node Gateway signer needs the client certificate,
its key and trust certificates; it does not require copying an entire peer MSP.
The original `blockchain/network/runtime/app-client-single-vps/org1/` is never
moved, re-owned, regenerated or otherwise changed.

`deploy/prepare-blockchain-worker.sh` is the future **root-operated preparation
entry point**, backed by the standard-library-only `prepare_blockchain_worker.py`.
It accepts no arguments and clears inherited environment/Python hooks. It has not
been run against production by this implementation. After separate review, its
behavior is:

1. Require root, serialize preparation, and require the worker to be stopped and
   disabled. Existing worker-account processes also cause refusal.
2. Check Git tracking/ignore rules and bounded regular files; reject symlinks,
   ambiguous credentials and unsafe paths. Validate the source CLIENT role, key
   pairing and chain to the retained public Org1 signing CA before account changes.
3. Create the system group/user only if absent; validate system UID/GID, locked
   password, non-login shell, home, group membership and absence of sudo privileges.
4. Create root-owned parent/config directories and the worker-owned private runtime;
   copy exactly the four allowlisted files with restrictive permissions. Existing
   identical material is retained. Changed identities or unexpected runtime files
   abort for separately reviewed rotation; nothing is deleted to make a rerun pass.
5. As the worker identity, verify Python imports and the startup privilege guard,
   denial of Docker/web-secret access, no project write permission, and offline Node
   validation of the copied client. No DB engine, Gateway call or delivery cycle is
   started by these probes.
6. Validate/install the root-owned 0644 unit and run daemon-reload. Repeating this
   reload is safe and recovers an interrupted previous preparation.
7. Never create or read the real environment file. If present, require root:worker
   ownership and mode 0640; if absent, print its required path/permissions and leave
   the worker stopped. Never start, enable, stop/restart other services, modify
   MySQL, regenerate Fabric crypto or change rhuadmin's groups.

No production preparation was performed during this task. Do not execute the
preparation script or any worker command automatically based on this document.
Later deployment must separately review the source, run preparation as root,
provision the external environment with delivery disabled, and validate the
actual service sandbox. No DB migration is needed. The shell/Python preparation
files must remain adjacent, and required host tools include systemd, shadow account
tools, runuser, sudo (policy inspection), pgrep, Git, OpenSSL, Python and Node.

After separate deployment authorization, the entry point supports continuous mode
and `--once`; **--once is one configured batch and can write Fabric anchors, not a
dry run**. Manual invocation also requires the worker's external process environment;
it cannot fall back to the FastAPI dotenv. Never run it as root or rhuadmin. The
preparation probes only import code and validate credentials, so they do not invoke
this entry point's processing loop.

Use `journalctl -u rhu-labchain-blockchain-worker` for sanitized transitions and
`systemctl status --no-pager` for restart/start-limit failures after controlled
deployment. To pause consumption later, stop the service and allow its current
attempt to finish; keep the external enable flag false to prevent future starts
from consuming work. No service was started or enabled in this follow-up.

Fabric outages leave clinical workflows available and cause bounded outbox
retries. A long outage can exhaust events into DEAD and block dependents, requiring
manual review after recovery. This single-VPS prototype still shares host, disk
and clock failure domains; multiple workers do not create infrastructure HA.
The fixed Org1 client/node1 Gateway configuration intentionally follows Phase
8B-2. Other source identities/endpoints require a separately reviewed extension.
Keep host clocks synchronized. Process-per-call overhead and local world-state
trust are prototype tradeoffs; capacity and prolonged-outage recovery need
operational validation before production enablement.

## Verification

Tests use synthetic SQLite data, fake adapter submissions, local dummy subprocesses
and a separate, socket-only ephemeral MySQL server. The MySQL probe verifies
SKIP LOCKED, distinct claims, nonexpired/expired leases, all stale-token update
paths and lost-acknowledgement reconciliation. It never uses application DB
credentials or a TCP listener. Gateway regression tests use their existing fakes.

```bash
.venv/bin/python -m pytest tests/test_phase_8b_delivery.py tests/test_phase_8b_adapter_bridge.py tests/test_phase_8b_worker_cli.py tests/test_phase_8b_delivery_mysql.py tests/test_phase_8b_worker_deployment.py -vv -ra
.venv/bin/python -m pytest tests/test_phase_8b_outbox.py tests/test_phase_8b_migration.py tests/test_phase_5b_release.py tests/test_phase_5b_mysql.py tests/test_application.py tests/test_phase_7a_frontend_hosting.py -ra
npm --prefix blockchain/gateway-adapter test
LABCHAIN_FABRIC_TOOLS=/opt/rhu-labchain/blockchain/network/tools .venv/bin/python -m pytest -ra
bash -n deploy/prepare-blockchain-worker.sh
systemd-analyze verify deploy/rhu-labchain-blockchain-worker.service
git diff --check
```

## Implementation verification record — 2026-09-28

- Focused Phase 8B-3: **179 passed** (178 unit/bridge/CLI cases and one real
  MySQL probe covering concurrent claims, SKIP LOCKED, lease recovery, stale
  confirm/fail/dead fencing and lost-acknowledgement reconciliation).
- Existing Phase 8B-1 capture/migration, report lifecycle/MySQL and readiness
  regressions: **150 passed** (77 outbox/migration, 70 report/MySQL, 3 readiness).
- Existing Gateway adapter: **44 passed**, all fake-based; no live submission.
- Complete Python suite with the installed Fabric tools: **1,386 passed**,
  two existing Starlette/httpx and AnyIO deprecation warnings, 1429.14 seconds.
- Source systemd unit: `systemd-analyze verify` passed without diagnostics.
- `git diff --check` passed; new untracked source files also passed a separate
  whitespace check.

The implementation did not start/install/enable the production worker, consume
production outbox rows, perform a Fabric write, run a production DB migration,
change account groups, or commit changes. The original operator-account blocker
is addressed by the dedicated-account source changes described above. Actual account preparation and controlled
integration/service verification remain separate deployment steps.


## Dedicated-account follow-up — 2026-09-29

Files added or updated for this follow-up (including edits to the still-uncommitted
Phase 8B-3 implementation):

- Deployment: `deploy/rhu-labchain-blockchain-worker.service`,
  `deploy/prepare-blockchain-worker.sh`, `deploy/prepare_blockchain_worker.py`,
  `deploy/blockchain-worker.env.example`, `deploy/README.md`, `.gitignore`,
  `.env.example`.
- Python: `app/blockchain_config.py`, `app/worker_config.py`, `app/config.py`,
  `app/cli/blockchain_worker.py`,
  `app/services/blockchain_event_validation.py`,
  `app/services/blockchain_outbox_service.py`,
  `app/services/blockchain_adapter_service.py`,
  `app/services/blockchain_delivery_service.py`.
- Gateway: `blockchain/gateway-adapter/src/check-credentials.js`,
  `blockchain/gateway-adapter/package.json`,
  `blockchain/gateway-adapter/test/credentials.test.js`.
- Tests: `tests/test_phase_8b_worker_deployment.py`,
  `tests/test_phase_8b_worker_cli.py`, `tests/test_phase_8b_adapter_bridge.py`.
- Documentation: this file, `docs/PHASE_8B_DELIVERY_WORKER.md`.

Completed checks:

- Focused delivery/bridge/CLI, disposable MySQL and deployment tests:
  **218 passed**, two existing deprecation warnings, 96.42 seconds.
- Phase 8B-1 capture/migration, report lifecycle/MySQL, application and frontend
  hosting regressions: **157 passed**, two existing warnings, 220.84 seconds.
- Gateway tests: **45 passed**. Gateway JavaScript syntax checks passed.
- Complete Python suite with the installed Fabric tools: **1,425 passed**,
  two existing Starlette/httpx and AnyIO deprecation warnings, 1242.06 seconds.
- `bash -n deploy/prepare-blockchain-worker.sh` and
  `systemd-analyze verify deploy/rhu-labchain-blockchain-worker.service` passed.
- `git diff --check` passed, as did separate whitespace checks for all 19
  untracked source files.

Read-only host checks confirmed that the production worker account, installed
unit, external environment and worker runtime were absent. Systemd reported
`LoadState=not-found`, `ActiveState=inactive`, `SubState=dead`. The operator
`rhuadmin` retained Docker membership. Tests used fake account administration and
synthetic credentials; no production preparation or live Fabric write occurred.
