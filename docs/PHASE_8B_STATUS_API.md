# Phase 8B-4A: permissioned blockchain anchoring status

This phase adds MySQL-backed API projections only. It does not submit or evaluate
Fabric transactions, inspect systemd, read worker secrets, change report mutations,
or introduce frontend UI. No migration or worker change is required.

## Meaning and boundaries

Blockchain status describes **evidence anchoring**, independently of clinical
validity, PDF integrity, approval/release state and public report authenticity.
Clinical/report state remains authoritative in MySQL. In particular:

- `NOT_ANCHORED`: no matching Phase 8B release evidence (including legacy reports),
  or a revoked report lacks evidence for its later lifecycle. This does not imply
  a fake or invalid report.
- `PENDING`: queued evidence, or an expired processing lease awaiting reclamation.
- `PROCESSING`: an event has a currently valid lease; staff detail only.
- `RETRYING`: the worker recorded retryable `FAILED`, including scheduled retries.
- `CONFIRMED`: MySQL records a VALID Fabric commit or exact ledger reconciliation,
  with a transaction ID and confirmation time. This API does not recheck Fabric.
- `FAILED`: automated anchoring reached `DEAD` (or receipt metadata is inconsistent)
  and requires staff intervention. This does not invalidate the clinical report.

`PENDING` and `RETRYING` do not block report use. Existing report access, release,
revocation and PDF integrity rules continue to apply. Patient/public responses
collapse `PROCESSING` to `PENDING` and reveal no queue or lease metadata.

## Permission and operational endpoint

`GET /api/v1/blockchain/status` requires authentication, an active staff/admin
role (`SYSTEM_ADMIN`, `LAB_STAFF`, `LAB_SUPERVISOR` or `DOCTOR`), and
`BLOCKCHAIN_STATUS_VIEW`. The existing active `SYSTEM_ADMIN` permission bypass
applies. Responses use the existing `PrivateRoute` and `Cache-Control: no-store`.

The permission is added through the existing idempotent permission catalog.
Consistent with that mechanism, bootstrap does not create role grants or change
existing assignments. Administrators therefore have access by default; other
appropriate staff roles require an explicit reviewed permission assignment.
Patients receive no grant and a patient-only role cannot access this endpoint
even if someone incorrectly assigns the permission to it. No production permission
bootstrap was run during this implementation.

Example response:

```json
{
  "delivery_enabled": null,
  "counts": {"pending": 0, "processing": 0, "confirmed": 1, "failed": 0, "dead": 0},
  "last_confirmed_at": "2026-09-29T12:34:40.408596",
  "last_confirmed_transaction_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "oldest_pending_at": null,
  "worker_health": "IDLE"
}
```

`delivery_enabled` is deliberately **unknown (`null`)**. There is no persistent
worker heartbeat/enablement record in MySQL. The web process has separate settings
from the worker; its enable flag cannot establish whether the worker is enabled
or running. This API neither opens `/etc/rhu-labchain/blockchain-worker.env` nor
probes the OS. Historical confirmations cannot establish current enablement.
Actual enablement/liveness would require separately designed worker telemetry.

Counts cover all outbox events, including synthetic events. `last_confirmed_at`
and its transaction ID come from the same newest confirmed row, ordered by
confirmation time and then event ID. `oldest_pending_at` is the earliest creation
time among all PENDING rows, including future-scheduled rows. Datetimes follow the
existing API's UTC convention.

`worker_health` is a deterministic **outbox condition**, not worker-process or
Fabric-peer health. Rules are applied in this order:

| Priority | Condition | Value |
| --- | --- | --- |
| 1 | Any DEAD event | ERROR |
| 2 | Any FAILED event, or PROCESSING with an expired/missing lease expiry | DEGRADED |
| 3 | Any PROCESSING event with a valid lease, or PENDING work due now | ACTIVE |
| 4 | Otherwise: empty queue, confirmed-only history, or future PENDING work | IDLE |

Expiry equal to the sampled UTC time is expired. A retry backlog is DEGRADED even
when its next attempt is scheduled later. ERROR wins over every other condition.
ACTIVE means eligible or leased work exists; it is not proof that a worker is
alive. IDLE is not proof that the worker is stopped. These states never affect
`GET /api/v1/ready`, which continues to check only MySQL/core application readiness.

## Staff report detail

Existing responses using `ReportDetail`, including `GET /api/v1/reports/{report_id}`,
add an `anchoring` object. Existing report permissions still govern these responses;
the new operational permission is required only for the global endpoint.

```json
{
  "anchoring": {
    "status": "PENDING",
    "release": {
      "status": "CONFIRMED",
      "confirmed_at": "2026-09-29T12:34:40.408596",
      "transaction_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "block_number": 5
    },
    "revocation": {
      "status": "PENDING",
      "confirmed_at": null,
      "transaction_id": null,
      "block_number": null
    },
    "supersession": null
  }
}
```

Release is always represented; absent release evidence has `NOT_ANCHORED` and null
receipt fields. Absent revocation/supersession is null. Receipt fields appear only
for CONFIRMED evidence with validation code 0, a lowercase 64-character transaction
ID, and a confirmation timestamp.

Every recorded lifecycle matters. Aggregate precedence is FAILED, RETRYING,
PROCESSING, PENDING, CONFIRMED. A later pending revocation/supersession can never be
hidden by confirmed release evidence. Repeated supersession events are combined
conservatively; any unconfirmed transition keeps that lifecycle unconfirmed.
When all transitions of a type are confirmed, its newest confirmation is shown.
A revoked report without any matching revocation/supersession evidence remains
NOT_ANCHORED overall, even if its release was confirmed.

## Patient and public contracts

The existing owned, released-report detail endpoint
`GET /api/v1/patient/reports/{report_id}` adds:

```json
{"blockchain_verification": {"status": "CONFIRMED", "confirmed_at": "2026-09-29T12:34:40.408596"}}
```

Ownership and current access are checked first. Revoked reports remain inaccessible
through the patient portal under its existing policy. The patient object permits
only `status` and `confirmed_at`. Confirmation time is null unless all relevant
evidence is confirmed, then reflects the latest lifecycle confirmation.

Known-token public verification adds `blockchain_status` and optionally
`blockchain_confirmed_at`. The safe status enumeration is NOT_ANCHORED, PENDING,
CONFIRMED, RETRYING, FAILED. Unknown/malformed tokens retain the exact neutral
NOT_FOUND response, without blockchain fields.

Public `status` and `message` remain governed by report/PDF verification. Examples:

| MySQL report / evidence | Public authenticity status | Blockchain status |
| --- | --- | --- |
| Released, intact PDF; release confirmed | VERIFIED | CONFIRMED |
| Revoked; release confirmed, revocation pending | REVOKED | PENDING |
| Revoked; release and revocation confirmed | REVOKED | CONFIRMED |
| Legacy released report, intact PDF | VERIFIED | NOT_ANCHORED |
| Altered PDF, captured release confirmed | ALTERED | CONFIRMED |

No public or patient transaction IDs, event UUIDs, block numbers, source node/MSP,
retry counts, error codes, internal event IDs or raw worker errors are exposed.
The staff anchoring object also excludes canonical payloads, lease tokens/expiries,
raw errors, database entity IDs, actor IDs and origin node IDs. Explicit schemas
allowlist every returned field; no SQLAlchemy event model is serialized.

## Queries and compatibility

The global projection uses two queries, in addition to authentication: grouped
aggregate counts/times and the latest confirmation. The existing status-leading
outbox index is available for grouping/filtering. Counts still require scanning
outbox entries; no per-event ORM models or canonical payloads are loaded. Confirmation ordering may sort matching confirmed
rows; no new index or schema migration is introduced.

Report projection uses one query bounded by `entity_type='REPORT'`, internal report
ID and frozen report UUID, with lifecycle type filtering. The existing entity index
supports this lookup. Legacy reports with no UUID need no event query. Patient
detail reuses the projection already read for its internal report detail.

Staff and patient list response contracts are unchanged and perform no new outbox
queries. Anchoring display on lists is deferred to a future batch-query design.
No report mutation rules, delivery rules, historical migrations, health/readiness
routes, worker environment, frontend files or production services are changed.

## Validation and deployment boundary

Focused tests use synthetic SQLite fixtures, temporary report artifacts, blocked
network connections and forbidden subprocess calls. They cover authentication,
permission bootstrap, all states, health precedence, lifecycle combinations,
privacy, patient ownership, unknown tokens, readiness and bounded query counts.
Existing report, patient, public verification and permission regressions are rerun.
The complete suite uses disposable test databases and the installed Fabric tools.

This is a source-only change. No production DB/bootstrap, Fabric transaction,
service restart or commit is part of this phase. Deployment and reviewed permission
assignment remain separate operational steps. Phase 8B-4B can add frontend status
presentation using these contracts; badges, explorer links, manual retry/requeue,
and live Fabric health are not implemented here.

## Files changed

- `app/api/blockchain.py`: permissioned operational endpoint.
- `app/main.py`: router registration.
- `app/schemas/blockchain.py`: explicit operational/staff/patient contracts.
- `app/schemas/reporting.py`: staff detail and separate public-safe fields.
- `app/schemas/patient_portal.py`: patient detail field.
- `app/services/blockchain_status_service.py`: MySQL projections and redaction.
- `app/services/permission_catalog.py`: idempotent permission metadata.
- `app/services/reporting_service.py`: staff detail projection.
- `app/services/patient_portal_service.py`: owned-report safe projection.
- `app/services/report_release_service.py`: public verification projection.
- `tests/test_phase_8b_status.py`: focused authorization/privacy/lifecycle/query tests.
- `tests/test_phase_3b_identity_admin.py`: bootstrap coverage for the new permission.
- `tests/test_phase_5b_release.py`: precise additive public response contract.
- `docs/PHASE_8B_STATUS_API.md`: contracts, operational limitations and validation.

## Verification record — 2026-09-29

- Focused Phase 8B-4A suite: **49 passed**, two existing deprecation warnings,
  39.41 seconds.
- Report generation/release and disposable MySQL, patient portal/ownership and
  MFA, permission administration/bootstrap, readiness and Phase 8B-1 outbox
  regressions: **474 passed**, two existing warnings, 535.59 seconds.
- Complete Python suite with the installed Fabric tools: **1,504 passed**,
  two existing Starlette/httpx and AnyIO deprecation warnings, 1312.28 seconds
  (21 minutes 52 seconds). The detached supervisor recorded exit status 0.

Focused command:

```bash
.venv/bin/python -m pytest tests/test_phase_8b_status.py -vv -ra --tb=long
```

Regression command:

```bash
.venv/bin/python -m pytest tests/test_phase_5a_reports.py tests/test_phase_5b_release.py tests/test_phase_5b_mysql.py tests/test_phase_6a_patient_portal.py tests/test_phase_6a_mysql.py tests/test_phase_6b_mfa.py tests/test_phase_3b_identity_admin.py tests/test_application.py tests/test_phase_8b_outbox.py -vv -ra --tb=long
```

The full run uses `LABCHAIN_FABRIC_TOOLS=/opt/rhu-labchain/blockchain/network/tools`
and `.venv/bin/python -m pytest -vv -ra --tb=long`. A detached supervisor owns
pytest and persists its exit code, log and PID outside Git, so terminal/session
interruption does not lose the run. Logs and exit status files for this validation
are under `/tmp/rhu-phase8b4a-validation-wvvqwbd8/`.

Completion review on 2026-10-04 recovered both successful detached runs after the
session interruption. All application and test files predate the full run; only
this documentation was completed afterward. `git diff --check` and separate
whitespace checks for all five new files passed. The 14-file scope excludes
health/readiness, migrations, frontend, worker and deployment files. No production
DB change, permission bootstrap, Fabric write, service restart or commit was made
for Phase 8B-4A. Frontend presentation remains Phase 8B-4B work.
