# Phase 5A — Official reports, snapshots, signatories and approval

Phase 5A generates official report records and historical patient/result snapshots
from completed laboratory orders. Its only transition is `GENERATED -> APPROVED`.
**Phase 5A does NOT release reports.** It uses the existing normalized reporting
schema without any model, column, constraint or migration change.

Phase 5B will create the final immutable PDF, QR code, canonical report SHA-256,
REPORT_VERIFICATION and RELEASED transition together, and implement the later
revocation/version correction lifecycle. None of those operations is implemented
here. There is no public verification, patient report access, blockchain event,
email delivery, print tracking, upload or frontend addition.

## Routes and permissions

All paths are relative to `/api/v1`. Creation returns 201; reads, PATCH, signing
and approval return 200. All 19 operations use the existing opaque session,
server-side RBAC, CSRF protection for unsafe methods, private validation errors
and `Cache-Control: no-store`. There are no DELETE operations.

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/facility-profile` | FACILITY_PROFILE_READ |
| POST, PATCH | `/facility-profile` | FACILITY_PROFILE_MANAGE |
| GET | `/report-templates` | REPORT_TEMPLATE_READ |
| GET | `/report-templates/{template_id}` | REPORT_TEMPLATE_READ |
| POST | `/report-templates` | REPORT_TEMPLATE_MANAGE |
| PATCH | `/report-templates/{template_id}` | REPORT_TEMPLATE_MANAGE |
| GET | `/signatories` | SIGNATORY_READ |
| GET | `/signatories/{signatory_id}` | SIGNATORY_READ |
| POST | `/signatories` | SIGNATORY_MANAGE |
| PATCH | `/signatories/{signatory_id}` | SIGNATORY_MANAGE |
| POST | `/lab-orders/{order_id}/reports` | REPORT_GENERATE |
| GET | `/reports` | REPORT_READ |
| GET | `/reports/{report_id}` | REPORT_READ |
| GET | `/lab-orders/{order_id}/reports` | REPORT_READ |
| GET | `/reports/{report_id}/signatories` | REPORT_READ |
| POST | `/reports/{report_id}/signatories` | SIGNATORY_MANAGE |
| POST | `/reports/{report_id}/sign` | REPORT_SIGN |
| POST | `/reports/{report_id}/approve` | REPORT_APPROVE |

The existing idempotent `app.cli.bootstrap_permissions` inserts the ten new
permission codes above, making 49 catalog entries. It preserves existing metadata
and assignments and does not grant the new permissions to roles automatically.
SYSTEM_ADMIN keeps its permission bypass, but cannot bypass signing identity.
Permissions are not seeded through Alembic.

Errors follow existing conventions: 401 missing authentication, 403 permission,
CSRF or signing identity failure, 404 missing path entity or unconfigured facility,
422 invalid input or missing related entity, 409 lifecycle/configuration/integrity
conflict, and generic 503 for unexpected database failures. Unique code conflicts
return 409. Unknown inputs and server-owned fields are rejected without echoing
submitted values.

## Facility configuration

The application represents one issuing RHU. GET returns a controlled 404 when
unconfigured. PATCH updates the one existing record, never creates it. POST is
provided because there is no existing first-time facility bootstrap: it works
only when no facility exists, and uses fixed server-owned `facility_id=1`.
Competing first-time requests cannot create multiple facilities because the
primary key is the final arbiter. Existing profiles with another ID remain usable;
the service does not renumber them. Multiple legacy profiles cause a controlled
409 requiring administrator correction, rather than silently choosing a facility.
This singleton policy applies to these service APIs; independent database writers
must follow it too.

Writable fields are facility_name, facility_type, address, contact_number, email,
website and logo_path. Names and metadata are bounded by existing column lengths;
email is validated. facility_id and timestamps are server-owned. logo_path is
metadata only: no file reading, upload, fetching or image processing occurs.

Facility summaries are live references, because the schema has no report facility
snapshot. Facility edits can therefore change the summary shown for an approved
report before Phase 5B rendering. This is a known schema limitation, not a frozen
historical facility claim. Phase 5B must settle facility/rendering policy before
release; its final artifact will preserve what was actually rendered.

## Report templates

Create/read/list/PATCH supports template_code, template_name, nullable panel_id,
header_title, section_title, clinical_note, footer_note, medico_legal_note and
is_active. A supplied panel must exist. NULL means a general template. Template
codes are unique; duplicate creation or update returns 409. Deactivate with
is_active=false. Template text is configuration, not new snapshot columns.

Lists use page >= 1, page_size 1–100 (default 20), search over template code/name,
and panel_id/is_active filters. An omitted panel_id filter includes both general
and panel templates. There is no special null-only filter. A panel template is a
layout reference, not a result filter: selecting one never drops results from a
mixed order. template_id may be omitted/null at generation for the general layout
reference. There is no PDF renderer in this phase.

A template referenced by an APPROVED report is protected against changes to every
field except is_active. The same protection covers existing RELEASED/REVOKED
records. No-op writes remain safe. Create a new code/profile for rendering changes.
Deactivation affects future selection only. Generated reports still refer to
mutable template text until approval; edits before approval can affect their
future rendering. Template detail is explicitly the selected live reference.

## Signatory profiles and assignment

Profiles contain staff_id, signature_image_path, license_number_snapshot and
is_active. Staff must exist. An active profile requires active staff; an inactive
profile can be created for inactive staff. Multiple profiles per staff are allowed.
Lists support pagination, staff_id/is_active filters and license snapshot search.
No credentials, staff contact information or authentication secrets are included.
Signature paths are metadata only; the API does not upload or read image files.

Assignments require a GENERATED report, active profile and active staff. Allowed
types are exactly LAB_IN_CHARGE, MEDICAL_TECHNOLOGIST and PATHOLOGIST. sort_order
is an integer (default 1). The same signatory/type combination cannot be assigned
twice; different types are distinct assignments. signed_at starts NULL. Assignment
reads sort by sort_order then report_signatory_id.

Once used by an approved report, the profile's staff_id, license_number_snapshot
and signature_image_path cannot be changed. Deactivation remains available for
future use. As an additional identity safeguard, these display fields freeze as
soon as any assignment is signed, even while its report is GENERATED: rebinding a
signed profile would otherwise turn a prior signature into another person's.
Create a new profile when these fields need to change.

The schema does not snapshot the signatory's name into REPORT_SIGNATORY. The
returned staff_name is formatted from current STAFF; existing staff identity APIs
can still update that name. Likewise, a path is not immutable image content.
Historical profile protection does not claim to solve those limitations. Phase 5B
must preserve the rendered signature/name in the immutable final PDF.

## Generation prerequisites and one initial version

POST `/lab-orders/{order_id}/reports` accepts only template_id and remarks.
The service requires:

1. An existing COMPLETED order, not CANCELLED.
2. At least one non-cancelled order item, all such items COMPLETED.
3. Exactly one result per non-cancelled item, all VERIFIED, with review and
   verification actor/timestamp provenance populated. Ambiguous result histories,
   missing results and DRAFT/REVIEWED results cause 409.
4. One issuing facility and an existing active template if supplied.
5. Consistent selected range/test association and completed source panel linkage
   where a panel exists.
6. No prior report for this order, regardless of its status. Repeat generation
   returns 409 and points to the future revision workflow.

All non-cancelled requested items are reportable, including optional panel members
already expanded into the order and separate occurrences of overlapping tests.
Cancelled items are omitted; test IDs are never deduplicated across requested
items. Panel configuration changes never remove a verified requested result.

The server writes version_no=1, supersedes_report_id=NULL, status=GENERATED,
generated_by_user_id and generated_at. report_code is
`RPT-YYYYMMDD-` followed by 16 cryptographically random hexadecimal characters:
29 characters, 64 random bits, no patient identity. The database UNIQUE constraint
is final collision protection; an improbable collision returns controlled 409 and
rolls back the entire request, allowing the caller to retry.

LAB_REPORT, exactly one REPORT_PATIENT_SNAPSHOT, all REPORT_RESULT_ITEM rows and
REPORT_GENERATE audit commit in one transaction. Any validation, snapshot, audit
or commit failure rolls everything back. LAB_RESULT_ITEM remains independent.

## Patient and result snapshots

The centralized printable_name helper combines first/middle/last/suffix, removes
extra whitespace and preserves supplied capitalization. Patient code/name, birth
date, sex and requesting physician's formatted name are stored at generation.
Absent physician means NULL. Historical reads use the snapshot, never reconstruct
names from today's demographics.

age_at_report is completed full years relative to the UTC date of generated_at,
with the birthday comparison made using month/day. A February 29 birthday reaches
its next full year on March 1 in a non-leap year. NULL birth date produces NULL age;
a future birth date is rejected. Age is stored only in REPORT_PATIENT_SNAPSHOT;
PATIENT has no age column. This is intentionally different from Phase 4B's
fractional-year reference-range selection.

Each line stores the verified result's exact display result_value, canonical flag
(or NULL), current test_name and these printable values:

| Snapshot | Rule |
| --- | --- |
| unit_snapshot | Selected range unit when non-NULL; otherwise test default_unit; otherwise NULL |
| reference_range_snapshot | Format the already selected range; no new range resolution |
| panel_id_snapshot | Source ORDER_PANEL.panel_id, otherwise NULL |
| section_name_snapshot | Current matching PANEL_TEST/PANEL_SECTION name when safely resolvable, otherwise NULL |

The result display value is never reconstructed from numeric_value. The flag is
never recalculated during generation. An inactive or historically selected range
is still the selected range: its pointer is preserved rather than selecting a
new range. The printable range reflects its configuration at generation time,
not necessarily the thresholds as they existed at result entry. Later catalog,
range and demographic changes do not mutate the stored printable snapshots.

NUMERIC ranges use Decimal fixed-point formatting with unnecessary fractional
zeros removed. Both normal bounds print `13 - 17` or `12.5 - 16.5`; high-only prints
`<= 200`; low-only prints `>= 5`. Inclusive one-sided notation matches Phase 4B's
NORMAL-at-equality rule. Zero remains a valid bound. No normal bounds means NULL.
TEXT/POS_NEG use qualitative_normal. No selected range means NULL.

Ordering is deterministic: panel groups first in source order_panel_id order,
then individual requests; within a group use PANEL_TEST.sort_order when available,
otherwise TEST_CATALOG.default_sort_order, otherwise order_item_id. Test default
order and stable order_item_id break ties. Store the resulting contiguous integers
1..N. The order schema has no separate group ordering field or historical section
snapshot. Current generation-time panel organization is therefore a documented
limitation. Removed membership/section configuration produces a NULL section and
stable fallback order, while retaining the verified result.

## Reads and lifecycle integrity

Report lists use page/page_size, literal search across report_code, order_code and
patient code/name snapshots, order_id, status, and inclusive UTC generated-date
filters date_from/date_to. Reversed date intervals are invalid. Results sort by
report_id descending. Out-of-range pages return empty items. The order-specific
list requires an existing order and returns the same pagination envelope.

Detail returns report metadata and actor/timestamp history fields, facility
summary, selected template reference, patient snapshot, ordered result snapshots
and signatories. The phase does not fetch account credentials. Configuration
summaries are distinguished from stored printable patient/result snapshots.

There are no snapshot CRUD endpoints, including while GENERATED. APPROVED reports
cannot receive assignments, signatures or another approval. Existing RELEASED and
REVOKED reports are also read-only to these operations. Source VERIFIED results
remain uneditable through the Phase 4B API. Incorrect clinical data needs a future
controlled correction/revision workflow; this phase does not silently overwrite it.

## Explicit signing and approval

Signing requires REPORT_SIGN and a target assignment in the specified GENERATED
report. The authenticated user must be connected through STAFF_ACCOUNT_LINK to
exactly the STAFF referenced by that assignment's current active SIGNATORY.
Permission alone, including SYSTEM_ADMIN, cannot sign for someone else. A valid
operation writes only that assignment's server signed_at and audit event. A
repeated signature returns controlled 409 and preserves the original timestamp.
Every assignment, including multiple types for the same profile, is explicit.

Approval requires REPORT_APPROVE. The approving account need not be a signatory
and need not have a staff link. The academic prototype policy requires **at least
one assigned signatory and all assigned signatories signed**. It does not require
any particular clinical type; this is an application policy, not a universal
laboratory regulation. Previously signed assignments remain evidence if the
profile is later deactivated; deactivation prevents new assignment/signing.

Approval locks and rechecks the order, current verified sources and report. It
requires the patient snapshot and a nonempty, complete, duplicate-free result
snapshot set matching all reportable sources, contiguous sort positions, correct
source panel IDs, exact stored result/flag agreement and nonblank names/values.
It checks snapshot age against snapshot birth date and report generation date,
not against today's patient. Inconsistent prior approval/release/revocation/PDF
metadata blocks approval. It does not rewrite patient, test, unit or range
snapshots from mutable master data.

A successful approval writes report_status=APPROVED, approved_by_user_id and
approved_at with its audit. It never writes release fields, REPORT_VERIFICATION,
PDF/QR/hash/token or blockchain rows. There is no release/revoke route.

## Transactions and concurrency

Services use the existing explicit mutation context: authentication may have
already started the request transaction; the service owns its single commit and
rolls back on any error. Response contracts are built before committing. MySQL
1213 deadlocks retry the entire rolled-back mutation, at most three attempts,
using the established helper. Other failures are not automatically replayed.

Generation locks LAB_ORDER with FOR UPDATE, the same parent used by Phase 4A/4B.
Its report-existence query is a current locking read. Thus even when concurrent
requests began with an empty repeatable-read snapshot, the second request observes
the first report after acquiring the order lock. No UNIQUE(order_id, version_no)
constraint is added. Approval takes order then report locks; assignment and signing
take report locks. Duplicate assignments, competing signatures and competing
approval transitions are serialized even when their child set was initially empty.

All mutation decisions and snapshot source/configuration reads use current locks
and refresh ORM objects rather than trusting authentication's old MySQL snapshot.
Panel reads coordinate with existing membership updates. Template/signatory edits
lock their profile and use current locking reads of historical report references;
approval locks the same configuration before committing. Interleaving operations
may deadlock due to opposite parent/reference paths, which is handled by the
existing whole-transaction retry policy. Approved history cannot slip through a
stale snapshot after a successful retry.

All future service writers must honor these lock conventions; ordinary direct SQL
is outside application immutability protection. Native tests use MySQL REPEATABLE
READ and intentionally pre-open stale snapshots before contending.

## Audit events

Successful operations write these actions to the existing AUDIT_LOG:

- FACILITY_PROFILE_CREATE (first-time setup), FACILITY_PROFILE_UPDATE
- REPORT_TEMPLATE_CREATE, REPORT_TEMPLATE_UPDATE
- SIGNATORY_CREATE, SIGNATORY_UPDATE
- REPORT_GENERATE, REPORT_SIGNATORY_ASSIGN, REPORT_SIGN, REPORT_APPROVE

Events record actor, server timestamp, validated IP, entity/record IDs and minimal
changed-field names, identifiers, counts or status transitions. Patient demographics,
full laboratory values, remarks, template prose, signature image data/paths,
license values, passwords and session/CSRF secrets are not duplicated in audit
JSON. Audit failure rolls back the business operation.

## Synthetic API examples

Use an authorized synthetic session. Set the IDs from actual setup responses;
never assume sample IDs exist. The order must first complete Phase 4B verification.
These calls do not release a report. CSRF comes from the current session's cookie.

```bash
LABCHAIN_URL=https://labchain.online
LABCHAIN_JAR=/tmp/labchain-synthetic.cookies
# Set LABCHAIN_CSRF from this session's rhu_csrf cookie.
# Set LABCHAIN_ORDER_ID and LABCHAIN_STAFF_ID from synthetic setup.

# First-time setup only; use PATCH for an existing facility.
curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"facility_name":"Synthetic RHU","facility_type":"RHU"}' \
  "$LABCHAIN_URL/api/v1/facility-profile"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"template_code":"SYNTH-GENERAL-V1","template_name":"Synthetic general","panel_id":null}' \
  "$LABCHAIN_URL/api/v1/report-templates"
# Set LABCHAIN_TEMPLATE_ID from the response.

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"staff_id\":$LABCHAIN_STAFF_ID,\"license_number_snapshot\":\"SYNTHETIC\"}" \
  "$LABCHAIN_URL/api/v1/signatories"
# Set LABCHAIN_SIGNATORY_ID from the response.

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"template_id\":$LABCHAIN_TEMPLATE_ID,\"remarks\":null}" \
  "$LABCHAIN_URL/api/v1/lab-orders/$LABCHAIN_ORDER_ID/reports"
# Set LABCHAIN_REPORT_ID from the response.

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"signatory_id\":$LABCHAIN_SIGNATORY_ID,\"signatory_type\":\"MEDICAL_TECHNOLOGIST\",\"sort_order\":1}" \
  "$LABCHAIN_URL/api/v1/reports/$LABCHAIN_REPORT_ID/signatories"
# Set LABCHAIN_ASSIGNMENT_ID from the response.

# Use the session of the account linked to that exact STAFF identity.
curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"report_signatory_id\":$LABCHAIN_ASSIGNMENT_ID}" \
  "$LABCHAIN_URL/api/v1/reports/$LABCHAIN_REPORT_ID/sign"

# Use a session authorized for REPORT_APPROVE.
curl --fail-with-body -X POST -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" \
  "$LABCHAIN_URL/api/v1/reports/$LABCHAIN_REPORT_ID/approve"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  "$LABCHAIN_URL/api/v1/reports/$LABCHAIN_REPORT_ID"
curl --fail-with-body -b "$LABCHAIN_JAR" \
  "$LABCHAIN_URL/api/v1/reports?page=1&page_size=20&status=APPROVED"
```

## Verification and Hostinger deployment

Verified on 2026-09-16 with `.venv/bin/python -m pytest -vv -ra --tb=long`: **855 passed, 0 failed, 0 skipped in 623.20 seconds**. This includes 125 new API/service cases and 10 native MySQL scenarios. The two existing Starlette/httpx and AnyIO deprecation warnings remain. `pip check` passed; Alembic retains the single head `20260915_01`. All 23 tracked model, migration, deployment, environment-example and dependency files are byte-for-byte unchanged, with exactly five original migrations. The existing Phase 4A OpenAPI test now excludes the new order-report routes from its unchanged 15-operation Phase 4A assertion.

The tests use synthetic settings and block production networking. API tests use a
copied SQLite schema; native concurrency tests use the existing disposable MySQL
harness under `/tmp/rhu-phase3b-mysql-*`, a private Unix socket, `--no-defaults`,
`--skip-networking` and disabled MySQL X. Tests create/drop only disposable schemas.
Hosts without mysqld skip the native checks; such skips are not MySQL verification.

New coverage includes every route's authentication/permission/CSRF, setup/configuration
validation, generation prerequisites, snapshot preservation and formatting, explicit
identity-bound signing, approval integrity, immutable rendering/profile guards,
audit privacy, code collisions and injected snapshot/audit/commit failures.
Native probes cover concurrent generation, assignments, signing, approval and
facility setup; template update/approval races; stale source/configuration reads;
and rollback at every report lifecycle stage.

Run these exact commands as `rhuadmin` after the reviewed Phase 5A checkout has
been delivered to `/opt/rhu-labchain`. Run one command at a time and stop on error.
The restart uses the existing service definition; no service configuration changes
are required. These are deployment instructions, not development-time actions.

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip check
.venv/bin/python -m pytest -vv -ra --tb=long
.venv/bin/alembic heads
.venv/bin/alembic current
# Both must identify 20260915_01 before continuing.
.venv/bin/python -m app.cli.bootstrap_permissions
sudo systemctl restart rhu-labchain-node1
sudo systemctl is-active rhu-labchain-node1
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/health
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/ready
curl --fail --silent --show-error --max-time 15 https://labchain.online/openapi.json -o /tmp/labchain-phase5a-openapi.json
.venv/bin/python -c 'import json; p=json.load(open("/tmp/labchain-phase5a-openapi.json"))["paths"]; assert "post" in p["/api/v1/lab-orders/{order_id}/reports"]; assert "post" in p["/api/v1/reports/{report_id}/sign"]; assert "post" in p["/api/v1/reports/{report_id}/approve"]; assert "/api/v1/reports/{report_id}/release" not in p; print("Phase 5A OpenAPI verified")'
```

Do not run `alembic upgrade` for Phase 5A. No dependency installation is needed.
After bootstrapping, grant permissions deliberately to non-admin roles using the
established administrative process, configure the one issuing facility and set up
staff-linked signatories. No production .env, Nginx, Certbot, UFW or systemd file
changes are needed. Production permission bootstrap and restart are not performed
as part of this development task. Stop at Phase 5A.
