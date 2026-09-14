# Phase 2A database foundation

Phase 2A adds SQLAlchemy 2.x declarative models and one explicit Alembic revision,
`20260914_01` (initial revision; no parent). It remains a FastAPI modular monolith.
There are no login endpoints, seeded users, credentials, or later-phase tables.

## Schema source

The authoritative workbook supplied in this checkout is
[`reference/RHU_LabChain_Improved_3NF_Normalization(1).xlsx`](reference/RHU_LabChain_Improved_3NF_Normalization%281%29.xlsx).
The brief names the same workbook without `(1)`; the available file was inspected
and its twelve Phase 2A definitions agree with the requested schema. The workbook
was already present and untracked; it has not been renamed or modified.

Models live in `app/models/identity.py` and `app/models/auth.py`, using the shared
`Base` in `app/models/base.py`. Importing `app.models` registers all twelve tables
without loading database settings or creating any tables.

## Tables and relationships

The migration creates these application tables in dependency order:

| Table | Purpose / relationship |
| --- | --- |
| `facility_profile` | Issuing facility master record; no Phase 2A foreign keys |
| `patient` | Patient identity, unique `patient_code`; age derived from `birth_date` |
| `permission` | Permission catalog, unique `permission_code` |
| `referring_facility` | Referring clinic/facility master records |
| `role` | Role catalog, unique `role_code` |
| `staff` | Staff identity, unique `staff_code`; job position separate from RBAC |
| `user_account` | Unique username, `password_hash`, account status and login timestamps |
| `patient_account_link` | PK/FK `patient_id`; unique FK `user_id` makes the link one-to-one |
| `requesting_physician` | Optional FK to `referring_facility` |
| `role_permission` | Role/permission bridge with unique `(role_id, permission_id)` |
| `staff_account_link` | PK/FK `staff_id`; unique FK `user_id` makes the link one-to-one |
| `user_role` | Unique `(user_id, role_id)`; nullable `assigned_by` references the assigning account |

Alembic also maintains its own `alembic_version` bookkeeping table. It is not an
additional application model. Downgrade drops the twelve application tables in
reverse creation order; table drops remove their indexes and constraints together.

All application IDs use signed `BIGINT`, with auto increment on the ten surrogate
primary keys. Link primary keys use existing patient/staff IDs and do not auto
increment. MySQL tables use InnoDB and `utf8mb4`; collation follows MySQL's default
for that character set, including its username/code comparison behavior.

`patient.sex` and `user_account.account_status` compile to native MySQL ENUMs with
exactly the values in the brief. Required `created_at` columns default to
`CURRENT_TIMESTAMP`; `is_active` defaults to `1`. Nullable `updated_at` fields are
not automatically updated. `account_status` and `user_role.assigned_at` must be
supplied explicitly; no unspecified defaults have been added.

Primary keys, foreign keys and unique constraints have deterministic names. Unique
constraints provide indexes for codes, usernames, account links and bridge pairs.
Additional indexes support physician facility lookup, user-role role/assigner
lookup, and role-permission permission lookup. The patient `(last_name, first_name)`
index follows the workbook's explicit note. Foreign-key columns already covered by
a primary key or the leading column of a unique key do not get redundant indexes.

No cascading delete/update rules are introduced: referenced rows remain protected
by MySQL's default foreign-key behavior. One account may have both a staff link and
a patient link; uniqueness is enforced within each link table as specified by the
workbook. Cross-table exclusivity is not part of this schema. No passwords or
password hashes are stored in `patient` or `staff`.

## Existing configuration integration

`migrations/env.py` imports `database_url` and `engine` from `app.database`, and
`Base.metadata` from `app.models`. Online Alembic commands use that existing
engine, retaining its driver, timeouts, and connection settings. Offline commands
use the existing SQLAlchemy URL object without opening a connection.

`app.database` continues to read `app.config.settings`: the existing project `.env`
and process environment variables are the only configuration source. There is no
second URL, credential file, root account, or URL in `alembic.ini`. The `.env`
remains ignored by Git. Model imports and FastAPI startup do not run migrations.

## Tests without production access

From the project directory after installing requirements:

```bash
.venv/bin/python -m pytest -q
```

Tests override every application setting with synthetic values and block network
connections before test collection. They check model imports and ORM mappings,
all twelve tables, keys, indexes, one-to-one links, password/age restrictions,
defaults, native MySQL DDL, and equality of frozen migration/model metadata.

The migration upgrade and downgrade are exercised on an in-memory SQLite database
with foreign keys enabled and synthetic explicit IDs. Duplicate links and bridge
pairs, invalid foreign keys, and deletion of an assigning account are rejected.
SQLite does not validate MySQL-native ENUM or BIGINT auto increment behavior; those
are checked by compiling the migration with the MySQL dialect. No live MySQL
migration is performed by the tests.

FastAPI import and health-route registration are checked, along with health and
readiness handler behavior using mocked database connections.

## Hostinger commands

**Production safety:** Implementation and tests do not apply this migration to the
Hostinger database. Only run the online upgrade below deliberately, after reviewing
the generated SQL and taking a restorable database backup/snapshot. Confirm the
existing configuration targets `rhu_labchain` as `rhu_app`, with no unexpected
process environment overrides. Do not use MySQL root, print credentials, overwrite
`.env`, or change service/network configuration.

Ensure the reviewed Phase 2A files are present on Hostinger. Run as `rhuadmin`,
from the existing repository, one command at a time; stop if any command fails:

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m alembic heads
.venv/bin/python -m alembic history --verbose
.venv/bin/python -m alembic upgrade 20260914_01 --sql > /tmp/rhu-phase2a-upgrade.sql
less /tmp/rhu-phase2a-upgrade.sql
```

`heads` and `history` read revision files. The `--sql` command only renders SQL.
The expected single head is `20260914_01`.

Inspect the database revision state (this connects using the application account):

```bash
.venv/bin/python -m alembic current --verbose
```

An initial empty database has no current revision. If an unexpected revision or
application tables already exist, stop and reconcile that state before applying
this initial revision. Do not use `stamp` to bypass an unapplied migration.

After reviewing the SQL and taking the backup, apply exactly Phase 2A:

```bash
.venv/bin/python -m alembic upgrade 20260914_01
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic heads
.venv/bin/python -m alembic check
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/ready
```

The current revision should equal head (`20260914_01`); `alembic check` should
report no pending upgrade operations. `alembic upgrade head` is equivalent while
this is the only head. The exact revision command above avoids accidentally
applying later phases if additional revisions are subsequently added.

MySQL DDL is not transactionally rolled back as a unit. A failed upgrade can leave
some tables created before Alembic records the revision. Stop on failure, inspect
the schema and error, and reconcile or restore from backup before retrying. The
application account needs the DDL permissions required by Alembic; resolve missing
permissions separately rather than changing the migration to use root.

No service restart, port change, or Nginx/systemd/UFW/Certbot edit is required for
this schema-only phase.

## Downgrade (destructive; optional rollback only)

**This deletes all data in the twelve Phase 2A tables.** Preserve a restorable
backup first. Do not run downgrade as part of normal deployment. These commands
apply when current revision is `20260914_01` and no later revision depends on it.

Preview without a database connection:

```bash
.venv/bin/python -m alembic downgrade 20260914_01:base --sql > /tmp/rhu-phase2a-downgrade.sql
less /tmp/rhu-phase2a-downgrade.sql
```

Only if deliberately rolling back Phase 2A:

```bash
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic downgrade base
.venv/bin/python -m alembic current --verbose
```

After downgrade, no revision is applied. Alembic retains its empty
`alembic_version` bookkeeping table.

## Review notes

- Reference filename differs from the brief only by the supplied `(1)` suffix.
- No live MySQL upgrade/downgrade has been run. Rehearsal on a disposable MySQL 8
  database remains the deployment validation step for actual server behavior.
- Database uniqueness follows the server's character-set default collation. A
  different case/accent sensitivity policy would require an explicit decision.
- Phase 2A provides database storage only; login flows, password hashing services,
  RBAC enforcement, seed accounts, and all later phases remain future work.
