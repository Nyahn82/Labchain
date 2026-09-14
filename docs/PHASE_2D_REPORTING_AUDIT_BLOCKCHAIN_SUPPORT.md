# Phase 2D reporting, audit and blockchain support

Phase 2D adds sixteen tables to the existing FastAPI modular monolith, using the
shared SQLAlchemy 2.x `Base`. Models live in `app/models/reporting.py`,
`app/models/logging.py` and `app/models/blockchain.py`; `app/models/__init__.py`
registers them without connecting to a database or creating tables.

## Reference and revision chain

The supplied authoritative workbook is
[`reference/RHU_LabChain_Improved_3NF_Normalization(1).xlsx`](reference/RHU_LabChain_Improved_3NF_Normalization%281%29.xlsx).
The filename without `(1)` is absent. All sixteen relevant table sheets,
Relationships and Implementation_Notes were inspected before implementation.
The workbook definitions agree with the brief. Its conditional note about a
single active signatory profile does not establish unconditional staff uniqueness;
`signatory.staff_id` remains nonunique, matching the stated 1:M relationship.

The existing migration files and `alembic heads` showed Phase 2C at
`20260914_03`. The new explicit migration is:

- File: `migrations/versions/20260914_04_phase_2d_reporting_audit_blockchain_support.py`
- Logical name: `phase_2d_reporting_audit_blockchain_support`
- Revision: `20260914_04`
- `down_revision`: `20260914_03`
- Chain: `20260914_01 -> 20260914_02 -> 20260914_03 -> 20260914_04`
- Head count: one

Previous migrations and Phase 2A/2B/2C model definitions are unchanged. Upgrade
creates only the following tables in the listed order, with no seed data.

## Sixteen tables

| Table | Purpose |
| --- | --- |
| `report_template` | Report layout and approved notes; optional panel association permits general templates |
| `lab_report` | Official report version, order/facility/template links, self-reference to a superseded version, lifecycle provenance and optional PDF path |
| `report_result_item` | Stored printable result lines, each referencing its source result and optionally its panel grouping |
| `report_patient_snapshot` | One patient/physician snapshot per report version; `report_id` is a non-auto-increment PK/FK |
| `signatory` | Staff signatory profiles, signature asset path and license snapshot; multiple profiles per staff remain allowed |
| `report_signatory` | Report/signatory association, printed professional role, signing time and sort order |
| `report_verification` | Opaque public verification token, report hash and public verification status; multiple records per report remain allowed |
| `email_log` | Delivery history with optional report/patient links and recipient address snapshot |
| `print_log` | One row per print action, with actor, timestamp and number of copies |
| `audit_log` | Append-only application history policy, with optional actor and JSON old/new snapshots |
| `login_log` | Login outcome and optional logout metadata; unknown usernames may have a null account link |
| `attachment` | File metadata linked to an order, a report, or both |
| `blockchain_node` | Logical node registry only, with unique code and port metadata |
| `blockchain_event` | Internal event identity, origin, entity reference, canonical hash and submission status metadata |
| `blockchain_verification_log` | Stored database/chain hash comparison metadata for an event and logical node |
| `blockchain_sync_log` | Stored source/target node, block height and synchronization outcome metadata |

## Report versions and immutability

`LAB_ORDER_ITEM` remains the central requested-test entity. Report lines trace
through `report_result_item.result_item_id -> lab_result_item.order_item_id` to
the requested test. `LAB_RESULT_ITEM` still exists independently of `LAB_REPORT`;
its schema has no report dependency.

Report statuses are exactly `GENERATED`, `APPROVED`, `RELEASED`, `REVOKED`.
**After release, the application's future services must not overwrite clinical or
printable report content.** A correction creates another `lab_report` row with
`version_no = previous version + 1` and `supersedes_report_id = prior report_id`.
The older report may then be marked revoked, with actor, time and reason, while
retaining its historical content.

The self-FK proves only that the prior report exists. It does not enforce version
sequence, same-order lineage, absence of self-links/cycles, authorization, or
immutability. Those rules, concurrency control for corrections, and lifecycle
actor/timestamp consistency belong to the later report service. No speculative
unique `(order_id, version_no)` constraint or trigger is added.

Only **VERIFIED** results should later be included in official report snapshots.
The report service must check eligibility and that each result's requested item
belongs to the report's order before capturing content. The FK itself does not
check result status or same-order membership. Report creation, approval, release,
PDF rendering and clinical interpretation are not implemented here.

## Intentional historical snapshots

`report_result_item` stores the printed section name, test name, display result,
unit, reference range, flag and ordering. These values intentionally duplicate
printable data. They must not be replaced with live catalog or reference-range
joins: later source edits must not change what a historical report displayed.
`flag_snapshot` is `VARCHAR(40)`, preserving the printed value rather than using a
live result-flag enum. Panel identity remains an optional FK as the workbook specifies.

`report_patient_snapshot` stores the printed patient code/name, birth date, sex,
physician name and `age_at_report`. Its PK/FK permits at most one snapshot per
report version; the later report service must ensure a required snapshot exists
before release. `PATIENT` still has no permanent age field. Current age is derived
from `patient.birth_date`; historical `age_at_report` preserves the printed age.

`signatory` references staff and stores the signature asset path and license
snapshot. `report_signatory` records the role printed on a particular report:
`LAB_IN_CHARGE`, `MEDICAL_TECHNOLOGIST`, or `PATHOLOGIST`. There is no invented
uniqueness constraint on staff, report/signatory pairs or roles. The future service
must preserve profiles/assets used by released reports, coordinate signing
provenance, and avoid rewriting a referenced signature asset in place. This phase
adds no extra per-report signature snapshot fields beyond the workbook.

## Opaque verification tokens and canonical hashes

A future public QR code must contain or resolve using an **opaque verification
token**, never a patient ID/name, laboratory value, internal report ID or other
database identifier. Public verification should reveal authenticity/status only.
It must not reveal full patient results. The token is unique, but its randomness,
entropy, generation, access policy and revocation handling require later services.

`report_hash`, `record_hash`, `database_hash` and `chain_hash` are `CHAR(64)`
columns intended for SHA-256 hexadecimal values. Canonical hashing will later
serialize a defined protected representation deterministically (for example,
canonical JSON) before hashing with SHA-256. Field selection, ordering, number/date
encoding and handling of null values must be stable. A stored string does not
prove correct canonicalization or integrity; these columns do not calculate or
validate hashes. `event_uuid CHAR(36)` likewise stores, but does not generate or
validate, an event UUID. No hashing, QR endpoint or token generation is implemented.

## Delivery, audit, login and attachments

`email_log.recipient_email` preserves the actual delivery target even if the
patient's address later changes. Report/patient links are optional. Email states
are exactly `PENDING`, `SENT`, `FAILED`. This table sends no email.

Each print action creates a new `print_log` row with its `copies` value. No
cumulative `print_count` is added to `lab_report`; print execution and validation
of copy counts are later service responsibilities.

**Audit history is append-only application history.** No audit update/delete APIs
are introduced. A future writer must redact passwords, password hashes,
authentication tokens and encryption keys from `old_value`/`new_value`, including
nested JSON. Credentials remain only in `user_account`. JSON columns alone do not
redact secrets or prevent updates/deletes. No trigger or grant change is made.
Python `None` maps to SQL NULL for these nullable JSON fields (`none_as_null=True`).

`login_log` permits a null user for unknown usernames and stores exactly `SUCCESS`
or `FAILED`. Its optional logout timestamp supports later session logging. No
authentication behavior or token storage is added. Audit and login IP fields are
`VARCHAR(45)` for IPv4/IPv6 text.

`attachment` has the named constraint `ck_attachment_parent_required`:

```sql
CHECK (order_id IS NOT NULL OR report_id IS NOT NULL)
```

It permits either parent or both, and rejects neither. MySQL **8.0.16 or newer**
is required for CHECK enforcement. Both foreign keys remain nullable. When both
links are present, the future service must validate that the report belongs to
the supplied order. Path authorization, upload validation and private file access
are later work; storing metadata does not upload or expose a file.

## Blockchain support boundary

**These tables do not themselves make the system a blockchain implementation.**
MySQL remains the source of truth for patient and laboratory data. The four tables
store logical registry, event, hash-check and sync metadata only. They implement
no ledger, consensus, peers, synchronization, smart contracts, Hyperledger Fabric,
IPFS, node daemons or blockchain API.

Do not put patient names, full result values, complete reports or other protected
clinical content into blockchain support records, including free-text `details`.
`entity_id` is an internal polymorphic reference, not a public identifier or a
single-target FK. A future service must validate its meaning and enforce the
metadata-only boundary.

A node's responsibility identifies event origin; it does not imply that each node
stores only part of the ledger. The later design expects accepted events to
synchronize across logical nodes. Port values here are registry data, not process
configuration. No nodes are seeded or started, no ports are opened, and the
existing FastAPI listener at `127.0.0.1:5001` is unchanged.

The stored vocabularies are exactly:

- Event: `PENDING`, `ACCEPTED`, `REJECTED`.
- Integrity comparison: `MATCH`, `MISMATCH`, `NOT_FOUND`.
- Synchronization: `SUCCESS`, `FAILED`, `CONFLICT`.

No event submission, hash comparison or node synchronization runs in this phase.

## Constraints, indexes and defaults

There are sixteen primary keys, 32 foreign keys, six unique constraints, one
named CHECK, and 31 explicit nonunique indexes. The patient snapshot PK is its
report FK and does not auto-increment; the other fifteen PKs do. All IDs use signed
`BIGINT`, tables use InnoDB and `utf8mb4`, and enums compile to native MySQL ENUMs.
String equality follows the established server collation; no new collation policy
is imposed on tokens, codes or hashes in this phase.

Required unique keys are `report_template.template_code`, `lab_report.report_code`,
`report_verification.verification_token`, `blockchain_node.node_code`,
`blockchain_node.port`, and `blockchain_event.event_uuid`. There is no unique
`report_id` on `report_verification`; its relationship remains 1:M.

Every FK has an explicit index except `report_patient_snapshot.report_id`, which
is already indexed by its PK. No automatic FK update/delete cascade or ORM delete
cascade is introduced. Existing referenced medical/history records stay protected
by restrictive FK behavior. No ORM navigation relationships are added, following
Phases 2B/2C and avoiding ambiguous multiple account or node relationships.

`is_active` defaults to `1`, and `created_at` defaults to `CURRENT_TIMESTAMP`,
consistent with earlier phases. Status values, `version_no`, sort order, copy
counts, event timestamps and node ports have no invented defaults. Nullable dates
are not automatically updated. The complete named inventories appear below.

## Tests and validation limits

Baseline: 83 passing tests. Extended suite: 135 passing tests. The workbook parser
was extracted into `tests/workbook_helpers.py` so Phase 2C and Phase 2D share the
existing contract strategy, with added support for CHAR, DATE, INT and JSON.
Previous phase tests still exercise their specific frozen revisions; the complete
Alembic environment test uses the new head and an isolated in-memory engine.

Coverage includes exact columns, types, lengths, nullability, enums, defaults,
FKs, unique keys, snapshot PK behavior, JSON storage, index coverage, and frozen
migration/model agreement including CHECK expressions. Offline MySQL SQL tests
check sixteen-table scope, dependency order including the self-FK, fifteen
auto-increment keys, native types and reverse downgrade order.

SQLite tests execute the real migrations with explicit synthetic BIGINT IDs and
foreign keys enabled. They check orphan/required-value rejection, uniqueness,
allowed multiple verifications and signatories, snapshot independence from source
edits, report version links, nullable log references, all attachment parent
combinations, and downgrade preservation of all thirty earlier tables and their
synthetic data. Application import, health/readiness behavior and the unchanged
set of API paths also pass.

Tests block network access before app imports and use synthetic settings. No
production migration, service restart or live MySQL execution was performed.
Offline compilation and SQLite execution do not verify actual MySQL ENUM, JSON,
auto-increment, collation or CHECK enforcement. Rehearse on disposable MySQL 8.0.16+
before the production deployment. Deployed migration files have checksum regression tests. Protected configuration
files are also checked for changes during the final repository review.

## Exact Hostinger deployment commands

These are manual operator instructions and were not executed against production.
Run as `rhuadmin` after delivering the reviewed Phase 2D files. Use the existing
checkout and environment; there is no new dependency or frontend build. Run one
command at a time and stop on failure. Confirm the configured database is
`rhu_labchain` with the intended account and no unexpected environment overrides.
Take a restorable backup before applying the upgrade.

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m alembic heads
.venv/bin/python -m alembic history --verbose
.venv/bin/python -m alembic upgrade 20260914_03:20260914_04 --sql > /tmp/rhu-phase2d-upgrade.sql
less /tmp/rhu-phase2d-upgrade.sql
.venv/bin/python -m alembic current --verbose
```

Expected code head: `20260914_04`, exactly one head. Expected database revision
before deployment: `20260914_03`. Reconcile unexpected state first; do not use
`stamp` to skip schema creation. The SQL preview is offline; `current` connects
read-only using the existing application configuration.

Check the server version before relying on enforced CHECK constraints:

```bash
.venv/bin/python - <<'PY'
import re
from sqlalchemy import text
from app.database import engine
with engine.connect() as connection:
    version = connection.scalar(text("SELECT VERSION()"))
    print("Database server:", version)
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    assert match and "MariaDB" not in version, "This migration targets MySQL"
    assert tuple(map(int, match.groups())) >= (8, 0, 16), "Enforced CHECK requires MySQL 8.0.16+"
PY
```

After SQL review, server-version verification and backup:

```bash
.venv/bin/python -m alembic upgrade 20260914_04
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic check
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5001/api/v1/ready
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/health
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/ready
```

Expect `20260914_04 (head)`, no pending upgrade operations and successful health
and readiness responses. Verify the tables and named attachment CHECK explicitly:

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import inspect
from app.database import engine
from app.models import Base
with engine.connect() as connection:
    inspector = inspect(connection)
    actual = set(inspector.get_table_names())
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert actual == expected, (actual - expected, expected - actual)
    checks = inspector.get_check_constraints("attachment")
    assert any(c["name"] == "ck_attachment_parent_required" for c in checks)
    print("Verified 46 application tables, alembic_version and attachment CHECK")
PY
```

No Nginx, Certbot, UFW, systemd, VPS, domain, port or production `.env` change is
required. No service restart is needed for this schema-only phase. MySQL DDL is
not rolled back as a single transaction: a failure can leave partially created
tables. Inspect and reconcile or restore that state before retrying; do not stamp
or rerun blindly. This change does not alter database accounts or grants.

## Optional destructive downgrade

Downgrade removes only the sixteen Phase 2D tables, in reverse dependency order.
It removes their indexes and constraints with the tables. **All Phase 2D data is
lost**, including reports, snapshots, verification and history records. Use a
restorable backup and run only when deliberately reverting from `20260914_04`
with no later dependent revision. This is not part of normal deployment.

Offline preview:

```bash
.venv/bin/python -m alembic downgrade 20260914_04:20260914_03 --sql > /tmp/rhu-phase2d-downgrade.sql
less /tmp/rhu-phase2d-downgrade.sql
```

Deliberate rollback only:

```bash
.venv/bin/python -m alembic current --verbose
.venv/bin/python -m alembic downgrade 20260914_03
.venv/bin/python -m alembic current --verbose
```

Expected remaining database revision: `20260914_03`; all thirty earlier application
tables remain. An `alembic check` using Phase 2D models after rollback correctly
reports missing Phase 2D tables. Do not downgrade to `base` for a Phase 2D rollback.

## Scope boundary

This phase adds database models, one migration, tests and documentation only.
It seeds no templates, signatories, tokens, reports or nodes. It implements no API,
report generator, PDF, QR endpoint, email sender, upload handler, hashing service,
ledger, consensus, peer process, smart contract, IPFS or frontend dashboard.
API development has not been started.

## Foreign-key inventory

| Constraint | Child columns | Referenced columns |
| --- | --- | --- |
| `fk_attachment_order_id_lab_order` | `attachment(order_id)` | `lab_order(order_id)` |
| `fk_attachment_report_id_lab_report` | `attachment(report_id)` | `lab_report(report_id)` |
| `fk_attachment_uploaded_by_user_id_user_account` | `attachment(uploaded_by_user_id)` | `user_account(user_id)` |
| `fk_audit_log_user_id_user_account` | `audit_log(user_id)` | `user_account(user_id)` |
| `fk_blockchain_event_created_by_user_id_user_account` | `blockchain_event(created_by_user_id)` | `user_account(user_id)` |
| `fk_blockchain_event_origin_node_id_blockchain_node` | `blockchain_event(origin_node_id)` | `blockchain_node(node_id)` |
| `fk_blockchain_sync_log_source_node_id_blockchain_node` | `blockchain_sync_log(source_node_id)` | `blockchain_node(node_id)` |
| `fk_blockchain_sync_log_target_node_id_blockchain_node` | `blockchain_sync_log(target_node_id)` | `blockchain_node(node_id)` |
| `fk_blockchain_verification_log_event_id_blockchain_event` | `blockchain_verification_log(event_id)` | `blockchain_event(event_id)` |
| `fk_blockchain_verification_log_node_id_blockchain_node` | `blockchain_verification_log(node_id)` | `blockchain_node(node_id)` |
| `fk_email_log_patient_id_patient` | `email_log(patient_id)` | `patient(patient_id)` |
| `fk_email_log_report_id_lab_report` | `email_log(report_id)` | `lab_report(report_id)` |
| `fk_lab_report_approved_by_user_id_user_account` | `lab_report(approved_by_user_id)` | `user_account(user_id)` |
| `fk_lab_report_facility_id_facility_profile` | `lab_report(facility_id)` | `facility_profile(facility_id)` |
| `fk_lab_report_generated_by_user_id_user_account` | `lab_report(generated_by_user_id)` | `user_account(user_id)` |
| `fk_lab_report_order_id_lab_order` | `lab_report(order_id)` | `lab_order(order_id)` |
| `fk_lab_report_released_by_user_id_user_account` | `lab_report(released_by_user_id)` | `user_account(user_id)` |
| `fk_lab_report_revoked_by_user_id_user_account` | `lab_report(revoked_by_user_id)` | `user_account(user_id)` |
| `fk_lab_report_supersedes_report_id_lab_report` | `lab_report(supersedes_report_id)` | `lab_report(report_id)` |
| `fk_lab_report_template_id_report_template` | `lab_report(template_id)` | `report_template(template_id)` |
| `fk_login_log_user_id_user_account` | `login_log(user_id)` | `user_account(user_id)` |
| `fk_print_log_printed_by_user_id_user_account` | `print_log(printed_by_user_id)` | `user_account(user_id)` |
| `fk_print_log_report_id_lab_report` | `print_log(report_id)` | `lab_report(report_id)` |
| `fk_report_patient_snapshot_report_id_lab_report` | `report_patient_snapshot(report_id)` | `lab_report(report_id)` |
| `fk_report_result_item_panel_id_snapshot_test_panel` | `report_result_item(panel_id_snapshot)` | `test_panel(panel_id)` |
| `fk_report_result_item_report_id_lab_report` | `report_result_item(report_id)` | `lab_report(report_id)` |
| `fk_report_result_item_result_item_id_lab_result_item` | `report_result_item(result_item_id)` | `lab_result_item(result_item_id)` |
| `fk_report_signatory_report_id_lab_report` | `report_signatory(report_id)` | `lab_report(report_id)` |
| `fk_report_signatory_signatory_id_signatory` | `report_signatory(signatory_id)` | `signatory(signatory_id)` |
| `fk_report_template_panel_id_test_panel` | `report_template(panel_id)` | `test_panel(panel_id)` |
| `fk_report_verification_report_id_lab_report` | `report_verification(report_id)` | `lab_report(report_id)` |
| `fk_signatory_staff_id_staff` | `signatory(staff_id)` | `staff(staff_id)` |

## Unique-constraint inventory

| Constraint | Columns |
| --- | --- |
| `uq_blockchain_event_event_uuid` | `blockchain_event(event_uuid)` |
| `uq_blockchain_node_node_code` | `blockchain_node(node_code)` |
| `uq_blockchain_node_port` | `blockchain_node(port)` |
| `uq_lab_report_report_code` | `lab_report(report_code)` |
| `uq_report_template_template_code` | `report_template(template_code)` |
| `uq_report_verification_verification_token` | `report_verification(verification_token)` |

## Explicit index inventory

| Index | Columns |
| --- | --- |
| `ix_attachment_order_id` | `attachment(order_id)` |
| `ix_attachment_report_id` | `attachment(report_id)` |
| `ix_attachment_uploaded_by_user_id` | `attachment(uploaded_by_user_id)` |
| `ix_audit_log_user_id` | `audit_log(user_id)` |
| `ix_blockchain_event_created_by_user_id` | `blockchain_event(created_by_user_id)` |
| `ix_blockchain_event_origin_node_id` | `blockchain_event(origin_node_id)` |
| `ix_blockchain_sync_log_source_node_id` | `blockchain_sync_log(source_node_id)` |
| `ix_blockchain_sync_log_target_node_id` | `blockchain_sync_log(target_node_id)` |
| `ix_blockchain_verification_log_event_id` | `blockchain_verification_log(event_id)` |
| `ix_blockchain_verification_log_node_id` | `blockchain_verification_log(node_id)` |
| `ix_email_log_patient_id` | `email_log(patient_id)` |
| `ix_email_log_report_id` | `email_log(report_id)` |
| `ix_lab_report_approved_by_user_id` | `lab_report(approved_by_user_id)` |
| `ix_lab_report_facility_id` | `lab_report(facility_id)` |
| `ix_lab_report_generated_by_user_id` | `lab_report(generated_by_user_id)` |
| `ix_lab_report_order_id` | `lab_report(order_id)` |
| `ix_lab_report_released_by_user_id` | `lab_report(released_by_user_id)` |
| `ix_lab_report_revoked_by_user_id` | `lab_report(revoked_by_user_id)` |
| `ix_lab_report_supersedes_report_id` | `lab_report(supersedes_report_id)` |
| `ix_lab_report_template_id` | `lab_report(template_id)` |
| `ix_login_log_user_id` | `login_log(user_id)` |
| `ix_print_log_printed_by_user_id` | `print_log(printed_by_user_id)` |
| `ix_print_log_report_id` | `print_log(report_id)` |
| `ix_report_result_item_panel_id_snapshot` | `report_result_item(panel_id_snapshot)` |
| `ix_report_result_item_report_id` | `report_result_item(report_id)` |
| `ix_report_result_item_result_item_id` | `report_result_item(result_item_id)` |
| `ix_report_signatory_report_id` | `report_signatory(report_id)` |
| `ix_report_signatory_signatory_id` | `report_signatory(signatory_id)` |
| `ix_report_template_panel_id` | `report_template(panel_id)` |
| `ix_report_verification_report_id` | `report_verification(report_id)` |
| `ix_signatory_staff_id` | `signatory(staff_id)` |
