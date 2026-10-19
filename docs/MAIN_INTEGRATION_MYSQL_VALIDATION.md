# Main integration and native MySQL validation

Completed 19 October 2026. This record supersedes the earlier requirement for a
second VPS: the user confirmed this is an active development system and its
application records are disposable. Infrastructure, credentials, certificates,
wallets, keys and ledger state remain protected. Destructive tests ran only on
new, private MySQL instances on the existing VPS.

**Development integration and testing are complete. Active application cutover
still requires explicit authorization.** No active-database migration, rebuild,
service restart, frontend deployment, push or remote merge was performed.

## Git integration and recovery snapshot

Both worktrees were clean before integration. `main` was at `8622444`; the tested
development head was `b9fe4fc5d4fbbad779036365a48b58c89e22c8ac` and contained:

| Workstream / correction | Commit |
| --- | --- |
| A — automatic codes | `38ea407` |
| B — dashboard | `ae37c1b` |
| C — activation | `6d3e527` |
| D — laboratory workspace / PDF | `42b276b` |
| E — catalog | `dcb6bfb` |
| Integration correction and preparation | `b5b5656` |
| source-map-js 1.2.2 security patch | `b9fe4fc` |

An ancestor check confirmed fast-forward compatibility. `main` was advanced using
`git merge --ff-only major-update-v1`; no branch reset, force operation or
uncommitted-file overwrite occurred. A subsequent local test/documentation commit
contains this report and the diagnosed native fixture fixes; `main` is then
fast-forwarded to the same commit. Resolve the final identity with `git rev-parse
main` (also reported in the completion message). All earlier commits remain intact.

Before integration, a verified Git bundle containing both branches and a
single-transaction database dump were saved privately under:

```
/home/rhuadmin/.local/state/rhu-labchain/recovery/pre-main-integration-qo61y7gz
```

The directory contains `pre-integration.bundle`, `active-database.sql`, a checksum
and schema manifest, protected-file hashes and the read-only preflight summary.
Files are private; temporary client credentials were removed. No passwords were
printed or added to Git. `.env` and 214 checked protected files matched their
pre-integration hashes. No tracked blockchain infrastructure file was changed by
the workstream fast-forward. Report/signature storage and web-root assets were not
overwritten.

This is a **lightweight live development recovery snapshot**, not a claim that
application writers were stopped or a complete file/database cutover backup was
restored. Take a fresh coordinated backup under the eventual cutover writer fence.
The restore exercises below used synthetic data exclusively.

## All 74 previously excluded native tests

The original selection executed once: **59 passed, 15 failed, zero skipped**.
The failures were three test setup mismatches exposed by the newer migrations:

1. Phase 6A/6B (13 cases) walked the current chain without A's writer-exclusion
   acknowledgement. Their helpers now verify the exact private Unix socket,
   disabled TCP, an empty synthetic schema and absence of other schema sessions
   before setting the acknowledgement for the migration block. The previous
   environment value is restored afterward. The migration guard is unchanged.
2. Phase 8B (one case) compared its intentionally historical schema with a later
   PDF presentation column. Its exact comparison still covers all original
   columns, defaults, indexes and foreign keys; only the explicitly later column
   is excluded, and its absence at this historical revision is asserted. The new
   combined rehearsal separately verifies that column's actual migration.
3. Analytics (one case) migrated only to `20261005_01` while using the current ORM,
   causing MySQL error 1054 for `presentation_snapshot`. It now builds the current
   real migration chain on its validated private server with the same scoped
   acknowledgement. Historical revision tests were not changed to expect a new
   historical head.

Targeted reruns: **13/13** activation/MFA and **2/2** historical/analytics passed.
JUnit testcase identities were reconciled: every original failed case passed its
rerun. Therefore **all 74 distinct native cases have passing evidence**, with no
remaining failures or skips. This is not a claim of a second complete 74-case run.
No application business rule, authentication, CSRF or audit protection changed.

Evidence: `/tmp/rhu-main-native74.log` / `.xml`,
`/tmp/rhu-main-native-phase6.log` / `.xml`,
`/tmp/rhu-main-native-historical.log` / `.xml`.

## Combined A → D migration and recovery rehearsal

New focused entry point:

```bash
cd /home/rhuadmin/rhu-labchain-dev
.venv/bin/python -m pytest tests/test_native_release_rehearsal.py -q -ra --tb=short -s
```

**Result: 1 passed**, including all ten required stage markers. The first run
passed; the affected test alone was rerun after strengthening permission-denial,
full historical-row comparison and post-failure restoration assertions.

The test reuses `test_phase_3b_mysql.disposable_mysql` and the existing migration
rehearsal helpers. It validates the private, user-owned socket directory and the
server's actual socket, data directory and disabled TCP state. Neither
`rhu_labchain` nor `rhu_labchain_dev` may exist in that server. Only fixed
`rhu_release_*` synthetic schema names are allowed. The populated rehearsal
database on the host server was not connected to or reset. The fixture destroys
only its own temporary server directory after testing.

Verified stages:

- Real historical chain to baseline **`20261005_01`**, then A **`20261015_01`**,
  then D **`20261018_01`**, with exact eleven-revision source inventory and
  connection-only Alembic environment. No production configuration is loaded by
  that environment and no metadata.create_all shortcut replaces the migrations.
- Seven historical identifier fixtures, including mixed case, accents, unpadded
  numbers, custom codes and trailing spaces. Actual MySQL column PAD SPACE and
  NO PAD collations reserve the expected 31/23 alternating high-water marks.
  Ambiguous identifiers and overflow refuse before DDL.
- Writer exclusion in the private instance: exact server verification, no other
  schema session, SELECT-only observer can read fixtures but receives **1142**
  on UPDATE. The migration acknowledgement does not substitute for these checks.
- Seven sequence rows, exact named CHECKs, native **3819** CHECK failures handled
  under savepoints, first allocations and normal repeat-upgrade without resetting
  counters. Missing-sequence and exhaustion errors remain correct.
- **20 independent concurrent sessions** produce 20 distinct Patient codes and
  committed records. Repeated allocations with autoflush disabled, rollback,
  destination uniqueness collision rollback, independent counters and both
  destination-length and BIGINT limits are checked.
- CREATE/PATCH Pydantic contracts reject all seven manually supplied codes and
  preserve native historical identifiers. Separate authenticated administrator
  API tests verify actual HTTP behavior, described below.
- Existing real v1 PDF bytes, recorded hash and all historical report columns,
  clinical snapshots and other baseline table rows survive both upgrades.
  Old presentation values remain SQL NULL. Repeating the final migration leaves
  the entire database snapshot unchanged.
- A legacy draft is signed, approved and released through the real services using
  v1; a newly generated report captures v2, is signed/approved/released, and renders
  a real v2 PDF. Existing stored PDF bytes remain unchanged. No Fabric submission
  is performed; release/outbox data belongs only to the synthetic instance.
- A real mysqldump backup and mysql restore reproduce the complete baseline row
  inventory in a separate schema; private PDF backup/restoration is byte-identical.
- Injected A seed-write failure, A revision-write failure and D failure after ALTER
  but before version advancement leave the expected partial DDL and old revision.
  After **each** failure, the baseline dump and files are restored again into a
  distinct new recovery schema and compared exactly. Failed schemas are not
  stamped, repaired or reset to conceal the failure. No new-migration downgrade
  or identifier recycling is used.

Evidence: `/tmp/rhu-main-combined-rehearsal.log`. Successful native CHECK handling
also resolves the previously identified PyMySQL classification concern through a
fresh run; it does not retroactively label the old populated rehearsal complete.

## Active database: inspected read-only

The running service points to `/opt/rhu-labchain`; its configured database is
**`rhu_labchain`**, MySQL **8.0.46-0ubuntu0.24.04.4**, Alembic
**`20261005_01`**. The expected baseline table inventory matches, all application
tables are InnoDB, and neither `code_sequence` nor the PDF presentation column
exists yet. The historical-code scanner ran in a read-only transaction, without
calling either upgrade, and accepted all seven histories. Each recognized
numeric high-water mark is zero; existing custom identifiers remain unchanged.

The actual columns use `utf8mb4_0900_ai_ci`, a supported NO PAD collation:

| Identifier | Actual VARCHAR length |
| --- | ---: |
| Patient / Staff | 20 / 20 |
| Department / Test / Panel | 30 / 30 / 30 |
| Rejection Reason / Report Template | **40 / 40** |

The older readiness report incorrectly listed the last two as 30; that
**documentation error** is corrected. Their models and actual migration DDL were
already 40, and the allocator reads model capacities directly. Counter limits and
application code do not change.

The active system had two patients, one report/verification and two blockchain
events at inspection. The existing stored PDF was read without rerendering and
matched its recorded SHA-256. These records were not modified by this task.
The active revision was checked again and remains `20261005_01`.

**Preferred path: ordinary A then D migrations. No clean rebuild is necessary or
proposed.** A rebuild would still require separate confirmation naming the exact
database; the statement that records are disposable is not used as reset approval.

## Focused development and running-service checks

- **140 passed**: allocation, master schemas, PDF v2, dashboard, activation and
  starter catalog selection.
- **8 passed**: authenticated administrator API cases covering generated-code
  uniqueness and immutable create/edit contracts for the seven resources.
- **37 passed**: frontend automatic-code and laboratory workspace tests.
- TypeScript and Vite build: **passed**, only inside the development frontend.
- Python syntax and `git diff --check`: **passed**.
- Main application's existing Python environment: `pip check` passed.
- Existing running `/api/v1/health` and `/api/v1/ready`: HTTP **200**, statuses
  `ok` and `ready`. These describe the already-running process, not a cutover to
  the updated code or a schema compatibility check of the future process.
- API PID 1538, worker PID 1534 and monitor PID 742 remained active; none was
  restarted by this task. No frontend artifact was copied to the live web root.

Two existing Starlette/httpx and AnyIO deprecation warnings remain in focused
backend tests. No comprehensive backend or frontend regression was repeated.
The previously verified 1.2.2 frontend lockfile/security correction is unchanged.

Evidence: `/tmp/rhu-main-focused-backend.log`, `/tmp/rhu-main-api-immutability.log`,
`/tmp/rhu-main-focused-frontend.log`, `/tmp/rhu-main-build.log`.
Temporary logs should be archived privately if required; no dumps, private assets,
credentials or generated test artifacts are included in the commit.

## Cutover remains separate

No development test blocker remains. The new code must **not** be started against
the old active schema. Final operator authorization must cover this coordinated
sequence (the more detailed recovery rules remain in the readiness report):

1. Confirm maintenance window, exact main/build artifact, recovery owner and actual
   writer inventory, including background worker, manual clients and scheduled jobs.
2. Exclude/drain active application writers and prevent unintended restarts. Keep
   Fabric peers, channels, volumes, certificates, wallets and keys intact.
3. Take a fresh protected database plus report/private-file recovery set at the
   fenced point. The earlier lightweight snapshot and synthetic restore evidence
   do not replace a current consistent cutover backup.
4. With identity `rhu_labchain` and baseline confirmed, acknowledge the actual
   writer fence and apply `20261015_01`, verify seven rows/history, then apply
   `20261018_01`, verify NULL legacy snapshots and unchanged PDF hashes.
5. Only after schema verification, restart/update the application and deploy the
   matching built frontend as one cutover. Verify auth/MFA/RBAC, generated codes,
   activation, dashboard, report/PDF behavior and outbox state before resuming
   background writers and opening normal access. Any synthetic mutating live
   smoke check must be deliberately authorized and audited.
6. On partial DDL, preserve evidence and inspect state; no blind retry/stamp/reset.
   Before new writes, an approved coordinated database/file/code restore may be
   used. After new identifiers/reports/outbox activity, prefer forward repair and
   reconcile ledger references; MySQL restoration cannot undo blockchain history.

Clinical starter entries stay inactive until facility approval. No existing active
record, infrastructure identity or encryption key was replaced. No active rebuild,
active migration, frontend deployment or service restart is authorized by this
validation record alone.
