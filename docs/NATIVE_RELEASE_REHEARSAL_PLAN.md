# Native release rehearsal and operator approval checklist

Prepared 19 October 2026. **Plan only: no native database test, migration,
provisioning, restore, privilege change or service operation was executed.**
Read together with [MAJOR_UPDATE_RELEASE_READINESS.md](MAJOR_UPDATE_RELEASE_READINESS.md),
[AUTO_CODE_MIGRATION.md](AUTO_CODE_MIGRATION.md) and
[MYSQL_MIGRATION_REHEARSAL.md](MYSQL_MIGRATION_REHEARSAL.md).

## Isolation boundary and approvals

Use one separately approved, disposable VM (or equivalent isolated development
host) with **no production or existing development data, credentials, mounts,
MySQL sockets, Fabric keys, peer volumes, or route to production services**. Do not
reuse or reset the populated `rhu_labchain_dev` on the current VPS. Record the new
host identity, server UUID, private data-directory identity, owner, source commit,
resource budget and evidence-retention location before authorization. Database
names alone are not sufficient isolation evidence.

Copy the approved development source to `/home/rhuadmin/rhu-labchain-dev` on that
isolated host, branch `major-update-v1`, without `.env`, runtime directories or
private assets. This preserves the existing rehearsal's fixed-worktree guard.
Provisioning pinned dependencies and a MySQL version compatible with the eventual
production version requires separate approval. Run as an unprivileged development
user, not root. Do not install or change system services on the production VPS.

On the isolated host only, an approved operator may provision a fresh local
MySQL instance and dedicated `rhu_labchain_dev` / `rhu_dev` account bound to
127.0.0.1:3306. This is a **different server and empty schema**, not a reset of the
existing database with the same name. The current rehearsal accepts only those
names and exact local account matches. Passwords come from its echo-disabled
prompt or secure runtime environment, never arguments, Git or logs. Do not weaken
its guards to point it at another host. Production-derived data is not needed for
synthetic runs; any later production clone requires separate privacy approval.

The existing populated rehearsal can be inspected only under separate read-only
authorization using `scripts/mysql_migration_verify.py`. Its SELECT-only account
requirement is strict. Changes to that account's privileges need explicit approval;
this plan does not authorize them or treat the marker as completion evidence.

## Existing native test setup: source review

All 74 selected test cases reach one of two fixture definitions:
`tests/test_phase_3b_mysql.py::disposable_mysql` or
`tests/test_phase_10_migration.py::disposable_mysql` (also imported by Phase 11).
Both create a private `TemporaryDirectory` under `/tmp/rhu-phase3b-mysql-*` and:

- Start `mysqld` with `--no-defaults`, a new data directory and private log.
- Initialize **only that new directory**, with `--initialize-insecure`.
- Disable TCP (`--skip-networking`) and MySQL X (`--mysqlx=OFF`); use an explicit
  Unix socket and PID file in the temporary directory.
- Terminate only their own subprocess and remove only their temporary directory.

The 13 `tests/mysql*probe.py` helpers validate the resolved socket's `/tmp` parent,
expected private-directory prefix and socket file type. Every native engine binds
`unix_socket` explicitly and uses synthetic database names. There is no TCP
fallback. Phase 8B/10/11 migration probes import `app.database` but replace its
engine with this socket-bound engine before migration execution. Other probes use
local engines and synthetic metadata or explicitly bound historical revisions.
Their CREATE/DROP operations target their synthetic databases in that private
server. Some tests intentionally exercise *older* downgrades; that is not approval
to downgrade either new release migration.

`tests/conftest.py` installs synthetic settings before collection and preserves the
ordinary socket network guard. Native probes run in subprocesses, so that guard
alone is not their protection; their explicit socket binding and the isolated host
are essential. The fixture subprocesses inherit synthetic settings from pytest.
Do not run helper scripts directly with arbitrary sockets, use `python -O`, set
`PYTHONOPTIMIZE`, replace the fixture, supply host credentials, or disable the
network guard. These invocation constraints preserve the inspected protection;
the scripts are not a sandbox against hostile code or a malicious same-user socket.

The reviewed pytest invocation below has no target path or configuration leading
to production. No native fixture was executed to make this assessment. If mysqld
is missing, the tests skip: **skips do not satisfy the release gate**. On failure,
retain captured synthetic logs/JUnit before fixture cleanup. Never rerun against
a real database as a workaround.

## Integrated A → D rehearsal procedure

This is one coordinated operator procedure reusing existing helpers, not a new
replacement framework or a claim that an A-only script now tests D. Review any
operator driver before execution. No single existing command automates all report
fixtures, D failure injection, backups and restoration described here.

### A. Prepare baseline and evidence

1. Confirm the isolated host/database identity, MySQL 8.0.16+ CHECK enforcement,
   InnoDB, SQL mode, available storage, migration permissions and session timeouts.
   Native MySQL is required; do not substitute SQLite or MariaDB. Record schema
   and effective column collations with their PAD attributes. Repeat later with
   every actual production column collation once separately inspected.
2. Fence all isolated application, worker, importer, scheduled and manual writers.
   Record owner/process inventory, network rules, grants, active connection and
   InnoDB transaction inventories using an authorized observer with adequate
   visibility. Use a negative write attempt by a synthetic non-migrator identity
   to prove exclusion, not merely an empty process list. Prevent service restarts
   throughout the window. The migrator and approved verifier are the only allowed
   sessions. `GET_LOCK` and `RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED=1` do not provide
   this fence. Keep the acknowledgement scoped to the migration process.
3. Use the existing connection-only `ENVIRONMENT`/`isolated_config` mechanism in
   `scripts/mysql_migration_rehearsal.py`, with a connection whose database,
   authenticated identity and host have been verified. It does not import the
   application's settings/engine. Build the real historical migrations from base
   to **`20261005_01`**; never `Base.metadata.create_all()` as a migration substitute.
   The A-only environment contains ten exact ancestor revisions through
   `20261015_01`; validate their bytes and chain before running it.
4. Reuse `fixture_values`, `prepare_history`, `historical_snapshot`,
   `index_snapshot` and `validate_checks`. Seed the seven resource histories before
   A, preserving case/accent/custom/unpadded/trailing-space examples. Expected
   identifiers include `PREFIX-000007`, lower-case `prefix-000011`, `PREFIX-17`,
   `CUSTOM-ARCHIVE`, accented prefix with `000023`, and `PREFIX-000031 `.
   Department insertion precedes dependent tests, with real foreign keys retained.
5. Add synthetic historical report fixtures using **baseline-compatible reflected
   tables or reviewed SQL**, not the current LabReport ORM column set: a draft,
   released report, revoked/superseded history, result/patient snapshots, actual
   stored PDF bytes and digests, verification and synthetic outbox records. Use
   existing report test fixtures as the source of valid relationships and status
   prerequisites. No production record or real Fabric submission is needed.
   Preserve real file artifacts and a byte/hash manifest; do not replace this
   preservation check with a mocked renderer. Existing PDF v1 expectations in
   `tests/test_report_pdf_v2.py` and release/outbox fixtures define the contracts.
6. Capture table/row counts, original indexes, per-row historical identifier HEX,
   report/status/snapshot manifests, private file SHA-256, Alembic revision and
   source file hashes. Take an encrypted baseline database+file backup with grants
   and environment/configuration references stored separately. Restore to a second
   approved isolated target and verify it **before** starting migration. Preserve
   a clean baseline snapshot for each destructive failure scenario.

### B. Upgrade and verify success in order

| Sequence | Column | Prefix / minimum digits | Synthetic effective collation | Seed |
| --- | --- | --- | --- | ---: |
| PATIENT | patient.patient_code | PAT / 6 | utf8mb4_unicode_ci (PAD SPACE) | 31 |
| STAFF | staff.staff_code | STF / 6 | utf8mb4_0900_ai_ci (NO PAD) | 23 |
| DEPARTMENT | lab_department.department_code | DEP / 3 | utf8mb4_unicode_ci | 31 |
| TEST | test_catalog.test_code | TST / 4 | utf8mb4_0900_ai_ci | 23 |
| PANEL | test_panel.panel_code | PNL / 4 | utf8mb4_unicode_ci | 31 |
| REJECTION_REASON | rejection_reason.reason_code | REJ / 3 | utf8mb4_0900_ai_ci | 23 |
| REPORT_TEMPLATE | report_template.template_code | TMP / 3 | utf8mb4_unicode_ci | 31 |

1. Exercise existing ambiguity and overflow refusals before DDL; confirm original
   revision/data/indexes remain unchanged and no sequence table is created. Native
   collation equivalence, not Python normalization, determines reserved values.
   The source migration allowlist must match observed column metadata. Unsupported
   collations require review; do not alter real history/collations to make it pass.
2. Upgrade explicitly to `20261015_01`. Verify seven exact rows, unique destination
   indexes, InnoDB, finalized CHECK names and seed values above. Test invalid
   counter/padding assignments inside savepoints: accept only MySQL errno **3819**
   even when PyMySQL wraps it as OperationalError; roll back each invalid change.
3. Verify repeated allocation (including autoflush disabled), >=20 concurrent
   allocations on independent sessions, both counter limits, missing sequences,
   uniqueness collision rollback and synthetic record/counter atomicity using the
   existing allocator probe cases. No caller-independent commit or unrelated
   flush is permitted. Existing historical identifier bytes must be unchanged.
   One committed allocation per resource from the original fixture seeds yields
   32/24/32/24/32/24/32; if additional cases allocate, track exact expected deltas
   separately. Repeating the Alembic upgrade must not reset any counter.
4. For D, prepare a private connection-only Alembic environment by reusing the same
   `ENVIRONMENT` text and verified connection, copying **all eleven exact source
   revision files** and checking one linear head `20261018_01`. This is a separate
   config for the combined procedure: do not mutate the A-only global HEAD,
   remove its assertions, use the application's normal env.py, or silently expand
   the historical script. Explicitly upgrade A → **`20261018_01`**.
5. Verify nullable JSON `lab_report.presentation_snapshot`, unchanged old rows
   with SQL NULL in that new column, identical old PDF bytes/hashes and prior
   result/patient snapshots, signatory/release/audit/outbox/verification references.
   Generate a new synthetic report, confirm v2 snapshot capture, sign/approve/
   release through authorized paths and verify its stored PDF/digest. The legacy
   draft must still use v1. Change catalog/facility metadata afterward and prove
   both released versions remain immutable. Unknown presentation versions must
   refuse rendering, not fall back silently.
6. Against the migrated isolated API, verify all seven CREATE/PATCH contracts
   reject client codes with 422, including administrator requests; valid creates
   return actual generated codes. Historical records retain original codes/IDs.
   Include authorized edit, patient/staff permission separation, CSRF, inactive
   catalog rejection and historical PDF download checks. Reuse assertions from
   `tests/test_auto_code_master_schemas.py`, `test_auto_code_generation.py`,
   `test_report_pdf_v2.py`, `test_starter_catalog.py` and release/outbox tests.
   Bind the test API only to the verified isolated engine and private file root.
7. Repeat final upgrade; prove unchanged counters/history/reports. Capture
   sanitized success evidence. No marker or revision alone establishes completion.

### C. Failure, restoration and recovery evidence

Use a separately approved **fresh baseline clone per scenario**, never reset the
populated VPS database or overwrite the successful evidence instance.

- Reuse A's `seed-failure` and `revision-failure` injection points. Confirm real DDL
  persists, prior revision remains, DML rollback matches observation, and all old
  identifiers/reports/files remain unchanged. Unexpected state is a failure.
- For D, inject after ALTER adds the column but before Alembic version advancement;
  record the observed partial schema and A revision. Confirm no successful
  completion signal. Do not drop the column or stamp the new head to hide failure.
- Rehearse process interruption/connection loss and inspect actual state read-only
  before selecting recovery. Ordinary rollback does not undo MySQL DDL.
- Restore each failed clone from the approved baseline database+files recovery set
  into a distinct isolated target, then verify exact revision, constraints, row
  counts, identifiers, hashes, audit/outbox references and account-key compatibility.
  Record restore duration and accepted RPO/RTO. A backup that was never restored
  is not sufficient release evidence.
- Demonstrate no-write rollback of the application/database/files as one unit.
  Separately document the after-write decision: preserve new identifiers, audit,
  reports and outbox/ledger state and prefer forward repair. Do not recycle issued
  codes or pretend restoring MySQL rolls back blockchain history. Both new
  migration downgrades intentionally refuse; preserve that policy.

Archive source/artifact hashes, anonymized result summaries, fixture/file manifests,
backup checksums, before/after schema observations, failure categories/errno,
restore evidence and operator sign-off outside Git. Retain raw synthetic evidence
privately; never include passwords, connection URLs or actual patient identifiers.

## Exact 74-test selection — execution requires separate approval

Only after the isolated host is approved, pinned mysqld is available, the private
`/tmp` resource budget is adequate, `.env` is absent and source hashes match:

```bash
cd /home/rhuadmin/rhu-labchain-dev
set -euo pipefail
test "$(git branch --show-current)" = major-update-v1
test ! -e .env
test -z "${PYTHONOPTIMIZE:-}"
umask 077
native_logs=$(mktemp -d /tmp/rhu-native-release-evidence.XXXXXX)
.venv/bin/python -m pytest \
  tests/test_phase_3b_mysql.py tests/test_phase_3c_mysql.py \
  tests/test_phase_4a_mysql.py tests/test_phase_4b_mysql.py \
  tests/test_phase_5a_mysql.py tests/test_phase_5b_mysql.py \
  tests/test_phase_6a_mysql.py tests/test_phase_6b_mysql.py \
  tests/test_phase_8b_delivery_mysql.py tests/test_phase12_mysql.py \
  tests/test_phase_8b_migration.py::test_mysql_migration_and_constraints \
  tests/test_phase_10_migration.py::test_native_mysql_migration_queries_and_login_serialization \
  tests/test_phase_11_mysql.py::test_native_analytics_with_rich_synthetic_data \
  -q -ra --tb=short --junitxml="$native_logs/results.xml" \
  > "$native_logs/pytest.log" 2>&1
```

Expected collection is exactly **74**; the acceptance target is 74 passed, zero
failed/errored/skipped. Keep the log directory even if pytest exits nonzero.
Diagnose individual failures and rerun only affected cases. Do not add blanket
skips, disable network protections or rerun the full backend suite. These tests
primarily exercise historical locking/constraint/transaction behavior; their
success does **not** replace the combined A+D procedure above.

## Production go/no-go checklist and exact approval boundaries

The ordered production commands/decision table are in section 8 of
[MAJOR_UPDATE_RELEASE_READINESS.md](MAJOR_UPDATE_RELEASE_READINESS.md).
Before the operator executes that sequence, complete this evidence record:

| Gate | Required evidence / approval | Current state |
| --- | --- | --- |
| Release identity | Integration + security commits, locked dependencies, built frontend/backend checksums, migration hashes | Development preparation only; freeze approved release artifact |
| Native rehearsal | Isolated host identity, success + partial-DDL scenarios, 74-test JUnit, report/hash preservation | Not executed; explicit provisioning/migration/test approval required |
| Existing rehearsal | Separate read-only authorization and least-privilege verifier; preserve populated database | No connection or privilege change authorized here |
| Production preflight | Read-only schema/revision/collation inventory, capacity, filesystem/storage and permissions | Separate production inspection approval required; no secrets in report |
| Service inventory | Actual units/containers/timers/cron/importers/remote writers, owners, restart controls | Templates only; live inventory not yet verified |
| Backup | Same fenced-point DB + PDFs/attachments/private assets; protected keys/config; hashes and binlog/GTID position where applicable | Separate backup/access approval required |
| Restore | Independent isolated restore, hashes/records/audit/outbox/account checks, measured RTO/RPO, owner sign-off | Not demonstrated; separate restore/provisioning approval required |
| Writer fence | Maintenance, all API/worker/job/manual writers stopped/drained, restart prevention, DBA connection/transaction evidence, controlled denial check | Separate maintenance/service-control approval required |
| Staging | Verified release directory and static web root, correct file owners; keep secrets/runtime files separate, preserve previous artifact | Development build only; production copy/switch requires approval |
| Migration | Verified identity + baseline, acknowledgement after fence, A then D, per-step stop/check | Explicit production migration approval required |
| Health/acceptance | Auth/MFA/RBAC, dashboard, activation status, existing IDs, historical PDFs/hashes, signatory controls, queue reconciliation | Separate controlled smoke-test authorization; writes require explicit synthetic-data policy |
| Recovery | Named incident owner/deadline; pre-write restore vs post-write forward repair; ledger reconciliation | Approval required before any destructive recovery |
| Clinical use | Qualified facility sign-off, methods/units/specimens/reporting and active flags | New entries remain inactive; activation is separate authorization |

Checked-in templates name `rhu-labchain-node1.service` (API),
`rhu-labchain-blockchain-worker.service` (DB/outbox writer) and
`rhu-labchain-monitor.service` (read-only monitor). Verify actual instances and
other hosts; do not assume this is an exhaustive inventory. Preserve current
HTTPS/Nginx configuration and private report paths. No service inventory command
against live services was executed here.

Approval to run isolated tests is **not** approval to access production, change
production grants, take patient-data copies, migrate, stop/restart services,
push/merge or deploy. No production change is authorized by this plan.
