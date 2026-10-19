# Original requirements completion

Development baseline: `394ac3c3b94b09e6cd4582221a7b7d9d483299ad`, branch `main`.
Completion review date: 20 October 2026 (Asia/Singapore).

This document updates all 60 IDs in [the original audit](ORIGINAL_REQUIREMENTS_GAP_AUDIT.md).
It describes **local development code, not deployed behavior**. The active MySQL
database was not migrated, clinical records were not modified, and no live service
was restarted. Nothing was copied into the production web root or deployed.

All 11 confirmed missing functions and five of the six partial functions have
development implementations. W16, true repeat testing and external referral,
remains blocked by the business decisions detailed below. Existing configuration,
data, visual-reference and browser blockers are not represented as completed.

## Status definitions and totals

| Status | Meaning |
| --- | --- |
| VERIFIED | Verified at the stated isolated API, query, schema, catalog or PDF scope. This is not a claim of authenticated browser acceptance. |
| UI PENDING | Implemented, with source and relevant isolated/component evidence; an authorized browser walkthrough remains pending. |
| CONFIG/DATA | Software support exists; approved facility configuration or representative accounts/catalog data are still required. |
| REFERENCE | Original visual reference remains unavailable. |
| DECISION | Required clinical/business rules cannot safely be inferred; a concrete proposed workflow is supplied. |

| Area | Reviewed | VERIFIED | UI PENDING | CONFIG/DATA | REFERENCE | DECISION |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Overview | 15 | 0 | 15 | 0 | 0 | 0 |
| Patients | 9 | 3 | 5 | 1 | 0 | 0 |
| Laboratory workspace | 16 | 0 | 14 | 0 | 1 | 1 |
| PDF | 12 | 11 | 0 | 1 | 0 | 0 |
| Catalog | 8 | 3 | 4 | 1 | 0 | 0 |
| **Total** | **60** | **17** | **38** | **3** | **1** | **1** |

The 38 UI PENDING classifications deliberately include newly implemented screens;
passing component tests does not substitute for a signed-in browser walkthrough.

## Changes and evidence by requirement

All endpoints below use `/api/v1`. Existing behavior is distinguished from new
development work. The validation section records actual execution results.

### Overview

Implementation: `app/api/dashboard.py`, `app/schemas/dashboard.py`,
`app/services/dashboard_service.py`, `app/services/activity_observation_service.py`,
`app/services/report_stage.py`, `frontend/src/pages/Dashboard.tsx`, and
`frontend/src/types/dashboard.ts`. Primary tests: `tests/test_dashboard.py`,
`tests/test_original_requirements_completion.py`, and frontend `dashboard.test.tsx`
and `original-requirements-completion.test.tsx`.

| ID | Requirement and resulting behavior | Updated status |
| --- | --- | --- |
| D01 | Recently active staff: distinct accounts with active staff associations, ACTIVE accounts, valid unrevoked sessions and server-observed activity in the last five minutes. Patient links, active PATIENT roles, inactive staff, expired/revoked sessions, absent and future observations are excluded. Multiple sessions count once. AUTH_ACTIVITY_VIEW gates the aggregate. | UI PENDING |
| D02 | Existing REQUESTED-order count retained; pending-order and status links now initialize the Orders filter. IN_PROGRESS remains a separate state. LAB_ORDER_READ retained. | UI PENDING |
| D03 | New count of patients without activated portal accounts, plus a separate review-required count. Shared SQL state derivation preserves account-link precedence; PATIENT_READ and activation-status authorization required. Filtered patient links provided. | UI PENDING |
| D04 | Existing persisted FAILED/retrying and DEAD/terminal blockchain queue indicators retained. Empty queue is never treated as a worker heartbeat. Existing queue permissions and unavailable states retained. | UI PENDING |
| D05 | Individual OFFLINE, DEGRADED, UNKNOWN and STALE node observations now appear in Overview, with safe monitor error codes, timestamps and the authorized monitor link. Observations older than five minutes are stale, not healthy. Healthy peers remain individually visible. | UI PENDING |
| D06 | New application/database observations describe the successful authenticated request and DB connection. Worker state comes from a persisted cycle/shutdown observation; absent is UNKNOWN, old is STALE, recorded failure is UNHEALTHY and graceful shutdown is STOPPED. BLOCKCHAIN_STATUS_VIEW gates the panel. Failed dashboard/authentication requests are unavailable, never fictional healthy zeroes. | UI PENDING |
| D07 | New exact ACTIVE account aggregate and filtered account directory link; ACCOUNT_READ required. Not labeled as online presence. | UI PENDING |
| D08 | New exact SUSPENDED aggregate and directory filter. DISABLED, LOCKED and INACTIVE are not combined with suspended accounts. | UI PENDING |
| D09 | New failed password-login count over an explicit inclusive last-24-hour UTC interval, including LoginLog rows with no linked account. No join drops unknown usernames; audit events and MFA failures are not double-counted. AUTH_ACTIVITY_VIEW and filtered activity navigation retained. | UI PENDING |
| D10 | Existing GENERATED report-version count retained, with status-filtered report navigation. This remains distinct from signing stages. | UI PENDING |
| D11 | New separate counts for GENERATED reports without assignments and assigned reports with at least one unsigned assignment. EXISTS predicates count reports once, regardless of assignment count. Both have filtered report queues. | UI PENDING |
| D12 | New count/queue for GENERATED reports with nonempty assignments and every signature complete. Label says signed reports awaiting approval; existing approval validations remain authoritative. | UI PENDING |
| D13 | APPROVED counts and pending-release navigation retained and linked to filtered report list. | UI PENDING |
| D14 | RELEASED counts include every stored version as before; filtered report navigation added. | UI PENDING |
| D15 | REVOKED counts and historical reports retained; filtered report navigation added. | UI PENDING |

Presence is **recent authenticated activity, not physical presence**. The nullable
`auth_session.last_activity_at` column starts unknown for old sessions. The
authentication dependency records activity only after cookie, account, CSRF and
applicable MFA checks. Writes are throttled to at most once per minute per session;
they do not extend session expiration. Observation commits occur before route
mutations; existing services still own their clinical/audit transactions. A login
with no subsequent authenticated request is not counted until activity is observed.
An administrator without a real staff association is not counted as staff.

The worker writes only the fixed `blockchain_worker` service key in
`service_observation`, separate from ledger/outbox records. The current deployment
has one worker service; the observation is not a distributed per-worker registry.
A long cycle with no completed heartbeat eventually becomes STALE rather than
inventing failure or health. No shell-command or process-control API was added.
Node/service observations age in the UI without network polling; that timer does
not manufacture staff activity. Refresh retrieves new server observations.
Observation writes use whole UTC seconds to match MySQL DATETIME precision and
prevent rounding a fresh observation into the future.

### Patient management

Implementation: `app/api/patients.py`,
`app/services/patient_activation_service.py`, `frontend/src/pages/ResourcePage.tsx`,
`PatientActivation.tsx`, `People.tsx`, and `frontend/src/styles/activation.css`.

| ID | Requirement and resulting behavior | Updated status |
| --- | --- | --- |
| P01 | Group and exact-state filters execute in SQL before COUNT, OFFSET and LIMIT. Link, consumed-history, latest-token and expiry precedence matches the existing six-state projection. Unauthorized activation filtering/sorting returns 403 rather than leaking state through totals. | UI PENDING |
| P02 | Allowlisted patient_id, permanent-code, name and activation sorting; asc/desc direction and patient-ID tie-break. Existing escaped name/code search combines with sex and activation filters. Synthetic tests verify equal-name ties, multiple pages and filtered totals. | UI PENDING |
| P03 | Shared accessible badges display text, symbol and color. REVIEW_REQUIRED has a conspicuous red warning; patient detail additionally uses an alert. Missing status remains unavailable. | UI PENDING |
| P04 | Directory/detail state labels remain consistent; activation status and parent details refresh after invitation completion. No new editable status field. | UI PENDING |
| P05 | All six states remain authoritative. Tests compare SQL-derived filtering to the existing projection, including consumed-token anomalies and linked-account precedence. | VERIFIED |
| P06 | Invitation/reissue identity confirmation, CSRF and one-time token handling retained. Status refresh does not remove the token dialog before the user can read it; closing hides the token and refreshes parent details. No email/SMS delivery claimed. | UI PENDING |
| P07 | Existing invalid, expired, revoked and consumed-token rejection and atomic redemption retained and tested with synthetic fixtures. | VERIFIED |
| P08 | Existing patient-account links and numeric relationships retained; linked accounts win over token history. No automatic relinking or identifier reassignment. | VERIFIED |
| P09 | Patient portal ownership, MFA and account controls retained; authorized patient-account data and a signed-in patient browser are still required for deployed acceptance. | CONFIG/DATA |

Group NOT_ACTIVATED includes all five states without an account link, including
REVIEW_REQUIRED. Detailed badges and the separate review filter retain that warning.
An ACTIVATED link does not override account suspension or MFA requirements.

### Laboratory workspace

Implementation: `app/api/workflow.py`, `app/api/results.py`, `app/api/reporting.py`,
`app/services/reporting_service.py`, frontend `Orders.tsx`, `Specimens.tsx`,
`Results.tsx`, `Reports.tsx`, `ReportSetup.tsx`, `App.tsx`, `layouts/Shell.tsx`,
and `components/LaboratoryProgress.tsx`.

| ID | Requirement and resulting behavior | Updated status |
| --- | --- | --- |
| W01 | Existing order search/status/priority/date filters retained; dashboard status links initialize the filter. | UI PENDING |
| W02 | Order details now show the permanent patient code beside existing name/details and a PATIENT_READ-gated record link. Code generation is unchanged. | UI PENDING |
| W03 | Existing requested test/panel expansion retained. All five starter panels now have isolated order-to-PDF coverage; panel labels also replace bare panel request IDs in result-entry context. | UI PENDING |
| W04 | Collection and receipt operations retained and exercised in full-panel synthetic flows. Workflow sequence and prerequisite messages clarify the next step. | UI PENDING |
| W05 | GET `/lab/rejection-reasons` now permits SPECIMEN_REJECT for active reasons only, regardless of a supplied inactive filter. Reason managers retain full filtering. Creation/update still require REJECTION_REASON_MANAGE. Frontend lookup uses SPECIMEN_REJECT. | UI PENDING |
| W06 | Confirmed pagination defect fixed: the authorized results page response now carries distinct occupied order-item IDs for the whole order. New-entry buttons check this complete set, and remain unavailable while state is unknown/loading/failed. Existing drafts remain editable from their results page. | UI PENDING |
| W07 | Existing NUMERIC, POS_NEG and TEXT entry retained. Full-panel numeric scenarios and the existing renal/qualitative/TEXT simulation cover configured result types without inventing clinical vocabularies. | UI PENDING |
| W08 | Reference-unit precedence retained. Frontend one-sided reference intervals now use ≤/≥; missing intervals remain explicitly unconfigured. | UI PENDING |
| W09 | Review and verification permissions/transitions retained. New panel tests reject verification before review and preserve verified result immutability. | UI PENDING |
| W10 | Identity-bound signing and approval remain unchanged. Report setup now exposes real staff/profile configuration; assigning a profile to a report remains a separate operation. | UI PENDING |
| W11 | Initial report generation is offered only for a completed order after a successful report-list response confirms total=0. Existing reports point users to versions/revision; release rules unchanged. | UI PENDING |
| W12 | Revocation, revision and historical-version behavior retained. New requests do not overwrite verified results or substitute for amendments. | UI PENDING |
| W13 | Existing stored-PDF preview/download, print audit, verification hash/URL and blockchain indicators retained. Actual authenticated browser controls remain pending. | UI PENDING |
| W14 | New `/administration/report-setup` route and permission-aware navigation expose facility create/edit, template create/edit/retire, and signatory create/edit/retire with staff association. Forms use existing API validation and CSRF. Template codes are displayed, never editable. | UI PENDING |
| W15 | No original visual reference was available. Neither workspace nor PDF reference fidelity is claimed. | REFERENCE |
| W16 | True repeat-result provenance and external referral are not implemented. Existing unrelated new-order action remains honestly labeled. Minimum model, transitions and unresolved decisions are specified below. | DECISION |

Report setup never invents facility names, licenses or signatures. New template and
signatory forms default inactive, requiring deliberate activation. Existing
private logo/signature path fields refer only to administrator-provisioned assets;
no upload service or remote image storage was introduced. PDF v2 prints electronic
identity attribution, not scanned handwritten signatures. Existing signed-profile
and approved-template immutability checks still reject prohibited edits.

### PDF v2

Implementation: `app/services/report_presentation.py`,
`app/services/report_pdf_v2.py`; tests in `tests/test_report_pdf_v2.py` and
`tests/test_starter_catalog.py`.

| ID | Requirement and resulting behavior | Updated status |
| --- | --- | --- |
| F01 | Existing facility header/logo rendering retained. Approved actual branding and private asset configuration remain prerequisites; synthetic image rendering does not satisfy live branding approval. | CONFIG/DATA |
| F02 | Frozen patient information retained. Continuation pages now repeat the permanent patient code without querying current patient data. | VERIFIED |
| F03 | Frozen order details retained; printed timestamps now use day/month/year and minute precision with an explicit UTC label. Stored timestamp precision is unchanged. | VERIFIED |
| F04 | Frozen department/panel/section grouping retained; all five panels exercised in synthetic PDFs. | VERIFIED |
| F05 | Results, flags, units and ranges retained, including existing reference-unit precedence and qualitative rendering. | VERIFIED |
| F06 | New presentation snapshots capture actual SampleType.sample_name through the specimen relationship. PDFs print the captured sample type. Post-generation catalog renaming does not alter it; old snapshots missing the key remain renderable. | VERIFIED |
| F07 | Remarks/methodology and long-note preservation retained. Shared specimen metadata is printed once per group/specimen, with test associations when specimens differ. Per-result verification history remains visible. | VERIFIED |
| F08 | Actual authorized signatory attribution retained. No invented signer, credential or signature asset. | VERIFIED |
| F09 | Frozen generation/approval/release metadata and version references retained with readable timestamps. | VERIFIED |
| F10 | URL-only QR content, released PDF SHA-256 and verification flow retained; no new patient data encoded. | VERIFIED |
| F11 | Multipage stress tests retain all 100 analytes, trailing remarks, repeated headers, page numbers and nonoverlapping paragraphs. Continuation patient identification added. Visual sampling is documented in validation. | VERIFIED |
| F12 | V1 and prior v2 compatibility tested. Stored released artifacts continue to be downloaded by their original bytes/hash; no released PDF was backfilled or regenerated. | VERIFIED |

### Philippine laboratory catalog

| ID | Requirement and resulting behavior | Updated status |
| --- | --- | --- |
| C01 | Inventory remains 5 departments, 39 tests, 5 sample types and 5 panels, with existing specimen and membership links. Manifest and importer unchanged. | VERIFIED |
| C02 | Preview, explicit confirmation, fingerprints, inactive defaults, atomic rollback and idempotency retained. Browser confirmation still requires an authorized isolated application session. | UI PENDING |
| C03 | Existing catalog administration retained; no live import or clinical activation performed. | UI PENDING |
| C04 | Selectable active tests/panels work in isolated fixtures. Broad active-site catalog simulation still requires approved import/configuration; no automatic activation. | CONFIG/DATA |
| C05 | Specimen compatibility remains enforced. Each panel simulation rejects an active incompatible sample and uses mapped received specimens. This verifies software rules, not facility assay/container approval. | VERIFIED |
| C06 | Existing configured numeric/qualitative/TEXT entry works in synthetic flows. Urinalysis/stool TEXT summaries remain summaries, not comprehensive structured clinical examinations. | UI PENDING |
| C07 | All five panel memberships now run through actual isolated order, specimen, result, review, verification, signing, approval, release and PDF grouping. Authenticated UI selection remains pending. | UI PENDING |
| C08 | Expanded simulation covers CBC, differential, lipid, liver and renal panels, plus existing pregnancy and ABO/Rh examples. Inactive panel/member, wrong specimen, invalid numeric entry, duplicate entry and out-of-order verification are rejected. | VERIFIED |

## Migration and compatibility boundary

New migration: `migrations/versions/20261019_01_activity_observations.py`, parent
`20261018_01`:

- Adds nullable `auth_session.last_activity_at` plus its index; existing sessions
  retain NULL rather than being assumed active.
- Adds `service_observation(service, checked_at, status)` with no seeded health.
- Does not update clinical, identity, report, ledger, outbox or code-sequence rows.
- Destructive downgrade is refused. Use a reviewed recovery procedure rather than
  deleting observations as an automatic rollback.

The migration was exercised only against disposable test data. Native MySQL tests
validate the private socket, fixture-owned data directory and disabled TCP before
creating the synthetic database. Baseline row snapshots and code sequences remain
unchanged; existing sessions gain only NULL, repeated upgrade is a no-op, and
native activity/filter queries and transaction rollback are verified.

Accepted automatic-code allocation code and the existing automatic-code migration
are unchanged. Historical-schema test projections were updated to exclude the new
activity column when comparing old migrations, and current-head assertions include
the additive revision. These fixture changes do not alter the seven generators.

## Repeat testing and referral: precise proposed workflow

No existing model expresses a repeat result or outbound referral. A requesting
physician's ReferringFacility is an inbound source and must not be silently reused
as an approved receiving laboratory. Current code uniqueness and result immutability
rules cannot safely establish clinical ordering authority or specimen reuse policy.

### Minimum repeat-testing proposal

Add a dedicated `lab_repeat_request` record with original `result_item_id`, a
server-validated link to a new `order_item_id`, required reason, request timestamp,
requesting actor, approving actor/time where required, and cancellation reason.
Keep both original and repeat result immutable after their normal verification.
The new item must refer to the same patient and test as its source; any panel-wide
repeat needs an explicit set of source-result links rather than an unrelated order.

Proposed action: open the original result → request repeat with reason → obtain
any required authorization → create the linked order/item atomically with an audit
event → collect/receive eligible specimens → normal entry/review/verification →
new report lifecycle. Display both directions of the provenance link and distinguish
repeat testing from correcting an erroneous report. Never copy an original result
value into a repeat or treat a repeat as an automatic amendment.

Decisions required before implementation:

1. Who can order/authorize a repeat, and is authorization different before versus
   after release? Which source result states are eligible?
2. Is the unit of repeat one analyte, a selected group, or the complete panel?
3. May an existing specimen be reused, and which retention/stability/collection
   rules and staff attestations make it eligible?
4. Does the repeat produce an independent report, or require a linked amendment
   under defined circumstances? Which cancellation and duplicate-request rules apply?

### Minimum external-referral proposal

Introduce a reviewed receiving-laboratory directory or explicit receiving role,
plus referral header/items linked to the originating order/test and specimens.
Required information: receiving facility and contact, destination acknowledgment,
referral purpose, authorizing actor/time, dispatch and receipt times, courier or
tracking reference when applicable, specimen handoff/condition, external accession
and report reference, returned result/report and issuer, return timestamp, and
local reviewing/accepting actor with rejection/cancellation reasons.

Proposed tracked stages: DRAFT → AUTHORIZED → DISPATCHED → ACKNOWLEDGED →
RESULT_RETURNED → LOCALLY_REVIEWED, with explicit rejection/cancellation transitions.
External results must retain their external provenance and must not become locally
verified results merely through attachment upload. Existing local report approval,
release and blockchain behavior should apply only after an approved integration rule.

Decisions required: approved receiving facilities and services; dispatch authority;
patient consent/data-sharing requirements; specimen custody responsibilities;
accepted result formats and identity matching; local review/signing responsibility;
whether/how external results enter a local report; amendment, cancellation and
turnaround rules. These are decisions for the facility, not inferred clinical policy.

## Reviewable development simulation procedure

This is a proposed procedure requiring separate authorization to mutate the chosen
development application. It is **not** authorization to import into the active database.

1. Identify an isolated development deployment/database and confirm that it contains
   only approved synthetic patients, staff and credentials. Record its URL/schema
   and a recovery point; confirm it is not the active `rhu_labchain` application.
2. Sign in as an authorized staff administrator. Open Laboratory setup → starter
   catalog preview. Review all 54 definitions (5+5+39+5), matches/conflicts and links.
   Preview is read-only. Resolve conflicts before confirming.
3. After approval, confirm the reviewed fingerprint with inactive-default
   acknowledgment. Verify the import audit and re-preview: a repeated import should
   propose no new records. Stop on any unexpected additions/conflicts.
4. Agree a small simulation scenario and exact selected tests/panel members. Configure
   explicitly synthetic units, methods and optional reference ranges; do not adopt
   the test fixture's arbitrary numeric values as clinical intervals.
5. Activate only the approved selected departments, samples, tests and panel. Confirm
   every active member has the intended specimen mapping and result type. Leave
   unapproved definitions inactive. TEXT summaries require explicit scope review.
6. Use Report setup to enter approved synthetic facility details, templates and
   signatory profiles associated with the actual synthetic staff accounts. Only
   those accounts sign their assignments. Do not invent real professional licenses.
7. Run the authorized synthetic order-to-release workflow, including wrong-specimen,
   inactive-member, duplicate-entry and permission-denial cases. Verify panel labels,
   specimen type, PDF pages, URL-only QR, stored hash and report history.
8. Retain validation evidence and retire synthetic configuration according to the
   agreed development cleanup plan. Review clinical use independently: software
   readiness and synthetic simulation do not constitute clinical authorization.

## Validation and remaining browser checks

**331 distinct backend/native test cases reached passing outcomes across the
focused runs below; 116 frontend tests passed.** The distinct backend count was
checked against collected test IDs, excluding reruns. This is not a claim that
the entire backend regression suite was run.

| Validation | Actual result and evidence |
| --- | --- |
| Requirements/API/catalog/PDF/schema batch | 101 cases: 99 passed initially; two fixture failures were corrected and passed in the next targeted run. Files: `test_original_requirements_completion.py`, `test_starter_catalog.py`, `test_dashboard.py`, `test_patient_activation_states.py`, `test_report_pdf_v2.py`, `test_phase_2a_migration.py`. `/tmp/rhu-completion-backend.log`. |
| Corrected scenarios and worker lifecycle | **24 passed**. Corrected the missing patient router in the new integration fixture and the historical-schema projection of the new activity column. Included all six frozen migration comparisons and worker CLI tests; no assertion was disabled. `/tmp/rhu-completion-corrections.log`. |
| Authentication/MFA/code/report compatibility | **227 passed**. Full focused files for authentication, MFA, worker CLI, automatic-code generation/master schemas/rejection service; selected existing facility/template/signatory, identity-bound signing, historical configuration and release/QR/hash cases. `/tmp/rhu-completion-security.log`. |
| Final PDF layout and catalog flow | **16 passed** after specimen consolidation and unit-column/signatory-heading refinements. `test_report_pdf_v2.py`, all five `test_every_panel_synthetic_order_to_pdf_and_specimen_errors` cases, and `test_catalog_order_specimen_results_and_pdf_history`. `/tmp/rhu-completion-pdf-final.log`. |
| Mixed specimens in one report group | **1 passed**; both specimen identities, sample types and test associations retained. `/tmp/rhu-completion-mixed-pdf.log`. |
| Native MySQL migration | **1 passed**, no skip, within the final 50-case run below. Disposable private socket and disabled TCP. `tests/test_activity_observations_mysql.py` covers historical preservation, all six activation states, strict-mode dashboard queries, timestamp precision and rollback. |
| Final MySQL/dashboard/activity/worker verification | **50 passed** after the native query and timestamp corrections: `test_activity_observations_mysql.py`, `test_dashboard.py`, `test_original_requirements_completion.py`, and `test_phase_8b_worker_cli.py`. `/tmp/rhu-completion-native-final.log`. These reruns are not added to the 331 distinct-case total. |
| Frontend components/workflows | **116 passed, six files**: `original-requirements-completion.test.tsx`, `dashboard.test.tsx`, `patient-activation-staff.test.tsx`, `laboratory-workspace.test.tsx`, `starter-catalog.test.tsx`, `workflows.test.tsx`. `/tmp/rhu-completion-frontend-final.log`. |
| TypeScript and Vite | `npm run build` passed: type checking plus local production build. `/tmp/rhu-completion-build-final.log`. No static artifact was copied to production. |
| Python and Git | Every changed/new Python file parsed successfully; `git diff --check` passed. Byte comparisons confirmed unchanged generator implementation, existing code migration, identity/laboratory/workflow services and immutable-code schemas; AST comparison confirmed unchanged report-template allocation/configuration function. |
| Document completeness | All 60 IDs present exactly once; status totals reconcile to 17 VERIFIED, 38 UI PENDING and five documented blockers. |

Earlier iterations exposed a TypeScript inference error, a results UI missing-field
crash, selectors that also matched new filter options, and old contract/head
assertions. Native MySQL additionally rejected grouping the correlated activation
expression under `ONLY_FULL_GROUP_BY`; the dashboard now counts filtered patients
without grouping. MySQL timestamp rounding could also briefly classify a fresh
worker observation as future/unknown; writes now explicitly retain whole seconds,
with a native regression using 999999 microseconds. SQL mode and future-observation
exclusion remain unchanged. These were corrected and the relevant final runs passed. Existing
Starlette/httpx and AnyIO deprecation warnings remain; no check was weakened,
permission disabled or failing case skipped to obtain these results.

Synthetic renderer output was captured unchanged under
`/tmp/rhu-completion-evidence` using an audit-only pytest wrapper. The existing
temporary pypdfium2 installation rasterized it without changing app dependencies.
Final visual sampling covered all three CBC pages, renal page 1, and stress-report
pages 24 and 47. Sample labels, complete units, continuation patient codes,
signatures and QR output were readable without clipping/overlap in these samples.
The CBC fixture reduced from four pages to three; the QR block may move intact to
a continuation page. The 47-page stress document retains all 100 analytes and its
final remarks, with automated paragraph-bound and nonoverlap checks across output.
Not every stress page was visually inspected. Physical printing and camera QR
scanning were not performed. No reference-image fidelity is claimed.

Reproduction uses the normal existing synthetic/network-blocked pytest fixtures:

```bash
.venv/bin/python -m pytest tests/test_original_requirements_completion.py \
  tests/test_dashboard.py tests/test_patient_activation_states.py \
  tests/test_starter_catalog.py tests/test_report_pdf_v2.py \
  tests/test_phase_2a_migration.py -q --tb=short
.venv/bin/python -m pytest tests/test_activity_observations_mysql.py -q -s --tb=short
cd frontend
npm run test -- --run src/test/original-requirements-completion.test.tsx \
  src/test/dashboard.test.tsx src/test/patient-activation-staff.test.tsx \
  src/test/laboratory-workspace.test.tsx src/test/starter-catalog.test.tsx \
  src/test/workflows.test.tsx
npm run build
```

The reproducible requirements command now collects the two additional PDF cases
added after the first 101-case batch. Temporary evidence can be removed by host
cleanup; the results, sampling limits and corrections are recorded here durably.

No authorized interactive browser session or installed browser executable was
available. Component tests run in jsdom with mocked APIs; backend tests use real
application code and synthetic records, not the live system. The following remain
pending in an authorized isolated browser: role-specific dashboard and drilldowns;
patient filters, pagination and invitation delivery; patient MFA/ownership;
report setup create/edit/retire; complete specimen-to-release workflow; PDF preview,
download/print/QR camera scan; all catalog confirmations; and desktop/mobile
loading, unavailable and empty-state presentation. No authentication bypass was used.

## Proposed deployment actions — not executed

1. Review the local development commit, these results, W16 decisions and remaining
   browser acceptance. Approve the release separately.
2. Prepare a coordinated recovery set for database, private report assets and
   application/static artifacts; confirm all existing report hashes and identifiers.
3. Exclude application/import writers under the existing deployment runbook. Apply
   `20261019_01` only after explicit active-database migration authorization. Check
   worker database permissions for its fixed observation table; do not grant arbitrary
   process control or broad new data access.
4. Deploy matching backend/worker code and the verified frontend build. **Do not
   restart new backend code against the old schema**: authentication now selects
   the activity column. Service restart and copying to `/var/www/rhu-labchain` are
   separate deployment actions and were not performed here.
5. Verify schema revision, authenticated role-specific behavior, fresh worker
   observations, first real staff activity, existing stored PDF hashes and outbox
   integrity. Initial NULL/UNKNOWN observations are expected until activity occurs.
6. Import/configure only separately approved development simulation definitions.
   Facility branding, actual account setup and clinical activation require their
   own approved values. Do not make the catalog clinically active as a deployment
   side effect, and do not change Fabric channels, volumes, certificates or wallets.
