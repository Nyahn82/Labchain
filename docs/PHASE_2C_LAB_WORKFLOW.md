# Phase 2C laboratory workflow

Phase 2C adds exactly nine tables to the existing FastAPI modular monolith.
`app/models/workflow.py` reuses `app.models.base.Base` and is registered by
`app/models/__init__.py`. Model imports do not connect to MySQL or create tables.
The existing Phase 2A and Phase 2B model definitions and migrations are unchanged.

## Reference and migration lineage

The authoritative workbook in this checkout is
[`reference/RHU_LabChain_Improved_3NF_Normalization(1).xlsx`](reference/RHU_LabChain_Improved_3NF_Normalization%281%29.xlsx).
The requested filename without `(1)` is absent. The nine workflow sheets,
Relationships, and Implementation_Notes were inspected before implementation.
Their definitions match the brief.

The existing migration files and `alembic heads` were inspected: the Phase 2B
head was `20260914_02`. The new explicit migration is:

- File: `migrations/versions/20260914_03_phase_2c_laboratory_workflow.py`
- Logical name: `phase_2c_laboratory_workflow`
- Revision: `20260914_03`
- `down_revision`: `20260914_02`
- Resulting chain: `20260914_01 -> 20260914_02 -> 20260914_03` (one head)

## Laboratory orders and requested tests

| Table | Purpose |
| --- | --- |
| `lab_order` | A patient's laboratory request, with optional physician and encoding account, dates, priority, notes and overall status |
| `order_panel` | A panel requested under an order; unique `(order_id, panel_id)` |
| `lab_order_item` | The central requested-test entity, linking an order to an individual catalog test and optionally its source panel request |
| `lab_payment` | Optional payment/status history: zero or many records per order |
| `specimen` | An accessioned specimen with sample type, order, collection/receipt provenance and status; many specimens may belong to one order |
| `specimen_order_item` | Explicit specimen-to-requested-test bridge; unique `(specimen_id, order_item_id)` |
| `rejection_reason` | Unseeded rejection reason catalog; unique `reason_code` |
| `specimen_rejection` | Rejection events with reason, actor, time, details and explicit recollection requirement; multiple events per specimen are allowed |
| `lab_result_item` | Display and optional numeric result, reference range, specimen and review provenance; always anchored to a requested test |

**LAB_ORDER_ITEM is the central requested-test entity.** Specimen mappings and
results reference its `order_item_id`. Future report lines must trace through
results to this requested test. Neither a catalog test nor a requested panel
replaces the individual request.

A later order service will expand a requested `test_panel` into `lab_order_item`
records, recording the originating `order_panel_id`. Individually requested tests
have a null `order_panel_id`. Expansion itself is not implemented here.
No unique `(order_id, test_id)` constraint is added: repeated requested tests remain
possible. There is also no unique order key on payments or unique requested-test
key on results.

Order, panel and item status values are exactly `REQUESTED`, `IN_PROGRESS`,
`COMPLETED`, `CANCELLED`. Priority values are exactly `ROUTINE`, `STAT`, `URGENT`.
These enums store state; they do not implement transition or aggregation rules.
`lab_order.diagnosis` is an optional working diagnosis supplied by an authorized
healthcare professional. The system does not generate diagnoses.

Payment/status records use `PENDING`, `PAID`, `FREE`, `WAIVED`, `SUBSIDIZED`.
`amount` is nullable `DECIMAL(12,2)`. An order requires no payment record and may
have multiple records. No billing logic is implemented.

## Specimens and rejection

`specimen_order_item` records which specimen is used for which requested test.
One order can contain tests needing different sample types; sharing an order does
not make every specimen suitable for every test. The bridge permits multiple
specimens per item and multiple items per specimen while preventing duplicate
pairs. It contains no redundant order column.

The specimen lifecycle vocabulary is `PENDING`, `COLLECTED`, `RECEIVED`,
`REJECTED`, `PROCESSED`. Collection and receipt actors/timestamps are nullable
until available. The later service will define allowed transitions, coordinate
provenance timestamps and determine eligibility for processing.

`specimen_rejection` records each rejection event rather than overwriting an
assumed single event. A reason, rejecting account, timestamp and
`recollection_required` are mandatory. Reasons are separate reusable setup rows;
none are seeded by this migration. Recording an event does not automatically
change `specimen.specimen_status`; a later transaction must coordinate both.

## Results before reports

The intended result lifecycle is **DRAFT -> REVIEWED -> VERIFIED**. The schema
stores the canonical status and encoding/review/verification accounts and times.
It does not enforce transitions, roles or consistency between status and optional
review fields. Encoding account/time are required; review and verification
account/time pairs are nullable pending those steps.

`result_value VARCHAR(100)` is the canonical display result and supports numeric
text and qualitative values such as `Negative`, `Positive`, `No growth` and
`Normal`. `numeric_value DECIMAL(12,3)` is optional and uses Python `Decimal` when
numeric processing applies. A numeric-looking display value does not automatically
populate it. The optional flag uses exactly `NORMAL`, `LOW`, `HIGH`,
`CRITICAL_LOW`, `CRITICAL_HIGH`, `ABNORMAL`; no automatic flag calculation runs.

`LAB_RESULT_ITEM` is independent of `LAB_REPORT`: there is no `report_id` and no
report table or foreign key. Results exist and are verified before later report
snapshotting. **VERIFIED results will later be eligible for official reporting**;
verification alone does not create, release or publish a report.

Reference ranges will be selected by test, patient sex, patient age and effective
date. Age is derived from `patient.birth_date` when needed, never stored as a
permanent patient age. Range selection, result interpretation and clinical
content approval are later work. Results must not generate diagnoses,
prescriptions or treatment plans.

## Cross-entity integrity and later service rules

1. **An item's source panel must belong to the same laboratory order.** The later
   service must validate this when expanding or changing requests. It is also
   enforced now by a composite FK:
   `lab_order_item(order_panel_id, order_id) -> order_panel(order_panel_id, order_id)`.
   The supporting unique key on the parent repeats an already-unique primary key,
   so it introduces no new business restriction or column. This follows Phase
   2B's same-panel constraint pattern and preserves the original individual FKs.
   A null source panel is valid. Invalid inserts and changes at either end are
   rejected without cascades.
2. **A specimen and order item connected through `specimen_order_item` must belong
   to the same laboratory order.** Individual FKs only prove that both exist.
   The bridge does not store `order_id`; enforcing equality with composite FKs
   would require adding a redundant order column or procedural triggers. Neither
   is added. The later service must compare the two parent order IDs atomically
   on bridge creation/update and any parent reassignment, including concurrency
   protection against conflicting changes.
3. **A result's specimen, when supplied, must be valid for that result's order
   item**, normally via `specimen_order_item`. The service must validate same-order
   membership, the mapping and applicable sample-type/processing eligibility.
   Existence of a specimen alone does not prove validity. No unconditional
   result-to-bridge FK is added because the brief says "normally" through that
   bridge and does not define allowed exceptions; that policy must be settled
   before write APIs are enabled. Bridge removal/reassignment must also preserve
   existing result validity. A null result specimen remains permitted.
4. **Rejected specimen state must be coordinated with rejection events.** The
   service must authorize the actor, write the event, update specimen state and
   handle recollection consistently in one transaction. The schema intentionally
   supports multiple events and does not synchronize them automatically.
5. **Only VERIFIED results are eligible for later official reporting.** Review
   services must enforce transitions, authorization and actor/timestamp consistency;
   future reporting services must validate eligibility before snapshotting.
6. When `reference_range_id` is supplied, the service must ensure its test matches
   the requested item's test and that sex, derived age and effective date apply.
   Numeric/display consistency and any flag calculation are also later validation.

There are no service implementations, triggers, ORM event hooks or API endpoints
in this phase. Direct SQL can still violate the documented service-only rules.
No ORM navigation relationships are added, matching Phase 2B and avoiding
ambiguous joins or implicit history deletion.

## Storage conventions

Every new table uses a signed `BIGINT` auto-increment primary key, InnoDB and
`utf8mb4`. Native MySQL ENUMs retain the exact canonical strings. Collation follows
the existing server defaults. FK behavior remains restrictive, with no automatic
delete/update cascades.

`created_at` on orders, order items and specimens defaults to `CURRENT_TIMESTAMP`,
following Phase 2A. `rejection_reason.is_active` defaults to `1`. Workflow status,
priority, event timestamps and `recollection_required` have no invented defaults.
Nullable `updated_at` is not automatically updated.

The migration creates nine PKs, 26 FKs (25 workbook FKs plus the same-order FK),
six unique constraints (five workbook constraints plus the supporting parent
key), and 23 explicit nonunique indexes. The unique order-code key supplies its
required index. Leading unique-key columns cover `order_panel.order_id` and
`specimen_order_item.specimen_id`; redundant standalone indexes are avoided.
The complete FK, unique and index inventories follow the deployment instructions.

## Verification performed

The baseline was 50 passing tests. The extended suite has 83 passing tests,
including the original FastAPI import, health and readiness checks. New tests
compare every Phase 2C column, type, nullability and original FK directly with the
tracked workbook; independently assert canonical enums and uniqueness; check FK
index coverage; and compare frozen migrations with model metadata.

Offline MySQL SQL tests check the exact nine-table scope, dependency order,
engine/charset, auto-increment, decimal types and composite constraint. Isolated
SQLite migration tests check every FK, non-null columns, duplicate rejection,
allowed repeated workflow records, optional links, decimal/display storage,
parent deletion protection, and same-order panel integrity on inserts/updates.
Downgrade preserves the previous 21 tables and their synthetic data. The existing
complete-history Alembic test uses an in-memory engine and checks metadata drift.

Tests use synthetic settings and block network access before application imports.
No Hostinger database migration or live MySQL test was run. SQLite relational
execution and offline MySQL compilation do not prove live MySQL ENUM enforcement
or auto-increment behavior. Rehearsal on disposable MySQL 8 remains the live-server
validation step.

## Exact Hostinger deployment commands

These commands are for the operator; they were not executed against production.
Run as `rhuadmin` after delivering the reviewed Phase 2C files to the existing
checkout. No new dependency installation or frontend build is needed. Run one
command at a time and stop on failure. Confirm the existing configuration targets
`rhu_labchain` with the intended account and no unexpected environment overrides.
Take a restorable backup before the online upgrade.

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m alembic heads
.venv/bin/python -m alembic history --verbose
.venv/bin/python -m alembic upgrade 20260914_02:20260914_03 --sql > /tmp/rhu-phase2c-upgrade.sql
less /tmp/rhu-phase2c-upgrade.sql
.venv/bin/python -m alembic current --verbose
```

Expected code head: `20260914_03`, exactly one head. Expected current database
revision before upgrade: `20260914_02`. Reconcile unexpected state first; do not
use `stamp` to skip schema creation. `--sql` does not connect; `current` is an
online read of the configured database.

After SQL review and backup:

```bash
.venv/bin/python -m alembic upgrade 20260914_03
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic check
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/ready
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/health
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/ready
```

Expect `20260914_03 (head)`, no pending upgrade operations, and successful health
and readiness responses. Verify the application table set:

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import inspect
from app.database import engine
from app.models import Base
with engine.connect() as connection:
    actual = set(inspect(connection).get_table_names())
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert actual == expected, (actual - expected, expected - actual)
    print("Verified 30 application tables plus alembic_version")
PY
```

No service restart or Nginx, Certbot, UFW, systemd, VPS, domain, port or `.env`
change is required. MySQL DDL is not rolled back as a single transaction. On a
partial migration failure, inspect and reconcile or restore before retrying;
do not blindly rerun or stamp the revision. Existing migration credentials must
have the required DDL privileges; this change does not alter credentials/grants.

## Optional destructive downgrade

Downgrade removes only Phase 2C tables, in reverse creation order. Table drops
remove their indexes and constraints together. **All Phase 2C workflow data is
lost.** Use a restorable backup and run only when deliberately reverting from
`20260914_03` with no later dependent migration. This is not normal deployment.

Offline preview:

```bash
.venv/bin/python -m alembic downgrade 20260914_03:20260914_02 --sql > /tmp/rhu-phase2c-downgrade.sql
less /tmp/rhu-phase2c-downgrade.sql
```

Deliberate rollback only:

```bash
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic downgrade 20260914_02
.venv/bin/python -m alembic current --verbose
```

Expected database revision afterward: `20260914_02`; all 21 Phase 2A/2B application
tables remain. `alembic check` with Phase 2C models will then correctly report the
nine missing tables. Never downgrade to `base` to roll back only Phase 2C.

## Scope boundary

The migration contains no seed data. This phase implements database models,
constraints, indexes, one migration, tests and documentation only. APIs,
authentication, services, panel expansion, result calculation, report/audit/logging
or blockchain tables, PDF/QR generation, dashboards and frontend frameworks remain
later work. Phase 2D has not been started.

## Foreign-key inventory

| Constraint | Child columns | Referenced columns |
| --- | --- | --- |
| `fk_lab_order_ordered_by_user_id_user_account` | `lab_order(ordered_by_user_id)` | `user_account(user_id)` |
| `fk_lab_order_patient_id_patient` | `lab_order(patient_id)` | `patient(patient_id)` |
| `fk_lab_order_physician_id_requesting_physician` | `lab_order(physician_id)` | `requesting_physician(physician_id)` |
| `fk_order_panel_order_id_lab_order` | `order_panel(order_id)` | `lab_order(order_id)` |
| `fk_order_panel_panel_id_test_panel` | `order_panel(panel_id)` | `test_panel(panel_id)` |
| `fk_lab_order_item_order_id_lab_order` | `lab_order_item(order_id)` | `lab_order(order_id)` |
| `fk_lab_order_item_order_panel_id_order_id_order_panel` | `lab_order_item(order_panel_id, order_id)` | `order_panel(order_panel_id, order_id)` |
| `fk_lab_order_item_order_panel_id_order_panel` | `lab_order_item(order_panel_id)` | `order_panel(order_panel_id)` |
| `fk_lab_order_item_test_id_test_catalog` | `lab_order_item(test_id)` | `test_catalog(test_id)` |
| `fk_lab_payment_order_id_lab_order` | `lab_payment(order_id)` | `lab_order(order_id)` |
| `fk_lab_payment_recorded_by_user_id_user_account` | `lab_payment(recorded_by_user_id)` | `user_account(user_id)` |
| `fk_specimen_collected_by_user_id_user_account` | `specimen(collected_by_user_id)` | `user_account(user_id)` |
| `fk_specimen_order_id_lab_order` | `specimen(order_id)` | `lab_order(order_id)` |
| `fk_specimen_received_by_user_id_user_account` | `specimen(received_by_user_id)` | `user_account(user_id)` |
| `fk_specimen_sample_type_id_sample_type` | `specimen(sample_type_id)` | `sample_type(sample_type_id)` |
| `fk_specimen_order_item_order_item_id_lab_order_item` | `specimen_order_item(order_item_id)` | `lab_order_item(order_item_id)` |
| `fk_specimen_order_item_specimen_id_specimen` | `specimen_order_item(specimen_id)` | `specimen(specimen_id)` |
| `fk_specimen_rejection_rejected_by_user_id_user_account` | `specimen_rejection(rejected_by_user_id)` | `user_account(user_id)` |
| `fk_specimen_rejection_rejection_reason_id_rejection_reason` | `specimen_rejection(rejection_reason_id)` | `rejection_reason(rejection_reason_id)` |
| `fk_specimen_rejection_specimen_id_specimen` | `specimen_rejection(specimen_id)` | `specimen(specimen_id)` |
| `fk_lab_result_item_encoded_by_user_id_user_account` | `lab_result_item(encoded_by_user_id)` | `user_account(user_id)` |
| `fk_lab_result_item_order_item_id_lab_order_item` | `lab_result_item(order_item_id)` | `lab_order_item(order_item_id)` |
| `fk_lab_result_item_reference_range_id_reference_range` | `lab_result_item(reference_range_id)` | `reference_range(range_id)` |
| `fk_lab_result_item_reviewed_by_user_id_user_account` | `lab_result_item(reviewed_by_user_id)` | `user_account(user_id)` |
| `fk_lab_result_item_specimen_id_specimen` | `lab_result_item(specimen_id)` | `specimen(specimen_id)` |
| `fk_lab_result_item_verified_by_user_id_user_account` | `lab_result_item(verified_by_user_id)` | `user_account(user_id)` |

## Unique-constraint inventory

| Constraint | Columns |
| --- | --- |
| `uq_lab_order_order_code` | `lab_order(order_code)` |
| `uq_order_panel_order_id_panel_id` | `order_panel(order_id, panel_id)` |
| `uq_order_panel_order_panel_id_order_id` | `order_panel(order_panel_id, order_id)` |
| `uq_specimen_specimen_code` | `specimen(specimen_code)` |
| `uq_specimen_order_item_specimen_id_order_item_id` | `specimen_order_item(specimen_id, order_item_id)` |
| `uq_rejection_reason_reason_code` | `rejection_reason(reason_code)` |

## Explicit index inventory

| Index | Columns |
| --- | --- |
| `ix_lab_order_ordered_by_user_id` | `lab_order(ordered_by_user_id)` |
| `ix_lab_order_patient_id` | `lab_order(patient_id)` |
| `ix_lab_order_physician_id` | `lab_order(physician_id)` |
| `ix_order_panel_panel_id` | `order_panel(panel_id)` |
| `ix_lab_order_item_order_id` | `lab_order_item(order_id)` |
| `ix_lab_order_item_order_panel_id_order_id` | `lab_order_item(order_panel_id, order_id)` |
| `ix_lab_order_item_test_id` | `lab_order_item(test_id)` |
| `ix_lab_payment_order_id` | `lab_payment(order_id)` |
| `ix_lab_payment_recorded_by_user_id` | `lab_payment(recorded_by_user_id)` |
| `ix_specimen_collected_by_user_id` | `specimen(collected_by_user_id)` |
| `ix_specimen_order_id` | `specimen(order_id)` |
| `ix_specimen_received_by_user_id` | `specimen(received_by_user_id)` |
| `ix_specimen_sample_type_id` | `specimen(sample_type_id)` |
| `ix_specimen_order_item_order_item_id` | `specimen_order_item(order_item_id)` |
| `ix_specimen_rejection_rejected_by_user_id` | `specimen_rejection(rejected_by_user_id)` |
| `ix_specimen_rejection_rejection_reason_id` | `specimen_rejection(rejection_reason_id)` |
| `ix_specimen_rejection_specimen_id` | `specimen_rejection(specimen_id)` |
| `ix_lab_result_item_encoded_by_user_id` | `lab_result_item(encoded_by_user_id)` |
| `ix_lab_result_item_order_item_id` | `lab_result_item(order_item_id)` |
| `ix_lab_result_item_reference_range_id` | `lab_result_item(reference_range_id)` |
| `ix_lab_result_item_reviewed_by_user_id` | `lab_result_item(reviewed_by_user_id)` |
| `ix_lab_result_item_specimen_id` | `lab_result_item(specimen_id)` |
| `ix_lab_result_item_verified_by_user_id` | `lab_result_item(verified_by_user_id)` |
