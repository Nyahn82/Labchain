# Automatic-code MySQL integration probe

This standalone harness prepares native MySQL/InnoDB checks for `CodeSequence`
and `allocate_code()`. Preparation and offline validation do not connect to MySQL.
Database provisioning and permission to run the integration checks are separate
steps. No application migrations are applied by this harness.

## Runtime isolation contract

The only accepted target is TCP `127.0.0.1:3306`, database `rhu_labchain_dev`,
username `rhu_dev`. Host, database and username must be supplied explicitly using
`RHU_CODE_TEST_HOST`, `RHU_CODE_TEST_DATABASE` and `RHU_CODE_TEST_USER`.
`RHU_CODE_TEST_PORT` is optional but, if supplied, must be 3306. No generic
`DB_*` variables, `DATABASE_URL`, MySQL defaults files or `.env` files are read.
The harness does not import `app.database` or the application configuration.

Supply the password through the private terminal prompt, or inject
`RHU_CODE_TEST_PASSWORD` using a secure runtime environment. Never put a password
in source, command arguments or shell history. The prompt requires a terminal
and refuses a fallback that cannot suppress echo. Passwords are excluded from
configuration representations; driver exception details and SQL parameters are
not printed.

A connection hook verifies the selected database and both the authenticated
account and login username before test SQL runs. It sets a session-local lock
wait timeout. SQLAlchemy uses `REPEATABLE READ`; the real allocator issues its
normal `SELECT ... FOR UPDATE`. The harness does not change server configuration,
users or privileges.

Only these tables may be created, seeded, updated, deleted from or dropped:

- `code_sequence`: a clone of the actual model's DDL, used by the original ORM.
- `auto_code_probe_record`: synthetic records with a database unique code constraint.
- `auto_code_probe_legacy`: synthetic historical identifiers for format scanning.

All three must be absent before a run. If any exists, execution refuses before
creating or modifying tables. This also means a migrated development database
with an existing `code_sequence` table is unsuitable without a separate reviewed
setup decision; do not delete that table merely to bypass the guard.

A database advisory lock prevents simultaneous harness runs. Every created table
receives a random ownership comment. Cleanup and fixture resets verify the
allowlist, this run's ownership marker and InnoDB engine. Cleanup drops only
tables successfully created by this run; unrelated tables are never truncated,
dropped or used as fixtures. An interrupted run may leave its own tables behind;
the next run refuses to reuse them. Investigate leftovers separately rather than
automatically deleting them. The database account must already have the required
SELECT, INSERT, UPDATE, DELETE, CREATE and DROP permissions on the three allowed
tables. The harness grants nothing. Allow at least 21 simultaneous client
connections: 20 workers plus the connection holding the advisory lock.

## Checks prepared

1. Sequential identifiers and committed counters observed from fresh sessions.
2. Twenty synchronized allocations on twenty distinct MySQL connections, checking
   exact unique identifiers, committed counter and record count.
3. Explicit rollback of a flushed increment, then reuse of the number.
4. A real unique-constraint collision rolling back the counter and inserted record.
5. Independent Patient and Staff counters.
6. Missing-sequence failure without changing persisted state.
7. Last available BIGINT counter value for Department, plus the last fitting
   Patient/Staff codes; subsequent allocations fail without consuming a value.
8. All seven migration prefixes and padding formats, case-insensitive historical
   matches, ignored nonmatching codes, retained legacy rows, continuation from
   the existing maximum and rejection of an out-of-range suffix.
9. Atomic counter and synthetic-record commit, rollback and recovery.
10. Repeated allocations in a single transaction with `autoflush=False` and no
    intermediate flush, to prevent regression of the allocator refresh defect.

The migration check calls only `existing_maximum()` against the synthetic legacy
table. It does **not** run Alembic, `upgrade()` or `downgrade()`, or test an entire
schema migration. These are native MySQL tests, not SQLite simulations.

The revised scanner now checks effective column collation metadata and uses
server comparisons for noncanonical numeric forms. The earlier ten passing
probe checks do not certify these later preflight changes. Follow the separate
[migration safety and rehearsal plan](AUTO_CODE_MIGRATION.md); do not execute a
live migration or rerun the native probe without separate authorization.

## Offline validation

From the development worktree:

```bash
cd /home/rhuadmin/rhu-labchain-dev
.venv/bin/python -m py_compile scripts/mysql_auto_code_probe.py tests/test_mysql_auto_code_probe_safety.py
.venv/bin/python -m pytest tests/test_mysql_auto_code_probe_safety.py -q -ra
.venv/bin/python -m scripts.mysql_auto_code_probe
git diff --check
```

The default command exits successfully with `SKIP`, even if credentials happen
to be configured. `--check` validates supplied configuration without creating an
engine or connecting. `--run` with missing or invalid settings refuses before
engine creation. Offline tests install an engine-creation tripwire and exercise
these paths plus ownership rules; the existing `tests/conftest.py` network guards
remain unchanged. Ordinary pytest collection never runs the online harness.

## Execute later, only after provisioning and authorization

Use this exact command from an interactive terminal after the isolated database
and restricted account have been prepared and the integration run is authorized:

```bash
cd /home/rhuadmin/rhu-labchain-dev
RHU_CODE_TEST_HOST=127.0.0.1 \
RHU_CODE_TEST_DATABASE=rhu_labchain_dev \
RHU_CODE_TEST_USER=rhu_dev \
.venv/bin/python -m scripts.mysql_auto_code_probe --run --prompt-password
```

The password is requested privately. If `RHU_CODE_TEST_PASSWORD` is already set,
it is used instead. Replace `--run` with `--check` for configuration-only validation.
There is no CLI override for a different database, user, host or port. Exit codes:
0 for passing checks or a default skip, 1 for test/runtime failures, 2 for safety
refusal. Failures identify the check and exception class without printing driver
messages that might contain sensitive data. Cleanup is attempted after test
failures, and cleanup failures make the command fail.

## Allocator safeguards

The original allocator combined `populate_existing=True` with an unflushed
counter update. The reported native MySQL run passed nine checks but failed
repeated allocations with `autoflush=False`; offline regressions reproduced the
same counter reuse. The allocator now disables autoflush for its locking query
and flushes only the selected sequence after incrementing it, within the caller's
transaction. No commit occurs and unrelated pending changes remain unflushed.
The final integration regression retains its original expectations and performs
no caller-side flush. The MySQL probe must be rerun manually to validate the fix
under native concurrency; offline tests do not establish MySQL locking behavior.

Identifier capacities are derived from the destination SQLAlchemy columns. The
models and migration DDL agree on these lengths; no live schema inspection is
performed by offline validation. With the configured three-character prefixes,
the maximum is `min(9223372036854775807, 10 ** (column_length - 4) - 1)`:

| Resource | Column length | Maximum counter |
| --- | ---: | ---: |
| Patient | 20 | 9,999,999,999,999,999 |
| Staff | 20 | 9,999,999,999,999,999 |
| Department | 30 | 9,223,372,036,854,775,807 |
| Test | 30 | 9,223,372,036,854,775,807 |
| Panel | 30 | 9,223,372,036,854,775,807 |
| Rejection Reason | 40 | 9,223,372,036,854,775,807 |
| Report Template | 40 | 9,223,372,036,854,775,807 |

The allocator checks the complete candidate string, including its actual prefix,
hyphen and padding, before modifying the counter or timestamp. This also guards
against a changed prefix or excessive padding. Missing destination mappings are
refused rather than bypassing validation. Capacity failures raise `RuntimeError`
with the sequence and destination-column capacity; the existing BIGINT exhaustion
error remains unchanged. No column definitions or migrations were changed.

The native exhaustion check now exercises the BIGINT limit with Department and
the 20-character limits with Patient/Staff. The other probe expectations and
owned-table cleanup rules are unchanged. Rerun the native probe manually after
these allocator changes; offline tests cannot verify InnoDB locking behavior.
