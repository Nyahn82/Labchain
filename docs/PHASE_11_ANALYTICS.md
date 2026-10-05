# Phase 11 — Laboratory analytics and operational insights

Implementation only. No production queries or data changes were needed for this
feature. No production migrations, grants, bootstrap commands, service restarts,
frontend deployment, commits or pushes were performed. Synthetic data exists only
in disposable automated test databases.

## Architecture and access

`/#/administration/analytics` is an administration dashboard backed by eight
independent, read-only SQL aggregate endpoints. Each section has its own loading,
error and retry behavior. One applied date range/grain drives all sections. Normal
workspace links retain their existing RBAC and do not invent unsupported filters.

Every endpoint requires **ANALYTICS_VIEW** through the existing cookie-session
permission dependency. SYSTEM_ADMIN retains its normal bypass. Patient-role and
patient-linked actors are explicitly excluded even if accidentally granted the
permission. The new catalog entry is metadata only; no grants or database
permission records were created. Private API responses use `Cache-Control: no-store`.

All endpoints are GET under `/api/v1/admin/analytics`:

| Suffix | Contents |
| --- | --- |
| `/overview` | Eight headline KPIs and previous-period comparisons |
| `/patients` | Registration, served and returning patient trends |
| `/orders` | Order arrivals, current cohort status, cancellation metrics |
| `/tests` | Individual item demand, panels and department workload |
| `/specimens` | Registration/collection/receipt, rejection events and reasons |
| `/reports` | Report-version lifecycle, result events/status, six TAT stages |
| `/operations` | Physicians/facilities, arrival weekday/hour, safe payment summaries |
| `/system` | Authentication and application outbox aggregates only |

Request example:
`GET /api/v1/admin/analytics/overview?date_from=2026-10-01&date_to=2026-10-31&grain=auto&top_n=10`

The shared aggregate-only response contains `range`, `metrics`, `series`,
`breakdowns`, `turnaround`, and `notes`. There are no patient, report-content or
session-record serializers. Metric definitions travel with the data and are
available through the UI's Definition controls and Metric definitions panel.

## Exact model and table sources

| ORM model | Actual table | Analytics use |
| --- | --- | --- |
| Patient | patient | Registration timestamp; IDs used only inside distinct aggregates |
| LabOrder | lab_order | Order creation cohort, patient encounters, status, physician, arrivals |
| LabOrderItem | lab_order_item | Individual requested test rows; never a guessed lab_order_test table |
| OrderPanel | order_panel | Separate panel request counts |
| TestCatalog | test_catalog | Test code/name and department relationship |
| TestPanel | test_panel | Panel name |
| LabDepartment | lab_department | Department code/name |
| Specimen | specimen | created_at, collected_at, received_at, current state |
| SpecimenRejection | specimen_rejection | rejected_at, reason and recollection flag |
| RejectionReason | rejection_reason | Operational reason name |
| LabResultItem | lab_result_item | encoded_at, reviewed_at, verified_at, status and exact specimen link |
| LabReport | lab_report | generated_at, approved_at, released_at, revoked_at and order relationship |
| ReportResultItem | report_result_item | Exact report/result links for review-to-approval TAT; no snapshot values |
| RequestingPhysician | requesting_physician | Operational name, facility link |
| ReferringFacility | referring_facility | Operational facility name |
| LabPayment | lab_payment | Latest recorded state/amount by recorded_at and payment_id |
| LoginLog | login_log | login_time and SUCCESS/FAILED aggregates |
| StaffAccountLink / PatientAccountLink | staff_account_link / patient_account_link | Current account-type classification only |
| AuthSession / UserAccount | auth_session / user_account | Current active-session count, no session details |
| BlockchainEvent | blockchain_event | Created cohort, current event status and confirmed_at latency |

The actual model includes collected_at, verified_at and revoked_at, so those real
events are used. There is **no processed_at**, no persisted QC acceptance decision
timestamp, and no paid_at. None are inferred from updated_at.

## Dates, timezone, grain and comparisons

Application services use naive UTC DATETIME values; no facility timezone is
configured. Analytics consistently interprets those timestamps as UTC. Responses
state `timezone: UTC` and `week_starts_on: Monday`. Browser-local dates/timezones
are not used to group or select records. Frontend presets use UTC calendar math.

`date_from` and `date_to` must be ISO calendar dates (`YYYY-MM-DD`). Both selected
days are inclusive: SQL predicates are `timestamp >= from 00:00 UTC` and
`timestamp < midnight after date_to`. Timestamp strings with offsets or times are
rejected rather than silently coerced to dates. Inputs must be ordered and between
1970-01-01 and 2100-12-31, with a maximum of 3,660 days. Future ranges are permitted
and simply have no recorded activity where appropriate.

Supported grains: day, week, month, quarter, year, auto. Buckets align to calendar
boundaries; weeks start Monday, quarters start Jan/Apr/Jul/Oct. The first/last bucket
may be partial and is clipped by the selected range predicate. Its displayed date
is the actual calendar bucket start, which can precede date_from.

Auto uses day for <=31 days, week for <=180, month for <=730, quarter for <=1,460,
and year beyond that. Any request producing more than 120 buckets is rejected;
the user must choose a coarser grain. Missing aggregate buckets are filled with
zeros; these are absence-of-record counts, not synthetic clinical activity.

Comparison uses the immediately preceding **equal number of UTC calendar days**.
For Oct 1–31, the previous range is Aug 31–Sep 30 (31 days), not a calendar-month
shortcut. Each headline returns current `value`, `previous_value`,
`absolute_change`, `percent_change`, and `compared`. Percentage is
`100 * (current - previous) / previous`; it is null when the baseline is zero or
missing. Missing TAT samples produce null values/changes, not a fabricated zero.

## Headline and patient definitions

- **New patient registrations:** Patient.created_at in range. This measures
  registration, not portal account creation and not necessarily patients served.
- **Patients served:** distinct patient IDs on orders created in range whose
  current status is not CANCELLED.
- **Returning patients:** patients served in range with at least one non-cancelled
  order created before its start. A correlated SQL EXISTS establishes the earlier
  encounter; an old registration alone does not qualify.
- **Orders created:** all LabOrder rows created in range, including cancelled.
- **Tests requested:** all LabOrderItem rows on period-created orders, including
  cancelled rows and individual tests expanded from panels.
- **Specimens registered:** Specimen.created_at in range.
- **Report versions released:** LabReport.released_at in range, including versions
  subsequently revoked. Revisions are separate report versions.
- **Average order-to-release TAT:** valid creation-to-release intervals per report
  version, with completion in range. See eligibility below.

Patient trend distinctness is per bucket. Returning trend checks for a qualifying
order before that bucket's start, clipped to date_from for the first bucket.
Consequently, served/returning bucket counts **must not be summed** to obtain the
period's distinct headline. A patient can appear in multiple buckets.

## Orders, requested tests and departments

Order status distribution is the **current status of orders created in range**,
not a historical transition timeline. Non-cancelled and cancelled counts partition
that cohort. Cancellation rate is currently CANCELLED / all period-created orders;
zero denominator produces null.

Test demand counts persisted item rows exactly once. No join to PanelTest is used;
there is no duplicate count from panel membership. OrderPanel rows are a separate
panel-request metric. Demand deliberately includes cancelled items/orders to show
requests received; this differs from the non-cancelled served-patient definition.

Top tests, panels, physicians, facilities and rejection reasons default to 10,
maximum 20 (`top_n`). Only requested tests appear; unused catalog tests are not
misrepresented as a meaningful low-volume ranking. Ties use stable entity IDs.

The common ranking schema maps top-test `key` to its test_id (string form), `code`
to test_code, `label` to test_name, `department` to department name, `count` to
request_count, and `share` to percent of all requested tests in the cohort.
`other_count` preserves the remainder omitted by top-N.

Department workload uses TestCatalog.department_id and one count per requested
test item, never one per order. Its key/code/label identify the department.
`count` is tests_requested; `drafted`, `reviewed`, `verified` are current result-row
state counts for the cohort's items. Results are first aggregated per order item,
so multiple result rows cannot multiply the requested-test count. The dashboard
shows up to 20 departments plus the omitted workload total.

## Specimens and rejections

Registered, collected and received counts use their corresponding real timestamps
independently. Current specimen-status distribution uses the registration cohort.
“Registered specimens currently processed” counts PROCESSED among that cohort;
there is no claim of a processed-event date.

Rejected specimens means distinct specimen IDs with a SpecimenRejection event in
range. Rejection-event count/trend and reason rankings count events, including
multiple events for one specimen. Recollection-required count counts flagged
rejection events; its rate is flagged / all rejection events in range.

There is no trustworthy accepted-QC denominator. The displayed metric is
**rejections per 100 registered specimens**:

`100 * distinct specimens rejected in range / specimens registered in range`.

These are different cohorts. The ratio can exceed 100 and is not a QC rejection
probability or acceptance rate. A zero registration count gives null. The UI and
API definition state this explicitly.

## Results, reports and TAT

Result total/status cohort uses encoded_at. Reviewed and verified counts/trends
use their real reviewed_at and verified_at, independently of encoding date.
No result values, flags, clinical remarks or patient identities are selected.

Generated/approved/released/revoked report counts and trends each use their own
persisted event timestamp. They count versions, including superseded/revoked
versions with those events. Events can occur in a different period from generation.

Each TAT returns average_seconds, sample_count, excluded_count and candidate_count.
SQL AVG is used; no raw records are loaded into Python for a median. Candidates
have an end timestamp in range, plus incomplete or negative stages whose start is
in range. Missing starts are counted as exclusions when the end falls in range.
Valid samples require both endpoints, nonnegative elapsed time and stage-specific
sequence checks. Incomplete samples do not become zero-duration observations.

| Stage | Sample unit and additional checks |
| --- | --- |
| Order created → specimen collected | One specimen; order creation <= specimen registration <= collection |
| Specimen collected → received | One specimen; registration <= collection <= receipt |
| Specimen received → result reviewed | One result, exact specimen_id, same order as the result item; registration <= collection <= receipt <= encoding <= review |
| Last linked result review → report approved | One report version, latest review across persisted ReportResultItem links; all links reviewed after encoding, latest review <= generation <= approval |
| Report approved → released | One report version; generation <= approval <= release |
| Order created → report released | One report version; order creation <= generation <= approval <= release |

Missing links and invalid sequences are excluded and counted. With zero eligible
samples the average is null. Results appear in seconds/minutes/hours/days in the
UI. Report revisions contribute additional version samples, not unique-order TAT.

## Referrals, order arrival patterns and payments

Physician/facility rankings use all orders created in range, including cancelled.
Missing physician or facility joins remain “Direct / Not specified”; bounded top-N
rankings include an Other total rather than silently losing the denominator.
Attribution uses the current physician-to-facility association; no historical
referral snapshot is claimed. Only names/codes needed for operations are returned,
not phone, email, address or licensing details.

Order arrival patterns group created_at by UTC weekday (Monday first) and hour.
They always have at most 7 and 24 categories. They measure order registration,
**not specimen-processing workload**.

LabPayment is append-only payment history. Summing all historical rows would double
count changing records. Analytics selects exactly one latest record per selected
order by recorded_at, breaking ties by payment_id. The current payment-status
breakdown includes NOT_RECORDED for orders with no entry. The amount metric sums
non-null amounts from those latest records across all statuses; an empty/all-null
set is null. No currency is assumed because the schema does not specify one.
This is **not accounting revenue**, may include unpaid/free/waived/subsidized
records, and can reflect a latest entry recorded after the selected order period.
There is no paid_at, so there is no revenue-by-date chart.

## Authentication and blockchain summaries

Login success/failure count LoginLog rows by login_time; failure rate divides
FAILED by all such attempts. The account-type breakdown uses current links,
PATIENT before STAFF, otherwise SYSTEM/UNKNOWN (including unknown login attempts).
The separate **Active sessions now** metric is an explicitly labeled live snapshot
of unrevoked, unexpired sessions for ACTIVE accounts, independent of date range.
No usernames, attempted usernames, IPs, agents or session IDs are returned.

Anchors created and the status breakdown use BlockchainEvent.created_at in range.
Confirmation rate is current CONFIRMED / that created cohort. Latency averages
created_at → confirmed_at for currently confirmed events in the cohort, even if
confirmation was later than the selected range. Missing/negative intervals are
excluded with counts. This is application outbox evidence, not live Fabric health.
No peer probes, hashes, payloads, transaction IDs or explorer content are duplicated.
Authorized links lead to the separate Authentication Activity and Blockchain Monitor.

## SQL, indexes, bounded work and privacy

All metrics use SQL COUNT, COUNT DISTINCT, SUM, AVG, CASE, EXISTS and GROUP BY.
Python assembles only bounded aggregate rows and calendar buckets. There are no
per-patient/per-test fetch loops. Test-demand analytics has six fixed aggregate
queries independent of entity count. Ranking queries have SQL LIMITs; schemas cap
series at 120 and breakdown rows at 24.

Date predicates compare the raw timestamp column to bound range endpoints. A fixed,
bounded CASE expression maps timestamps to calendar buckets portably. Only weekday
and elapsed seconds need dialect helpers: MySQL WEEKDAY/TIMESTAMPDIFF and SQLite
strftime/julianday. Their SQL is composed solely from SQLAlchemy-compiled column
expressions; no request-controlled SQL snippets, grain fragments or sort strings
are interpolated. Native MySQL execution is tested, not just SQLite emulation.

**No schema migration required.** Existing PK/unique/FK indexes cover joins and
returning-patient lookup by patient_id. There are no analytics tables or materialized
summaries. Timestamp coverage is incomplete; this phase does not add a speculative
large set of write-cost indexes. SQL range filtering bounds the selected cohort,
not necessarily database scan cost. Date-range, returning EXISTS, result grouping
and latest-payment query plans should be measured against representative larger
histories before adding targeted temporal/composite indexes. No production EXPLAIN
or load benchmark was performed.

No patient identity/contact, clinical values, diagnoses, result/report content,
free-form remarks or authentication details enter the response. Physician/facility
names are the intentional authorized business-entity exception. All new endpoints
are reads with no audit/outbox/workflow mutations. Tests explicitly observe SQL
and reject INSERT/UPDATE/DELETE during analytics requests.

## Frontend and empty states

The dashboard uses existing React routing, auth guards, cards, tables, resource
hooks and responsive workspace styles. New lightweight SVG/CSS charts require no
chart dependency or package/lockfile changes. Chart labels, keyboard-focusable bars,
value tooltips and expandable data tables provide equivalents beyond color.
Breakdowns include category/count/share text; department tables include result states.

Presets: Today, Last 7 Days, This Week, Last 30 Days, This Month, This Quarter,
This Year, Custom. This Week/Month/Quarter/Year mean period-to-date. Applying a range
refreshes all eight sections independently and cancels superseded requests; an
error in one section leaves other sections usable. Navigation and drilldowns honor
permissions, and the patient route guard redirects patient actors.

KPI zeros remain visible. No-data charts show explanatory messages rather than
axes. Explicit states include “No orders in this period”, “No specimen activity
in this period”, and “No released reports in this period”. Null baselines show
“No previous baseline” or “No comparable previous data”; null TAT shows “No eligible
samples”. Numeric formatting guards against nonfinite values. Narrow screens use
one-column charts/cards and keyboard-accessible horizontal table wrappers.

## Changed files

New backend: `app/api/analytics.py`, `app/schemas/analytics.py`,
`app/services/analytics_service.py`, `app/services/analytics_sql.py`.
Integration: `app/main.py`, `app/services/permission_catalog.py`.

New frontend: `frontend/src/pages/Analytics.tsx`,
`frontend/src/components/AnalyticsCharts.tsx`, `frontend/src/types/analytics.ts`,
`frontend/src/styles/analytics.css`. Integration: `frontend/src/App.tsx`,
`frontend/src/layouts/Shell.tsx`, `frontend/src/styles/main.css`.

Tests: `tests/test_phase_11_analytics.py`, `tests/test_phase_11_mysql.py`,
`tests/mysql_phase11_probe.py`, `frontend/src/test/analytics.test.tsx`.
Documentation: this file. Existing models and migrations are unchanged.

## Validation

Only focused Phase 11 tests were run; full regression remains for Phase 12.
Backend synthetic fixtures span dates/months, old/new/returning patients, cancelled
orders, panel-expanded items, departments, specimen lifecycle/rejections, result
review/verification, report versions/invalid intervals, referrals, payment history,
login success/failure and outbox states. Tests cover permission boundaries, no PHI,
no writes, empty data, finite ratios, UTC dates, all grains and period comparisons.

The native MySQL probe initializes an isolated /tmp datadir, no host defaults, a
validated Unix socket and no TCP listener; only existing migrations are applied to
that disposable schema. It exercises all endpoints and patient grains using the
same rich synthetic fixture. It never connects to production MySQL.

Frontend tests cover sections, presets/custom/grain inputs, comparisons, charts and
table accessibility, empty/loading/partial-failure states, navigation and patient
exclusion.

Verified results:

- Focused backend: **60 distinct tests passed**. The initial combined run of
  `.venv/bin/python -m pytest tests/test_phase_11_analytics.py tests/test_phase_11_mysql.py -vv -ra --tb=long`
  passed 53 tests, including both SQL compilation/native MySQL tests. After adding
  seven date/history/query-count cases and tightening date/TAT validation,
  `.venv/bin/python -m pytest tests/test_phase_11_analytics.py -vv -ra --tb=long`
  passed all 58 API tests. The native probe passed before those final validation
  refinements; it was not repeated afterward. Two existing dependency deprecation
  warnings were reported; no failing cases remain.
- Frontend: `npm test -- --run src/test/analytics.test.tsx` passed **18 tests**.
- `npm run build` passed TypeScript checking and the Vite production build.
  Output: JavaScript **437.95 kB** (**129.74 kB gzip**), CSS **23.30 kB**
  (**6.11 kB gzip**). No chart library or other dependency was added.
- Python compilation passed for all **9 changed/new Python files**.
- `git diff --check` passed; a separate whitespace inspection also covered all
  **18 changed/new files**, including untracked files.
- No full backend regression, deployment, service restart, production migration,
  permission grant, production data write, commit or push was performed.

## Later deployment and limitations

With separate release authorization, review the diff, run Phase 12 regression and
stage the feature against the current Phase 10 schema. No Phase 11 migration is
needed. Register the ANALYTICS_VIEW catalog entry through the existing approved
metadata process; review any manager grants explicitly. Do not bootstrap roles or
grant analytics broadly. Deploy backend and built frontend through the normal
release procedure, then smoke-check authorized endpoints, denied patient/staff
access, UTC ranges and real sparse-data empty states. No fake production data is
needed. Deployment and service actions were not performed by this implementation.

Known limits: current-state/association attribution is not an historical snapshot;
independent endpoint requests can observe different committed instants; TAT counts
versions and only trustworthy persisted stages; no QC acceptance rate, processed
timeline, paid-date revenue, median, export or production-scale benchmark. Counts
reflect persisted history, including any retained outbox events; no missing clinical
records are reconstructed from blockchain metadata. Exports are deferred.
