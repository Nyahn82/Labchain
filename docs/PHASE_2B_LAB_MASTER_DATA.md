# Phase 2B laboratory master data

Phase 2B adds nine laboratory setup tables to the existing FastAPI modular
monolith. Models are in `app/models/laboratory.py` and registered by
`app/models/__init__.py`, using the existing `app.models.base.Base`.
Importing models registers metadata without loading database settings, connecting
to MySQL, or creating tables. Production schema creation uses Alembic only.

The authoritative workbook available in this repository is
[`reference/RHU_LabChain_Improved_3NF_Normalization(1).xlsx`](reference/RHU_LabChain_Improved_3NF_Normalization%281%29.xlsx).
Its nine relevant sheets and implementation notes were inspected before coding;
they match the brief. The filename differs from the brief by the `(1)` suffix.
The workbook and the Phase 2A models/migration are unchanged.

## Tables and relationships

| Table | Purpose and foreign keys |
| --- | --- |
| `lab_department` | Department setup; unique `department_code` |
| `sample_type` | Accepted sample categories; unique `sample_name` |
| `test_catalog` | Individual tests; unique `test_code`; required `department_id` references `lab_department.department_id` |
| `test_sample_type` | Many-to-many bridge: `test_id` references `test_catalog.test_id`, `sample_type_id` references `sample_type.sample_type_id`; unique pair |
| `test_panel` | Named test group; unique `panel_code`; optional `department_id` references `lab_department.department_id` |
| `panel_section` | Ordered subsection within a panel; required `panel_id` references `test_panel.panel_id` |
| `panel_test` | Ordered membership of tests in panels; `panel_id` references `test_panel.panel_id`, `test_id` references `test_catalog.test_id`, optional `section_id` references `panel_section.section_id`; unique `(panel_id, test_id)` |
| `reference_range` | Sex, age and date dependent ranges; required `test_id` references `test_catalog.test_id` |
| `test_interpretation_rule` | Approved general explanations by flag; required `test_id` references `test_catalog.test_id`; unique `(test_id, flag)` |

`test_sample_type` allows a test to accept multiple sample types and each sample
type to support multiple tests. `is_default` records a choice explicitly. No
constraint requiring exactly one default per test is inferred from examples.
This is sample-type setup, not storage of collected specimens.

`test_panel` groups tests, `panel_section` defines optional printable subsection
headings, and `panel_test` specifies membership, sort order and whether each test
is required. A test may belong to multiple panels, once per panel. Section names
and sort orders are not assumed unique. No rendering or reporting is implemented.

### Same-panel integrity

The three workbook-defined `panel_test` foreign keys are retained. An additional
composite foreign key enforces:

```text
panel_test(section_id, panel_id)
    -> panel_section(section_id, panel_id)
```

The parent has the supporting unique key `(section_id, panel_id)`. Because
`section_id` is already the primary key, this adds no business uniqueness
restriction and requires no extra column or denormalized value. It gives the
composite foreign key an explicit unique referenced key compatible with MySQL.

A null `section_id` permits an unsectioned panel member. A non-null section must
belong to the member's panel. The database rejects invalid inserts, changes to
either member foreign key, and reassignment of a referenced section to a different
panel. Default restrictive foreign-key behavior protects referenced rows; there
are no delete/update cascades. Future write services may add friendly validation,
but the database already enforces this invariant.

No ORM navigation relationships are added in this schema-only phase. Foreign keys
provide explicit joins without overlapping writable relationships or implicit
collection mutation behavior.

## Reference ranges and interpretation

**Reference ranges are selected by test, sex, age, and effective date.** One test
can have multiple ranges; ranges are intentionally separate from `test_catalog`.
Selection and result flag calculation remain future work.

- `sex` contains exactly `M`, `F`, `ANY`.
- `age_min` and `age_max` are nullable `DECIMAL(6,2)` values in years.
- Numeric normal and critical bounds are nullable `DECIMAL(12,3)` values, mapped
  as Python `Decimal` values; `unit` describes the range's unit.
- `qualitative_normal` stores the normal qualitative value for `TEXT` or `POS_NEG`
  tests. It is explanatory text for a nonnumeric result, not a numeric threshold.
- `effective_from` and `effective_to` are nullable dates. A null `effective_to`
  means open-ended validity; `is_active` marks active setup records.

Do not store patient age as a permanent patient value. Age is derived from
`PATIENT.birth_date` when needed. This phase adds no patient age field.
Selection precedence, overlapping ranges, missing birth dates, interval boundary
rules and sex applicability must be defined in the later selection service;
no speculative uniqueness or evaluation logic is introduced here.

`test_catalog.result_type` contains exactly `NUMERIC`, `TEXT`, `POS_NEG`.
`test_interpretation_rule.flag` contains exactly `NORMAL`, `LOW`, `HIGH`,
`CRITICAL_LOW`, `CRITICAL_HIGH`, `ABNORMAL`.

`interpretation_text`, `possible_causes`, and `recommendation` contain approved
**general explanatory information only**. They must not be treated as diagnoses,
prescriptions, or treatment plans. Storage does not approve content; controlled
content review belongs to the later master-data workflow. No automated diagnosis,
result flagging, or clinical recommendation engine is implemented.

## Constraints, indexes and defaults

All nine tables use signed `BIGINT` auto-increment primary keys, InnoDB and
`utf8mb4`, following Phase 2A. ENUM columns compile to native MySQL ENUMs with the
exact canonical values above. String comparison follows the server's default
collation for `utf8mb4`, consistent with Phase 2A.

There are nine primary keys, eleven foreign-key constraints (ten workbook FKs
plus the same-panel composite FK), eight unique constraints (seven workbook
constraints plus the supporting section/panel key), and seven explicit nonunique
indexes. Names follow the existing Base naming convention.

| Unique constraint | Columns |
| --- | --- |
| `uq_lab_department_department_code` | `lab_department(department_code)` |
| `uq_sample_type_sample_name` | `sample_type(sample_name)` |
| `uq_test_catalog_test_code` | `test_catalog(test_code)` |
| `uq_test_sample_type_test_id_sample_type_id` | `test_sample_type(test_id, sample_type_id)` |
| `uq_test_panel_panel_code` | `test_panel(panel_code)` |
| `uq_panel_section_section_id_panel_id` | `panel_section(section_id, panel_id)`; composite FK support |
| `uq_panel_test_panel_id_test_id` | `panel_test(panel_id, test_id)` |
| `uq_test_interpretation_rule_test_id_flag` | `test_interpretation_rule(test_id, flag)` |

| Explicit index | Columns |
| --- | --- |
| `ix_test_catalog_department_id` | `test_catalog(department_id)` |
| `ix_test_sample_type_sample_type_id` | `test_sample_type(sample_type_id)` |
| `ix_test_panel_department_id` | `test_panel(department_id)` |
| `ix_panel_section_panel_id` | `panel_section(panel_id)` |
| `ix_panel_test_section_id_panel_id` | `panel_test(section_id, panel_id)` |
| `ix_panel_test_test_id` | `panel_test(test_id)` |
| `ix_reference_range_test_id` | `reference_range(test_id)` |

Other FK lookup paths are covered by the leading columns of primary/unique keys.
Indexes and constraints are removed with their tables during downgrade, avoiding
attempts to drop FK-supporting indexes while constraints still use them.

All `is_active` columns have `NOT NULL DEFAULT 1`, deliberately following Phase
2A. `is_default` and `is_required` are required with no default; callers must
supply them. Sort orders and enum values also have no invented defaults.

## Migration and verification

- File: `migrations/versions/20260914_02_phase_2b_laboratory_master_data.py`
- Revision: `20260914_02`
- `down_revision`: `20260914_01`
- Logical name: `phase_2b_laboratory_master_data`

Upgrade creates the nine tables in the order shown above. Downgrade drops them
in reverse order, leaving all twelve Phase 2A application tables intact.
`alembic_version` remains Alembic's existing bookkeeping table. The migration
contains no seed data and imports no current application models.

Development verification:

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m alembic heads
.venv/bin/python -m alembic history --verbose
```

The baseline had 24 passing tests; the extended suite has 50. The existing strategy
is retained: metadata contracts, frozen migration/model comparison, offline MySQL
DDL, SQLite migration execution with synthetic IDs, and the real Alembic online
path using a substituted in-memory engine. Phase 2A-specific checks now select
Phase 2A tables/revision explicitly; the complete-history test covers the new head.

Tests block network access before application imports and use synthetic settings.
They cover exact table/column contracts, ENUMs, precision, defaults, FK indexes,
uniqueness, cross-panel insert/update rejection, valid null sections, protected
parents, empty tables after upgrade, and preservation of Phase 2A data after a
Phase 2B downgrade. Existing FastAPI import, health and readiness tests still pass.
No live MySQL migration has been executed. SQLite does not validate MySQL-native
ENUM enforcement or auto-increment behavior; those are checked through MySQL SQL
compilation. A disposable MySQL 8 rehearsal remains a deployment validation step.

## Hostinger deployment commands

These are operator instructions; they were **not executed against production**.
Use the existing checkout as `rhuadmin` after the reviewed Phase 2B files have
been delivered. There is no new dependency or frontend build. Run one command at
a time and stop on failure. Retain a restorable database backup before the online
upgrade, and confirm the existing configuration targets `rhu_labchain` with the
intended application account and no unexpected environment overrides.

Review the code and generated SQL:

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m alembic heads
.venv/bin/python -m alembic history --verbose
.venv/bin/python -m alembic upgrade 20260914_01:20260914_02 --sql > /tmp/rhu-phase2b-upgrade.sql
less /tmp/rhu-phase2b-upgrade.sql
.venv/bin/python -m alembic current --verbose
```

Expected code head: `20260914_02`. Expected database revision before deployment:
`20260914_01`. If it differs, reconcile the state before proceeding. `--sql` is
an offline preview; `current` connects read-only to the configured database.
Do not use `stamp` to bypass schema creation.

After SQL review and backup, apply exactly Phase 2B and verify:

```bash
.venv/bin/python -m alembic upgrade 20260914_02
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic check
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/ready
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/health
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/ready
```

Expected revision: `20260914_02 (head)`; `alembic check` reports no pending upgrade
operations. Confirm the exact application table set using the existing engine:

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import inspect
from app.database import engine
from app.models import Base
with engine.connect() as connection:
    actual = set(inspect(connection).get_table_names())
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert actual == expected, (actual - expected, expected - actual)
    print("Verified 21 application tables plus alembic_version")
PY
```

This schema-only deployment requires no service restart, Nginx, Certbot, UFW,
systemd, port, domain, VPS or `.env` changes. MySQL DDL is not rolled back as one
transaction; a failed upgrade can leave partially created tables. Inspect and
reconcile/restore that state before retrying. Use the existing migration account's
required DDL privileges; this change does not alter grants or credentials.

### Optional rollback

**Downgrade deletes every row in the nine Phase 2B tables.** Use a restorable
backup and run only when deliberately reverting Phase 2B from `20260914_02` with
no later dependent migration. It is not part of normal deployment.

Preview:

```bash
.venv/bin/python -m alembic downgrade 20260914_02:20260914_01 --sql > /tmp/rhu-phase2b-downgrade.sql
less /tmp/rhu-phase2b-downgrade.sql
```

Execute only for rollback:

```bash
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic downgrade 20260914_01
.venv/bin/python -m alembic current --verbose
```

Expected remaining revision: `20260914_01`. An `alembic check` using Phase 2B
models after rollback will correctly report the nine missing tables.

## Scope boundary

No laboratory catalog, sample types, panels, reference ranges or interpretation
rules are seeded. Controlled seed/reference data belongs to a later step. This
phase creates no orders, specimens, results, reports, CRUD/authentication APIs,
blockchain tables, microservices, or frontend/framework changes. Phase 2C has not
been started.
