# Isolated native MySQL migration rehearsal and read-only verification

This harness rehearses the **complete real Alembic upgrade**, unlike the allocator
probe. Preparation/offline tests do not open a connection or execute a migration.
Native execution is separately authorized. See the Step 29C.6 diagnosis below for
the user-reported run and the distinction between migration and rehearsal completion.

## Preconditions and authorization

Only TCP `127.0.0.1:3306`, database `rhu_labchain_dev`, account `rhu_dev` are
accepted. For the mutating rehearsal harness, the database must already exist and be **empty**. Existing probe tables,
application tables, views, an Alembic version table, routines, events, and a prior
rehearsal marker all cause refusal. No reset, reuse, automatic DROP/TRUNCATE,
provisioning, grant changes, sudo, or global configuration changes are provided.
An existing `alembic_version` is read before refusal; it is never stamped.

The operator must authorize creation of the complete synthetic application schema
in that empty database. This includes empty synthetic audit/report/blockchain
metadata tables, but never accesses Fabric, real identities, reports or records.
Use native MySQL 8.0.16+ (not MariaDB), enforced CHECK constraints and InnoDB.
The restricted account needs the normal DDL/DML permissions for these historical
migrations **only on `rhu_labchain_dev`**, including indexes, foreign keys and
ALTER, and access to its information_schema metadata. Do not grant global or
production permissions merely to make the rehearsal pass. Account creation and
privilege changes require separate approval; this script does neither.

Before execution, reserve the development database exclusively. Ensure no
application, worker, CLI, import, probe, scheduled task or independent client can
write to it for the entire run. Do not touch production services to achieve this.
Coordinate access with anyone who has credentials. The harness rejects other
visible development sessions and takes an advisory GET_LOCK, but neither is a
complete writer fence: process visibility can be restricted, privileged sessions
can be hidden and uncooperative writers do not honor advisory locks. If exclusive
access cannot be established, **do not run**.

The exact migration acknowledgment is
`RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED=1`. Both `--writers-stopped` and
`--authorize-empty-database` are also required with `--run`. These are explicit
operator acknowledgments, **not mechanisms that stop writers**. They are checked
again in the online entry point, before engine creation. Run only from
`/home/rhuadmin/rhu-labchain-dev` on `major-update-v1`, with no `.env` file.

## Isolation and credentials

The harness shares only the allocator probe's offline configuration parser:
`RHU_CODE_TEST_HOST`, `RHU_CODE_TEST_PORT`, `RHU_CODE_TEST_DATABASE`,
`RHU_CODE_TEST_USER`, and optionally `RHU_CODE_TEST_PASSWORD`. Generic application
variables, DATABASE_URL, .env and MySQL defaults files are not read. Prefer the
interactive, echo-disabled password prompt; insecure/nonterminal fallback refuses.
Do not put a password in command arguments, source, history or this document.

Before any schema mutation the harness checks `DATABASE()`, `CURRENT_USER()`,
`USER()`, `@@port`, and server version. Both authenticated account and client
identity must be `rhu_dev@localhost` or `rhu_dev@127.0.0.1`; wildcard-account
matches are refused. No alternate hosts, ports, sockets or URLs are accepted.
SQL echo is disabled and bound parameters are hidden. Errors print fixed stage/substage labels, exception category, structured numeric
MySQL error number, validated SQLSTATE when available, and last observed revision
state. They never print exception messages, SQL, parameters or identifiers. A
failure during upgrade is reported as unknown until a revision is actually read;
the diagnostic path never makes a recovery connection to guess the outcome. Do not enable SQL debug logging.

The normal `migrations/env.py` imports `app.database`, so it is deliberately not
used. A private temporary directory inside the development worktree receives a
connection-only env.py and **byte-for-byte copies** of the real revision files.
The pinned, linear ten-revision chain and its head/parent are checked before DDL;
a source SHA256 is printed for reproducibility. An Alembic Config created without
an ini file receives only the already-verified connection and model metadata.
No production/application engine or configuration is imported.

## Scenario isolation and owned tables

The first operation after the empty-schema guard and chain check creates
`auto_code_rehearsal_run`, containing a random run ID and scenario name. The run
ID is printed for evidence. Real historical upgrades then build revision
`20261005_01` from base. No dumps or metadata.create_all substitutions are used.

The owned inventory is the 52 current application model tables (51 before the
new migration), `alembic_version`, and `auto_code_rehearsal_run`: 53 tables at the
parent and 54 after CREATE code_sequence. The baseline inventory is checked
exactly against model metadata and every table must use InnoDB. Table names are:

```
attachment audit_log auth_session blockchain_event blockchain_node
blockchain_sync_log blockchain_verification_log code_sequence email_log
facility_profile lab_department lab_order lab_order_item lab_payment lab_report
lab_result_item login_log mfa_challenge mfa_recovery_code order_panel
panel_section panel_test patient patient_account_link patient_activation_token
permission print_log reference_range referring_facility rejection_reason
report_patient_snapshot report_result_item report_signatory report_template
report_verification requesting_physician role role_permission sample_type
signatory specimen specimen_order_item specimen_rejection staff
staff_account_link test_catalog test_interpretation_rule test_panel
test_sample_type user_account user_role user_totp_mfa
alembic_version auto_code_rehearsal_run
```

All belong to the initially empty, exclusively reserved development database.
The script never deletes tables on completion or failure. Every later invocation
of the mutating harness against this populated database refuses; it does not infer permission to reuse
objects merely from a familiar name or marker.

Each run first tests pre-DDL refusals using transactional synthetic inserts;
those test inserts are rolled back between cases. MySQL AUTO_INCREMENT gaps
from rolled-back fixtures are acceptable; no patient/code data is rewritten.
Post-DDL failure modes require their **own empty instance of the same fixed
logical database**. They cannot run consecutively on the populated result of a
success run. Review and separately authorize preservation/reset/reprovisioning
of synthetic-only state before another run. This harness intentionally provides
no cleanup command. It never substitutes a second database or expands privileges.

## Native scenarios

Every mode performs:

1. Real base-to-parent migrations, exact inventory and InnoDB checks.
2. Multiple synthetic historical rows in all seven source tables; real foreign
   keys and unique indexes remain intact. Test catalog uses the actual inserted
   department ID.
3. Explicit per-column overrides alternating `utf8mb4_unicode_ci` (PAD SPACE)
   and `utf8mb4_0900_ai_ci` (NO PAD). Real server comparisons verify lowercase,
   accent equivalence and trailing-space behavior. Unpadded numeric and ordinary
   custom identifiers are included. Expected counters are independently fixed:
   31 for PAD SPACE columns and 23 for NO PAD columns.
4. A fullwidth-digit ambiguous Patient code must refuse the **actual upgrade**
   before DDL. A SQL event guard forbids any writes during the refused upgrade.
5. A Rejection Reason above signed BIGINT capacity must likewise refuse.
   Each refusal checks the old Alembic revision, absence of code_sequence and
   byte-preserved historical code spellings using HEX, then rolls back only its
   synthetic fixture insertion.

`--scenario success` then runs the actual parent-to-head upgrade and verifies:

- Exactly seven correct `(key, prefix, padding, counter)` rows and head revision.
- Historical identifiers byte-for-byte unchanged and original source-table indexes preserved.
- Exact CHECK names `ck_code_sequence_nonnegative_value` and
  `ck_code_sequence_valid_padding`; invalid negative counter and padding 0/17
  updates must raise MySQL CHECK error 3819 and roll back through savepoints.
  SQLAlchemy DBAPI errors are accepted only for that precise number: the installed
  PyMySQL driver maps 3819 to OperationalError. Other errors still propagate.
- First allocation for every sequence uses the expected next code and commits.
- A second normal Alembic upgrade to head leaves all sequence fields, historical
  identifiers and head revision unchanged; it must not reseed counters.

`--scenario seed-failure` injects an exception immediately before seed INSERT,
**after real CREATE TABLE**. `--scenario revision-failure` injects immediately
before the actual Alembic version UPDATE, after seed DML. Each must propagate the
injected failure, retain the created sequence table, roll back seed rows, retain
the parent revision and preserve history. Only those expected observations yield
`PASS intentional_post_ddl_failure`. A mismatch fails and leaves all evidence.
This successful *test* result is deliberately **not a successful migration**.

Coverage is scoped to the two named collations and synthetic fixtures. It does
not certify every supported collation, the production schema, arbitrary Unicode,
privilege configuration, writer fencing or deployment readiness. Before deployment,
rehearse any additional effective collations identified by an authorized schema
review, and the broader cases in [the migration runbook](AUTO_CODE_MIGRATION.md).
Do not change production collations to match these fixtures.

## Proposed manual commands — only after separate authorization

Offline preparation checks (no credentials required, no connection/migrations):

```bash
cd /home/rhuadmin/rhu-labchain-dev
.venv/bin/python -m scripts.mysql_migration_rehearsal
.venv/bin/python -m pytest tests/test_mysql_migration_rehearsal_safety.py tests/test_mysql_auto_code_probe_safety.py -q -ra --tb=short
```

Configuration check only, in an interactive VS Code terminal:

```bash
cd /home/rhuadmin/rhu-labchain-dev
RHU_CODE_TEST_HOST=127.0.0.1 RHU_CODE_TEST_PORT=3306 \
RHU_CODE_TEST_DATABASE=rhu_labchain_dev RHU_CODE_TEST_USER=rhu_dev \
.venv/bin/python -m scripts.mysql_migration_rehearsal --check --prompt-password
```

Once the operator has approved schema creation, verified the database is empty
and established exclusive access, the proposed native success command is:

```bash
cd /home/rhuadmin/rhu-labchain-dev
RHU_CODE_TEST_HOST=127.0.0.1 RHU_CODE_TEST_PORT=3306 \
RHU_CODE_TEST_DATABASE=rhu_labchain_dev RHU_CODE_TEST_USER=rhu_dev \
RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED=1 \
.venv/bin/python -m scripts.mysql_migration_rehearsal \
  --run --authorize-empty-database --writers-stopped --prompt-password \
  --scenario success
```

For each separately approved, freshly empty database incarnation, use that exact
command replacing `--scenario success` with `--scenario seed-failure` or
`--scenario revision-failure`. Never run all three sequentially without the
separately reviewed reset. If RHU_CODE_TEST_PASSWORD is already present, the
secure runtime value is used instead of prompting; no password is printed.

## Recovery and remaining approvals

On any unexpected error, interruption, or deliberate post-DDL failure:

1. Keep development writers excluded. Preserve run ID, source hash, stage output
   and database state. Do not assume rollback removed MySQL DDL.
2. In a separately authorized read-only inspection, check the marker, table
   inventory, Alembic revision, sequence rows, CHECK definitions and synthetic
   history. The script itself does not retry, stamp, downgrade or repair.
3. Parent revision plus an existing code_sequence is **partial migration state**.
   Do not stamp head, manually zero counters, drop the sequence table or retry
   the normal migration to bypass the error. Investigate whether any rows or
   allocations committed before deciding a recovery plan.
4. Only after confirming this was an isolated synthetic run and preserving its
   evidence may an operator approve disposal/reprovisioning of the dedicated
   development database. Any unrelated data blocks such a reset. Provisioning
   and reset commands are deliberately outside this harness and this task.
5. Re-run a complete scenario only against a verified empty incarnation.
   Recovery for any real application database needs its own reviewed backup/
   forward-repair plan; these synthetic observations do not authorize it.

No native run, provisioning, reset, privilege change or deployment is authorized
by preparation. Do not execute ordinary `alembic upgrade` for this rehearsal:
that would load the application's normal configuration.


## Step 29C.6 diagnosis: migration reached head, rehearsal stopped

The user reported head `20261015_01`, seven correctly seeded counters and both
correctly named CHECK constraints after an `OperationalError` at `STAGE success`.
This investigation made **no database connections or migration executions**.
These database observations are user-supplied, not independently re-read here.

The installed PyMySQL 1.2.0 error map has no explicit entry for 3819. Its packet
parser therefore raises `pymysql.err.OperationalError(3819, ..., sqlstate='HY000')`.
SQLAlchemy wraps it as OperationalError. An offline synthetic MySQL error packet
reproduced that exact classification, without any socket or engine. The former
constraint loop caught only IntegrityError, so a correctly enforced CHECK could
abort the rehearsal rather than count as a successful validation.

The most likely failing operation is the **first negative-counter CHECK test**,
`UPDATE code_sequence SET current_value=-1 WHERE sequence_key='PATIENT'`, after
the actual migration committed. The old redacted log lacks errno/substage, so this
is a strongly supported diagnosis, not proof of which native statement failed.
A metadata permission error, UPDATE permission error, connection failure, or an
allocation error before its transaction committed can also leave seeded counters.
A migration failure is not established by the aggregate REHEARSAL_FAILED label.

The harness now catches DBAPIError only when its original native number is 3819;
it preserves savepoint rollback and still fails if the CHECK is not enforced.
Access-denied, deadlock, disconnect, duplicate-key and other database errors are
not suppressed. Application services and the Alembic migration are unchanged.

### Execution order after STAGE success

| Phase | Operations | Interpretation of observed state |
| --- | --- | --- |
| Before upgrade | Read historical HEX snapshots and source-table indexes, roll back read transaction | These do not advance the revision. |
| Actual upgrade | Scan all seven code columns, CREATE code_sequence, insert seven seeds, Alembic version UPDATE and commit | The reported head and seed rows support completion of this phase. |
| Sequence verification | Roll back read state, read revision, historical spellings, table presence, indexes, seven counters and CHECK names | Metadata/connection errors here are possible; wrong values would raise AssertionError instead. |
| Constraint validation | Three savepoint-protected invalid UPDATEs: negative counter, padding 0, padding 17 | First 3819 is the most likely source of the uncaught OperationalError. |
| Allocation | Allocate once for each resource using an autoflush-disabled session; commit all seven together | Successful completion would change counters to 32/24/32/24/32/24/32. Observed seed values show no committed allocation batch. |
| Repeat upgrade | Snapshot counters, normal no-op upgrade to head, verify counters/history/revision | Not established by the old log; normally follows committed allocations. |
| Cleanup | Final read rollback, remove local temporary Alembic files, close connection and dispose engine | No table deletion. These later failures would normally leave incremented counters. |

`REHEARSAL_PASS` is now emitted only after connection and engine cleanup succeeds.
Substages identify the operation being attempted. Revision diagnostics report the
last actual observation; no exception handler attempts a reconnect, migration or
repair. SQLSTATE is `unavailable` when the driver exposes no valid structured
field; messages are never parsed to reconstruct it.

### Observed counters and marker meaning

| Sequence | Effective column collation | Correct seed / reported value |
| --- | --- | --- |
| PATIENT | utf8mb4_unicode_ci / PAD SPACE | 31 |
| STAFF | utf8mb4_0900_ai_ci / NO PAD | 23 |
| DEPARTMENT | utf8mb4_unicode_ci / PAD SPACE | 31 |
| TEST | utf8mb4_0900_ai_ci / NO PAD | 23 |
| PANEL | utf8mb4_unicode_ci / PAD SPACE | 31 |
| REJECTION_REASON | utf8mb4_0900_ai_ci / NO PAD | 23 |
| REPORT_TEMPLATE | utf8mb4_unicode_ci / PAD SPACE | 31 |

The six fixtures per resource include canonical 7, lowercase 11, unpadded 17,
a custom identifier, equivalent prefix spelling with suffix 23, and a numeric
31 spelling with a trailing space. PAD SPACE reserves 31; NO PAD leaves that
trailing-space spelling distinct and reserves 23. All reported seed values match.

`auto_code_rehearsal_run` is inserted and committed **before the parent schema is
built**. It has only run_id and scenario fields, and is never updated at later
stages. A row whose scenario is `success` identifies the *requested scenario*;
it is initialization evidence, not progress or completion evidence.

## Prepared read-only inspection of the existing database

Use `scripts/mysql_migration_verify.py` only after separate authorization. Default
invocation skips without a connection. This is distinct from rerunning the
success scenario and does not invoke Alembic, allocation, invalid UPDATEs,
CREATE, repair, stamping, locking reads, temp tables, COMMIT or cleanup DDL.

It retains the exact loopback/database/account/worktree checks. Before reading
synthetic records it enables and verifies a server read-only session and checks
the authenticated account and its grants. A driver-level **exact SQL allowlist**
permits only the fixed verification SELECTs, SHOW GRANTS and the read-only session
setting. Rollback and close are the only transaction endings. No raw fixtures,
grants, SQL, parameters, passwords or run IDs are printed by the verifier.

To meet the no-mutation-privileges requirement, it **refuses** unless the fixed
`rhu_dev` account has only schema-scoped SELECT (and optional USAGE), no broader
scope, no grant option, and no active or granted roles. A write-capable rehearsal
account will therefore refuse this verification mode. Do not revoke/regrant
privileges automatically or change accounts to bypass isolation. An operator
must separately approve any necessary restriction of the isolated account's
privileges, coordinating other development users. No privilege changes are part
of this investigation, and no assumption is made about the account's current
grants. No new database incarnation is needed for these read-only checks.

The verifier checks the exact InnoDB inventory, initialization marker, head,
seven seed values (or the uniformly incremented state from a completed allocation
batch), exact synthetic code spellings, expected column collations, single-column
unique indexes, CHECK expressions and ENFORCED metadata. Unexpected or mixed state
fails without repair. `READ_ONLY_STATE_VERIFIED` does **not** claim a completed
rehearsal or prove earlier state transitions, live CHECK rejection, allocation
atomicity, concurrency, or repeat-upgrade behavior. Those require a separately
reviewed focused validation plan; do not rerun the original success scenario on
this populated database. Preserve the database and current evidence.

Proposed command, **not executed**, once read-only access and inspection have
been separately authorized:

```bash
cd /home/rhuadmin/rhu-labchain-dev
RHU_CODE_TEST_HOST=127.0.0.1 RHU_CODE_TEST_PORT=3306 \
RHU_CODE_TEST_DATABASE=rhu_labchain_dev RHU_CODE_TEST_USER=rhu_dev \
.venv/bin/python -m scripts.mysql_migration_verify \
  --verify-read-only --authorize-existing-synthetic --prompt-password
```

No writer-acknowledgment flag is required for SELECT-only inspection. Coordinate
with the database owner to keep the synthetic state stable while inspecting it;
read-only permissions do not stop other sessions from writing.

If later testing requires a complete fresh run or intentional post-DDL failure,
first preserve this evidence and separately authorize disposal/reprovisioning of
the synthetic-only database. No reset, privilege-management or recovery commands
are provided or executed here.
