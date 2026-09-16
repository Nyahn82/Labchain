# Phase 3C — Laboratory master-data APIs

Phase 3C manages the nine existing Phase 2B laboratory configuration tables.
Individual tests remain in `TEST_CATALOG`; groups of tests remain in `TEST_PANEL`,
connected through `PANEL_TEST`. Sample mappings, sections, reference ranges and
interpretation rules retain their normalized tables. No models, schema or prior
migrations change. The single Alembic head remains `20260915_01`.

## Endpoints and permissions

All paths below start with `/api/v1/lab`. Every request uses the existing secure
server-side session. Every POST, PATCH and PUT additionally requires the
session-bound `X-CSRF-Token`. All GET operations require `LAB_MASTER_READ`.
An active `SYSTEM_ADMIN` bypasses permission checks while preserving session,
CSRF, validation and transaction requirements. Responses use `Cache-Control: no-store`.

| Resource | Create | Read | Update | Mutation permission |
| --- | --- | --- | --- | --- |
| Departments | POST `/departments` | GET `/departments`, `/departments/{department_id}` | PATCH `/departments/{department_id}` | `LAB_DEPARTMENT_MANAGE` |
| Sample types | POST `/sample-types` | GET `/sample-types`, `/sample-types/{sample_type_id}` | PATCH `/sample-types/{sample_type_id}` | `SAMPLE_TYPE_MANAGE` |
| Individual tests | POST `/tests` | GET `/tests`, `/tests/{test_id}` | PATCH `/tests/{test_id}` | `TEST_CATALOG_MANAGE` |
| Test/sample mappings | — | GET `/tests/{test_id}/sample-types` | PUT `/tests/{test_id}/sample-types` | `TEST_CATALOG_MANAGE` |
| Panels | POST `/panels` | GET `/panels`, `/panels/{panel_id}` | PATCH `/panels/{panel_id}` | `TEST_PANEL_MANAGE` |
| Panel sections | POST `/panels/{panel_id}/sections` | GET `/panels/{panel_id}/sections` | PATCH `/panels/{panel_id}/sections/{section_id}` | `TEST_PANEL_MANAGE` |
| Panel composition | — | GET `/panels/{panel_id}/tests` | PUT `/panels/{panel_id}/tests` | `TEST_PANEL_MANAGE` |
| Reference ranges | POST `/tests/{test_id}/reference-ranges` | GET `/tests/{test_id}/reference-ranges`, `/reference-ranges/{range_id}` | PATCH `/reference-ranges/{range_id}` | `REFERENCE_RANGE_MANAGE` |
| Interpretation rules | POST `/tests/{test_id}/interpretation-rules` | GET `/tests/{test_id}/interpretation-rules`, `/interpretation-rules/{rule_id}` | PATCH `/interpretation-rules/{rule_id}` | `INTERPRETATION_RULE_MANAGE` |
| Range selection helper | — | GET `/tests/{test_id}/reference-range?sex=M&age_years=32&as_of_date=2026-09-15` | — | — |

There are 32 method/path operations. Creates return 201; other successes return
200. There are no DELETE endpoints. Records with `is_active` are deactivated
through PATCH; existing references remain intact.

Errors follow Phase 3B: 401 unauthenticated, 403 missing permission or invalid
CSRF, 404 missing path entity, 409 duplicate or business conflict, 422 invalid
input or related entity, and generic 503 for unexpected database failures.
Database exception text and submitted request bodies are never echoed.

### Permission bootstrap

The existing idempotent permission catalog gains exactly seven codes:

```text
LAB_MASTER_READ
LAB_DEPARTMENT_MANAGE
SAMPLE_TYPE_MANAGE
TEST_CATALOG_MANAGE
TEST_PANEL_MANAGE
REFERENCE_RANGE_MANAGE
INTERPRETATION_RULE_MANAGE
```

Run `.venv/bin/python -m app.cli.bootstrap_permissions` once at deployment.
Repeated runs insert only missing codes and preserve names, descriptions and
role grants. The combined Phase 3B/3C catalog has 24 permissions. Bootstrap does
not grant them to roles automatically. SYSTEM_ADMIN needs no explicit grants;
other roles require deliberate administrative grant setup. Run only one
bootstrap at a time; a concurrent uniqueness failure rolls back and can be retried.

## Input and pagination conventions

Text is trimmed, nonblank when supplied, and bounded by the existing VARCHAR
limits. Nullable text can be cleared with null. TEXT fields accept up to 16,000
characters to fit MySQL TEXT with four-byte UTF-8. IDs are positive signed BIGINTs;
sort orders accept signed 32-bit integers. Enum values are exact and case-sensitive.
Unknown body fields and generated IDs are rejected. PATCH changes submitted
fields only, rejects null for required columns, and cannot change a child record's
parent. Empty PATCH is permitted and audited with no changed fields.

Departments, sample types, tests, panels, reference-range lists and rule lists
use Phase 3B pagination:

```json
{"items": [], "page": 1, "page_size": 20, "total": 0}
```

`page >= 1`; `page_size` defaults to 20 and is bounded to 1–100. Items are ordered
by ascending primary key. Total counts apply the filters before pagination;
out-of-range pages return an empty array. Search is a trimmed substring of up to
200 characters; SQL wildcard characters are escaped. Matching follows the database
collation and the existing case-insensitive search helper.

| List | Search fields | Optional exact filters |
| --- | --- | --- |
| Departments | department_code, department_name | is_active |
| Sample types | sample_name | is_active |
| Tests | test_code, test_name | department_id, result_type, is_active |
| Panels | panel_code, panel_name | department_id, is_active |
| Test reference ranges | — | is_active |
| Test interpretation rules | — | is_active |

Sample assignments, sections and panel members are complete configuration arrays.
They are also embedded in detail responses where applicable. Each PUT accepts
at most 1,000 members and requires its array field explicitly.

## Departments, sample types and tests

Department create requires `department_code` (30 characters) and
`department_name` (100); optional `description` and `is_active` (default true).
Duplicate department codes return 409, including on PATCH.

Sample type create requires `sample_name` (80); optional `description` and
`is_active` (default true). Duplicate names return 409. Referenced sample types
can be deactivated without destroying their mappings.

Test create requires `test_code` (30), `test_name` (150), `department_id`, and
`result_type` (`NUMERIC`, `TEXT`, `POS_NEG`). Optional fields are `default_unit`
(50), `methodology` (150), `default_sort_order` (nullable), and `is_active`
(default true). Duplicate test codes return 409. Department IDs must exist.

Creating or activating an active test, or moving an active test to a different
department, requires an active department (409 otherwise). Existing tests can
still be edited or deactivated after their department retires. Department
retirement does not cascade to existing tests. Inactive tests may be configured
under inactive departments. An unchanged department/activity field in PATCH does
not trigger a new activation check.

Detailed test GET returns the test fields, a safe `department` object and
`sample_types`, containing each mapping and a safe sample-type object. Dedicated
response schemas prevent SQLAlchemy internals from entering the response.

## Test/sample mappings

PUT replaces the complete mapping set atomically:

```json
{"sample_types": [{"sample_type_id": 1, "is_default": true}, {"sample_type_id": 2, "is_default": false}]}
```

The test and every sample type must exist. Duplicate IDs and more than one
`is_default: true` return 422. Zero defaults are allowed. An empty array is
allowed so a test can temporarily have no configured specimen type during setup.
Mappings can reference inactive sample types; the response exposes their activity
so administrators can review configuration. This phase implements no ordering or
specimen collection workflow that consumes them.

The service locks the test row, validates all members, replaces mappings and
writes its audit entry in one transaction. The database unique pair
`(test_id, sample_type_id)` remains intact. Responses are sorted by sample-type ID,
then mapping ID. Replacement may generate new association IDs; consumers should
identify a configured association by its test/sample pair.

## Panels, sections and composition

Panel create requires `panel_code` (30) and `panel_name` (120). Optional fields are
`department_id`, `description`, and `is_active` (default true). A supplied department
must exist; it may be inactive. PATCH may clear the department with null.
Duplicate panel codes return 409.

Section create requires `section_name` (120) and `sort_order`; `is_active` defaults
to true. The path panel must exist. PATCH verifies that the section belongs to
that panel and returns 404 for a cross-panel path. Section IDs and parent IDs are
immutable. Sections sort by `sort_order`, then `section_id`, including inactive
sections for administrative review.

Panel composition PUT is a complete replacement:

```json
{"tests": [{"test_id": 1, "section_id": null, "sort_order": 1, "is_required": true}, {"test_id": 2, "section_id": 5, "sort_order": 2, "is_required": true}]}
```

Every test must exist, test IDs must be unique, and a nonnull section MUST belong
to the SAME panel. Missing related rows and cross-panel sections return 422.
The service enforces this rule before deletion, alongside the unchanged database
foreign keys and unique `(panel_id, test_id)` constraint. Null sections are valid.
Empty composition is allowed during setup. Inactive tests and sections remain
configurable and visible; no active-workflow policy is invented in this phase.

The panel row is locked before section or composition writes. All members and
the audit event commit together. Replacement may generate new member IDs.
Panel detail returns metadata, ordered sections, and members with safe test
summaries. Member ordering is explicit:

1. Unsectioned tests first.
2. Section `sort_order`, then `section_id` for sectioned tests.
3. Member `sort_order`, then `panel_test_id` within each group.

## Reference-range configuration

Reference ranges remain separate from individual tests. Create requires `sex`
(`M`, `F`, `ANY`); all other fields are optional:

- `age_min`, `age_max`: nonnegative Decimal years, at most six digits/two decimals.
- `normal_low`, `normal_high`, `critical_low`, `critical_high`: Decimal thresholds,
  at most twelve digits/three decimals. Negative thresholds are allowed.
- `qualitative_normal`: up to 80 characters; `unit`: up to 50.
- `effective_from`, `effective_to`: nullable dates.
- `is_active`: default true.

NaN, infinity, excess precision and out-of-column-range values are rejected.
Decimal values remain Decimal in services and MySQL and serialize as JSON strings.
Send decimal strings to avoid rounding before the request reaches the server.
The resolver accepts finer age precision than the stored age bounds and does not
round the supplied age into a range.

Validation requires ordered age and date bounds, `normal_low <= normal_high`,
`critical_low <= normal_low`, `normal_high <= critical_high`, and
`critical_low <= critical_high` whenever the corresponding two values exist.
Zero is a supplied bound. PATCH validates the merged stored/submitted values,
so changing just one end cannot invert an interval. Numerical thresholds are not
required for TEXT/POS_NEG; qualitative text is not required for NUMERIC. These
APIs configure thresholds; they do not evaluate results.

### Overlap policy

Two active ranges conflict (409) when all of these are true:

- Same test.
- Same sex category.
- Age intervals intersect.
- Effective-date intervals intersect.

All boundaries are inclusive. Null means unbounded on that side. Consequently,
`age_max=18` and `age_min=18` overlap if the date windows intersect. Adjacent
windows must have distinct endpoints. Inactive ranges may overlap, but activation
must pass the check. Every edit that leaves a range active rechecks overlap,
excluding the edited row itself. M and F can each overlap ANY intentionally;
exact-sex precedence resolves those cases.

Range creates/updates lock the parent test before checking overlap. The overlap
query uses a current locking read, preventing a request's older MySQL REPEATABLE
READ snapshot from missing a concurrently committed range. This protects the
application write paths without schema changes. Direct database maintenance must
preserve the same invariant. Existing ambiguous configuration is not modified
silently.

### Reusable selection service

```python
resolve_reference_range(db, test_id, patient_sex, age_years, as_of_date)
```

**REFERENCE_RANGE selection uses test, sex, age and effective date, with exact
sex preferred over ANY.** Only active ranges matching all four criteria are
candidates. Null age/date bounds are open-ended and boundaries are inclusive.
For M or F, an applicable exact-sex range takes priority; otherwise ANY is used.
For `Patient.sex = Other`, only ANY applies. An exact-sex range outside the age
or date window does not suppress an applicable ANY fallback.

The reusable service returns a range or `None` for no match. A missing test
returns a controlled 404. Multiple candidates at the winning precedence raise
`ReferenceRangeAmbiguityError` (409) and log only test/range configuration IDs.
It never selects an arbitrary row. Ambiguous ANY fallbacks do not prevent use of
a single applicable exact-sex range.

The protected helper endpoint requires `sex=M|F|Other`, nonnegative finite
`age_years`, and `as_of_date`. It returns the selected range or 404 for no match,
and rejects unknown query fields including `patient_id`. It accepts no patient
identifier, reads no patient data, and stores no age. Future patient-aware callers
must calculate age from `PATIENT.birth_date` as of the relevant date. No result
flagging or clinical diagnosis logic is implemented.

## Interpretation-rule safety boundary

Create requires `flag`: `NORMAL`, `LOW`, `HIGH`, `CRITICAL_LOW`, `CRITICAL_HIGH`,
or `ABNORMAL`. Optional fields are `interpretation_text`, `possible_causes`,
`recommendation` and `is_active` (default true). Text may be cleared with null.
The unchanged `(test_id, flag)` uniqueness constraint covers both active and
inactive rows; duplicates on create or PATCH return 409. PATCH can change a flag
but cannot move a rule to a different test.

These fields store previously approved GENERAL explanatory statements. They are
not medical diagnoses. The API does not approve or generate clinical content,
prescribe treatment, generate prescriptions, or automatically interpret a patient
result. Content review and approval remain an administrative responsibility.

## Auditing and transactions

Successful mutations emit these existing-AUDIT_LOG actions:

```text
LAB_DEPARTMENT_CREATE       LAB_DEPARTMENT_UPDATE
SAMPLE_TYPE_CREATE          SAMPLE_TYPE_UPDATE
TEST_CREATE                 TEST_UPDATE
TEST_SAMPLE_TYPES_UPDATE
PANEL_CREATE                PANEL_UPDATE
PANEL_SECTION_CREATE        PANEL_SECTION_UPDATE
PANEL_TESTS_UPDATE
REFERENCE_RANGE_CREATE      REFERENCE_RANGE_UPDATE
INTERPRETATION_RULE_CREATE  INTERPRETATION_RULE_UPDATE
```

Events contain actor, entity, record ID, validated client IP and UTC time. Scalar
mutations record changed field names; replacements record compact association IDs
and the selected default/sections. Complete request objects, explanatory text,
credentials and session values are never copied into audit JSON.

Authentication begins the request's transaction. The existing mutation context
owns one commit, including the audit write, and rolls back on every exception.
Responses are validated before commit. Failed validation, database insertion,
audit or commit cannot leave partially replaced configuration. Per-test or
per-panel row locks serialize replacements across workers. Current shared reads
validate related entities and build replacement responses without upgrading
shared catalog locks unnecessarily. InnoDB can still deadlock on shared empty
index gaps for different parents. MySQL deadlock-victim error 1213 retries the
entire rolled-back mutation up to three attempts within the authorized request.
Each successful request commits exactly one audit event. Other errors and
exhausted retries return the existing generic database failure response; an
uncertain connection/commit failure is never retried automatically.

## Synthetic examples

All values below are illustrative synthetic configuration, not clinical guidance.
Use a synthetic authorized session and set its current CSRF token from the
`rhu_csrf` cookie. IDs must come from actual synthetic create responses, not from
assumptions about production IDs. Every later request uses those IDs.

```bash
LABCHAIN_URL=https://labchain.online
LABCHAIN_JAR=/tmp/labchain-synthetic.cookies
# Set LABCHAIN_CSRF from the current synthetic session's rhu_csrf cookie.

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"department_code":"SYNTH-3C","department_name":"Synthetic laboratory"}' \
  "$LABCHAIN_URL/api/v1/lab/departments"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"sample_name":"Synthetic sample 3C"}' \
  "$LABCHAIN_URL/api/v1/lab/sample-types"

# Set LABCHAIN_DEPARTMENT_ID and LABCHAIN_SAMPLE_ID from the responses above.
curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"test_code\":\"SYNTH-TEST-3C\",\"test_name\":\"Synthetic measurement\",\"department_id\":$LABCHAIN_DEPARTMENT_ID,\"result_type\":\"NUMERIC\"}" \
  "$LABCHAIN_URL/api/v1/lab/tests"

# Set LABCHAIN_TEST_ID from that response.
curl --fail-with-body -X PUT -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d "{\"sample_types\":[{\"sample_type_id\":$LABCHAIN_SAMPLE_ID,\"is_default\":true}]}" \
  "$LABCHAIN_URL/api/v1/lab/tests/$LABCHAIN_TEST_ID/sample-types"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"sex":"ANY","age_min":"0.00","normal_low":"1.123","normal_high":"9.987","unit":"synthetic-unit"}' \
  "$LABCHAIN_URL/api/v1/lab/tests/$LABCHAIN_TEST_ID/reference-ranges"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  "$LABCHAIN_URL/api/v1/lab/tests/$LABCHAIN_TEST_ID/reference-range?sex=Other&age_years=32&as_of_date=2026-09-15"

curl --fail-with-body -b "$LABCHAIN_JAR" \
  -H "X-CSRF-Token: $LABCHAIN_CSRF" -H 'Content-Type: application/json' \
  -d '{"flag":"NORMAL","interpretation_text":"Synthetic approved general explanation."}' \
  "$LABCHAIN_URL/api/v1/lab/tests/$LABCHAIN_TEST_ID/interpretation-rules"
```

## Verification and Hostinger deployment

Resumed-work verification on 2026-09-15: the saved Phase 3C implementation was
reviewed against the handoff and the complete suite was rerun: **402 passed,
0 skipped**, including 127 new Phase 3C tests (117 API/service tests and 10
disposable-MySQL scenarios). The complete run took 205.71 seconds. No additional
application changes were needed. Two existing Starlette/httpx and AnyIO
deprecation warnings remain. `pip check` passed; the single Alembic head is `20260915_01`. All 22 tracked
model, migration, deployment and environment-example files checked against HEAD
were byte-for-byte unchanged. No new migration exists. Production deployment was
not executed.

Run from the reviewed Phase 3C checkout already delivered to `/opt/rhu-labchain`
as `rhuadmin`. Execute one command at a time and stop on failure. There are no
new dependencies or migrations. The commands below are deployment instructions;
implementation/testing does not bootstrap production permissions or restart the
production service.

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/alembic heads
.venv/bin/alembic current
# Both must identify 20260915_01 before continuing.
.venv/bin/python -m app.cli.bootstrap_permissions
sudo systemctl restart rhu-labchain-node1
sudo systemctl is-active rhu-labchain-node1
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/health
curl --fail --silent --show-error --max-time 15 https://labchain.online/api/v1/ready
curl --fail --silent --show-error --max-time 15 https://labchain.online/openapi.json -o /tmp/labchain-phase3c-openapi.json
.venv/bin/python -c 'import json; p=json.load(open("/tmp/labchain-phase3c-openapi.json"))["paths"]; assert "/api/v1/lab/tests/{test_id}/reference-range" in p; print("Phase 3C OpenAPI verified")'
```

Do not run `alembic upgrade` for Phase 3C. Production `.env`, Nginx, Certbot, UFW
and systemd definitions are unchanged. The restart above loads reviewed code
using the existing service definition.

The complete suite includes Phase 2 model/frozen-migration checks, Phase 3A auth,
Phase 3B APIs/concurrency, health/readiness/OpenAPI, and Phase 3C HTTPS tests with
synthetic SQLite data. New MySQL probes check competing range creation,
activation and edits, atomic replacements, shared references across different
parents, native Decimal precision and audit-failure rollback under REPEATABLE READ.

MySQL tests start disposable instances under `/tmp/rhu-phase3b-mysql-*` using the
existing harness, an isolated data directory and Unix socket, `--no-defaults`,
`--skip-networking` and MySQL X disabled. They clean up the temporary database and
server afterward. They never connect to production MySQL. Tests explicitly skip
MySQL probes when `mysqld` is unavailable; those skips must not be described as
successful MySQL verification. Other tests block network connections and substitute
synthetic configuration before importing the application.

Phase 3C ends here. Orders, panel order expansion, patient activation, specimens,
payments, results/flags, reviews, reports/PDF/QR, blockchain and dashboards are
outside this implementation.
