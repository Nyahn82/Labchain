# Original requirements audit and gap analysis

Audit date: **19 October 2026 (Asia/Singapore)**. Evidence timestamps retain their
recorded UTC timezone. Repository: `/opt/rhu-labchain`, branch
`main`, deployed commit `394ac3c3b94b09e6cd4582221a7b7d9d483299ad`.

**Finding: the deployed major update does not yet satisfy every original
requirement.** The accepted automatic-code implementation is unchanged. The most
significant omissions are dashboard presence/security/activation metrics,
signature-stage counts, patient activation filtering/sorting/badges, and report
prerequisite administration in the frontend. Catalog definitions exist, but the
starter catalog has not been imported or configured in the active database.

This is an audit, not authorization to implement these corrections, activate
clinical tests, import data, or deploy another release.

## 1. Scope, status definitions and totals

The 60 numbered functions below cover the supplied audit checklist: 15 Overview
metrics, 9 patient functions, 16 laboratory workspace functions, 12 PDF functions,
and 8 catalog functions. Workspace scope includes prerequisite administration,
visual-reference matching, and the original Workstream D repeat/referral request.
Loading/error handling, permissions, navigation and data provenance are assessed
within these functions rather than counted again as separate features.

| Status | Meaning used in this report |
| --- | --- |
| **VERIFIED** | Implemented and directly verified at the stated scope through source inspection plus real read-only observations or actual isolated API/PDF execution. Does not imply an authenticated deployed browser walkthrough. |
| **UNVERIFIED** | Implemented, with source and usually DOM/API test evidence, but **not verified in the deployed authenticated UI**. |
| **PARTIAL** | A specific required aspect is absent or incomplete; the row names it. |
| **MISSING** | The requested function has no usable implementation at its required surface. Related tables or an unrelated administration page do not satisfy it. |
| **BLOCKED — CONFIG/DATA** | Supporting implementation exists, but configuration or representative active data is absent. |
| **BLOCKED — REFERENCE** | The original visual reference is unavailable; matching cannot be established. |

These are mutually exclusive primary classifications. For example, a confirmed
missing patient filter stays MISSING even though browser access is also absent.
VERIFIED rows describe backend state/security behavior, definition integrity,
synthetic workflow execution or directly inspected PDFs; none falsely claims a
signed-in live browser test.

| Area | Reviewed | VERIFIED | PARTIAL | MISSING | UNVERIFIED / awaiting browser | BLOCKED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Overview | 15 | 0 | 1 | 8 | 6 | 0 |
| Patients | 9 | 3 | 1 | 2 | 2 | 1 |
| Laboratory workspace | 16 | 0 | 3 | 1 | 11 | 1 |
| PDF | 12 | 10 | 1 | 0 | 0 | 1 |
| Catalog | 8 | 3 | 0 | 0 | 4 | 1 |
| **Total** | **60** | **16** | **6** | **11** | **23** | **4** |

Of the four blockers, **three concern configuration/data and one concerns the
unavailable reference**. No CRITICAL defect was confirmed in this audit. HIGH
priorities below concern original requirement fulfillment or important workflow
visibility; they are not claims of a security breach or data corruption.

## 2. Evidence and limits

### Evidence identifiers used in the matrices

| ID | Evidence |
| --- | --- |
| **S** | Direct inspection of the named backend/frontend/schema/permission code at the deployed commit, not just workstream reports. |
| **L** | Fresh active-database SELECTs in an explicitly read-only transaction, deployed OpenAPI inspection, and public HTTPS/build-byte checks. Sanitized aggregate evidence: `/tmp/rhu-original-audit-KAZrYt/live-readonly.json`. |
| **B** | Fresh focused offline execution: `test_dashboard.py`, `test_patient_activation_states.py`, `test_report_pdf_v2.py`, `test_starter_catalog.py`: **70 passed**, zero failures. Synthetic SQLite and the existing network guard retained. |
| **F** | Fresh Vitest execution: `dashboard.test.tsx`, `patient-activation-staff.test.tsx`, `laboratory-workspace.test.tsx`, `starter-catalog.test.tsx`, `workflows.test.tsx`: **100 passed**, five files. Actual components in jsdom, mocked backend responses; not a live browser session. |
| **Q** | Fresh isolated `test_phase_5b_release.py::test_release_snapshots_pdf_qr_hash_and_download`: **1 passed**. Actual PDF generation, URL-only QR payload, stored SHA-256, authenticated download, redacted public verification and duplicate-release rejection. |
| **V** | Synthetic PDF bytes captured without altering renderer results, rasterized and visually inspected. See section 6. |
| **C** | Prior cutover evidence in `/home/rhuadmin/.local/state/rhu-labchain/recovery/cutover-20261019-394ac3c-report.md`: historical PDF preserved, old tables preserved, four peers online, protected assets unchanged. This is explicitly prior evidence, not a new audit-time Fabric probe. |

**Fresh total: 71 backend tests and 100 frontend tests passed.** Backend runs
reported the existing Starlette/httpx and AnyIO deprecation warnings. No full
backend/frontend regression or build was repeated. The deployed build was
already validated at cutover; this audit confirmed the public HTML matches the
actual web-root artifact.

### Resumption verification — 19 October 2026

The existing audit and its retained artifacts were checked when this task resumed.
Repository HEAD still matches `394ac3c3b94b09e6cd4582221a7b7d9d483299ad`;
the only working-tree addition is this audit document. All 60 requirement IDs are
unique, the row classifications reconcile to the summary totals, and every
relative Markdown source-file link resolves.

The retained logs confirm **70 + 1 backend tests and 100 frontend tests passed**.
These tests and the live read-only observations above were performed during the
original audit execution, **not rerun during this resumption**. The sanitized
`live-readonly.json` and PDF inventory remain present. Source spot-checks reconfirm
missing dashboard aggregates, missing patient activation filters/sorting, the
rejection-reason permission dependency, absent report setup routes, and absent
specimen-type capture. The saved single-page signed report and page 24 of the
47-page stress report were visually reinspected; neither sampled image showed
clipping or overlap. This does not extend the original sampling to every page.

No new live database query, authenticated browser walkthrough, service operation,
or application mutation was performed during resumption. Live observations remain
point-in-time evidence from the original audit; browser and configuration blockers
remain open. The implementation plan below is proposed work only.

### Interactive verification limits

No authorized interactive browser session was available to this agent. There is
no local Chromium/Chrome executable or installed Playwright client, and no
authenticated browser session was supplied. No session was forged, reused from
database hashes, or created by bypassing authentication. The user's SSH/sudo
credential is not treated as an application login.

Consequently, real signed-in navigation, visual responsiveness, live role-specific
buttons, invitation delivery, portal MFA/login, clinical mutations, and live PDF
preview/download clicks were **not** performed. Matrices distinguish this from
the real offline API and component tests. All live database inspection was
read-only; no live reports, invitations, accounts, catalog imports or test orders
were created. No live service was restarted and nothing was deployed.

### Fresh deployed data/configuration observations

- Database `rhu_labchain`, Alembic revision **`20261018_01`**.
- Deployed patient GET list parameters: `page`, `page_size`, `search`,
  `patient_code`, `sex`. **No activation or sorting parameter exists.**
- Deployed dashboard response fields: `generated_at`, `patients`, `orders`,
  `specimens`, `results`, `reports`. No account, online, activation or signature
  waiting fields exist.
- Two patients, both derived as `NOT_ACTIVATED`; **zero patient-account links**.
- One ACTIVE account and one DISABLED account. No SUSPENDED account in the
  observed data. One unexpired, unrevoked session for one account: this is
  **not evidence that one staff member is currently online**.
- Login history contains 57 SUCCESS and **10 FAILED** events. The absence of a
  dashboard failed-login indicator is not caused by missing event storage.
- One COMPLETED order and one RELEASED report; **zero PDF v2 report snapshots**
  in the active database. The existing report is historical and must stay so.
- Outbox: two CONFIRMED events; no other statuses at inspection.
- Live catalog: one active department, one active test, one active specimen
  type, zero panels; zero `STARTER_CATALOG_CREATE` audit events.
- Starter preview: 5 departments / 5 samples / 39 tests / 5 panels, **54 proposed
  additions, zero preserved matches and zero conflicts**. Preview does not import.
- Private logo and signature directories are unconfigured. This does not mean
  electronic signatory attribution is absent; v2 uses captured authorized names,
  capacities, license values and signing timestamps.
- HTTPS returned 200. These observations are a point-in-time audit, not permanent
  monitoring statistics.

## 3. Overview Dashboard: all 15 original metrics

Backend summary files: [`dashboard.py`](../app/api/dashboard.py),
[`dashboard_service.py`](../app/services/dashboard_service.py),
[`schemas/dashboard.py`](../app/schemas/dashboard.py).
Frontend: [`Dashboard.tsx`](../frontend/src/pages/Dashboard.tsx).
All endpoints below are prefixed `/api/v1`.

The implemented summary counts actual table rows, grouped by current status,
without multiplying them through joins. It is **all-time current state**, not
today's throughput. Report counts include every version, including superseded
versions. Permission-denied sections are omitted rather than returned as zero.
Staff-only access excludes patient-role and patient-linked accounts, including
mixed-role accounts; existing administrator permission semantics remain.

| ID / requirement | Backend, data and logic | Frontend, states and navigation | Evidence / status | Gap and required correction | Priority |
| --- | --- | --- | --- | --- | --- |
| D01 Current user/staff online | `auth_session` stores creation, expiry, revocation and MFA time; `/admin/sessions` lists session state. No last-activity/heartbeat exists. See `models/auth_session.py`, `dependencies/auth.py`, `auth_activity_service.py`. | Welcome message identifies the current user; there is no online staff metric/list, freshness indicator or corresponding empty/error/drilldown state. | S,L; **MISSING** online-presence function. | Define recent activity before implementing presence. Count distinct eligible staff identities with recent server-observed activity and valid sessions; never label ACTIVE accounts or unexpired sessions as online. Gate sensitive identity detail with appropriate permissions. | HIGH |
| D02 Pending laboratory orders | GET `/dashboard/overview`, `LabOrder.status == REQUESTED`; section requires `LAB_ORDER_READ`. IN_PROGRESS orders appear in a separate status breakdown. | “Requested orders” in Pending work, Orders total and status breakdown. Loading/unavailable/retry/zero states exist; “View orders” opens the directory, but pending count itself is not a status-filtered link. | S,L,B,F; **UNVERIFIED** in live UI. | No confirmed missing count. Verify live labels and empty cases; add a status-filtered drilldown if pending-work actionability is required. Preserve distinction between requested and in-progress work. | MEDIUM |
| D03 Unregistered/not-yet-activated patients | `patients` is total `Patient` rows, not activation count. `patient_activation_service.activation_states()` exists but is not aggregated by the dashboard. A person with no Patient row cannot be counted. | “Registered patients” total only; no unactivated/invitation/review-required indicators or links. | S,L; **MISSING**. | Name the metric “Patients without activated portal accounts.” Aggregate link/token-derived states with authorized visibility; distinguish review-required anomalies. Do not claim to count people absent from the database. | HIGH |
| D04 Blockchain failures | GET `/blockchain/status`; `blockchain_status_service.global_status()` groups persisted `blockchain_event` states. FAILED means retrying; DEAD means terminal failed. Expired processing leases can make queue health degraded. Requires named staff roles plus `BLOCKCHAIN_STATUS_VIEW`. | `components/BlockchainQueue.tsx` displays actual retrying/failed counts and an “Attention required” state for ERROR. Separate loading/unavailable/never-confirmed states exist. No direct link from failure counts to affected events. | S,L,B,F,C; **UNVERIFIED** in live UI. | This is a real failure indicator, not merely an ONLINE label. Verify failed/dead examples in an isolated authenticated UI; optionally link authorized users to the existing monitor queue/anchors. Never treat an idle queue as proof that the worker process is alive. | MEDIUM |
| D05 Node failures | GET `/admin/blockchain/overview`; `blockchain_monitor_service.py` and the local monitor provide observed nodes, statuses, timestamps and error codes. Requires `BLOCKCHAIN_EXPLORER_VIEW`. | Dashboard shows aggregate network status and “N of M peers online”; links to Blockchain Monitor. Individual failing nodes/reasons are only available in that separate page. Unavailable and UNKNOWN are distinguishable from healthy output. | S,B,F,C; **PARTIAL**. | Add an actionable node-attention projection identifying OFFLINE/DEGRADED versus UNKNOWN/stale observations. Preserve available healthy peers. A reduced online count alone must not be presented as a confirmed node failure count. | HIGH |
| D06 Service problems | `/health` and `/ready` exist; readiness observes DB connectivity. Queue health is not worker process health. No persisted worker heartbeat/status aggregate exists (`schemas/blockchain.py` explicitly documents this). | No application/DB/worker service-problem panel in Overview. A failed summary request gives an unavailable message, not a service diagnosis. | S,L; **MISSING**. | Expose a bounded, authorized, sanitized service observation with freshness; integrate attention states. Reuse readiness where appropriate and add honest worker liveness evidence if required. Never expose arbitrary systemctl execution or infer health from an empty queue. | HIGH |
| D07 Active accounts | `user_account.account_status` and account administration exist; `/users?account_status=ACTIVE` provides filtered records. Dashboard does not aggregate them. | No active-account card, states or link in Overview. `People.tsx` administration is a different surface. | S,L; **MISSING**. | Add permission-filtered account counts, explicitly separate from sessions/presence; link to the corresponding authorized account filter. | HIGH |
| D08 Suspended accounts | SUSPENDED is a real stored enum; suspension/reactivation and audits exist in `administration_service.py` / POST `/users/{user_id}/suspend` and `/users/{user_id}/reactivate`. | No suspended-account indicator in Overview; administration can show/change account status. | S,L; **MISSING**. | Count SUSPENDED exactly, without combining DISABLED, LOCKED or INACTIVE. Use ACCOUNT_READ or an explicitly reviewed monitoring permission and real zero/unavailable states. | HIGH |
| D09 Failed login attempts | `LoginLog.status=FAILED` is stored, including unsuccessful usernames without a linked user. GET `/admin/auth-activity` supports LOGIN_FAILED/status/date filters under `AUTH_ACTIVITY_VIEW`. MFA failures are separate audit events. | Authentication Activity exists; no failed-login metric in Overview. | S,L; **MISSING**. | Add a documented time-window aggregate over LoginLog without double-counting AUTH_LOGIN audits or losing unknown-user attempts through an inner join. Do not silently mix MFA failures into password failures. Link to the filtered activity view. | HIGH |
| D10 Generated reports | `/dashboard/overview`, `LabReport.report_status=GENERATED`, `REPORT_READ`. Every stored version contributes once. | GENERATED breakdown and “Generated reports to review”; loading/error/zero states implemented. General Reports link; no dedicated signature-stage filtering. | S,L,B,F; **UNVERIFIED** in live UI. | Verify against live authorized data when available. This count intentionally includes both unsigned and fully signed GENERATED reports; it does not satisfy D11/D12. | MEDIUM |
| D11 Reports awaiting signature | `report_signatory.signed_at` and signing APIs exist, but no dashboard aggregate separates GENERATED reports with missing assignments/unsigned assignments. | No awaiting-signature card, filter or attention link. | S; **MISSING**. | Derive distinct report counts; show unassigned versus awaiting signatures explicitly. Do not count signature rows as reports or invent a new persisted report state solely for the card. | HIGH |
| D12 Reports awaiting approval | Approval checks in `reporting_service.approve_report()` require at least one assignment, all signed, valid verified sources and valid snapshots. No corresponding aggregate. | No fully-signed-awaiting-approval metric. GENERATED is used for all pre-approval reports. | S; **MISSING**. | Derive GENERATED reports with nonempty, fully signed assignments; label “Signed reports awaiting approval,” not guaranteed approvability. Keep full backend approval validation authoritative. Use REPORT_READ and appropriate action permissions. | HIGH |
| D13 Approved reports | Persisted APPROVED count, REPORT_READ. | APPROVED breakdown and “Approved reports awaiting release”; accurate loading/unavailable/empty states, general Reports navigation. | S,L,B,F; **UNVERIFIED** in live UI. | Verify approved sample and permission behavior in an authorized browser; consider direct filtered link. | LOW |
| D14 Released reports | Persisted RELEASED count, REPORT_READ. Includes all released versions, not just current versions. | RELEASED breakdown and report-directory navigation. | S,L,B,F; **UNVERIFIED** in live UI. | Verify the displayed count and all-version wording. Do not silently change to “current final reports” without a distinct definition. | LOW |
| D15 Revoked reports | Persisted REVOKED count, REPORT_READ; historical report/PDF retained. | REVOKED breakdown and report-directory navigation. | S,L,B,F; **UNVERIFIED** in live UI. | Verify revoked example and linked history in isolated UI; do not revoke a live report just to populate the card. | LOW |

### Presence and security conclusions

`get_current_session()` rejects revoked/expired sessions and non-ACTIVE accounts,
but it does not update an activity timestamp. A browser closed without logout can
leave an unexpired session. `/admin/sessions` uses expiry/revocation to label
ACTIVE and does not establish physical presence. Showing that count as “online”
would be incorrect. A future presence definition must document its time window,
session/account/MFA eligibility, distinct-account counting, privacy and stale
observations. It may require a carefully scoped last-activity field or equivalent
server-side store; no migration is created by this audit.

Ten stored failed-login events prove that D09 can use real evidence. Account
status and auth activity already have private, paginated endpoints and existing
permissions. Reuse their semantics rather than inventing another security log.

## 4. Patient management

Key files: [`patients.py`](../app/api/patients.py),
[`identity_service.py`](../app/services/identity_service.py),
[`patient_activation_service.py`](../app/services/patient_activation_service.py),
[`patient_activation.py`](../app/api/patient_activation.py),
[`ResourcePage.tsx`](../frontend/src/pages/ResourcePage.tsx),
[`resources.ts`](../frontend/src/pages/resources.ts),
[`PatientActivation.tsx`](../frontend/src/pages/PatientActivation.tsx),
[`People.tsx`](../frontend/src/pages/People.tsx).

| ID / requirement | Backend / endpoint | Frontend | Evidence / status | Gap and required correction | Priority |
| --- | --- | --- | --- | --- | --- |
| P01 Activated versus not activated filter | GET `/patients` only filters patient_code/sex and text search. Activation is projected after selecting the page; no activation WHERE clause or filtered total exists. | Patient resource has only a sex filter; no activation selector. | S,L; **MISSING**. | Add authorized server-side state/group filtering before count/pagination, reusing the exact state precedence. Add a directory selector and preserve warnings in grouped results. Filtering only the current frontend page is incorrect. | HIGH |
| P02 Sorting and search | `identity_service.list_records()` escapes substring search over code/name fields and orders by primary key ascending. No user-selected sort. | Search and pagination exist; no sort control. | S,L,F; **PARTIAL**. | Preserve search; add allowlisted sort keys/direction, stable primary-key tie-breaks and activation-aware ordering if requested. Never interpolate unchecked SQL sort identifiers. | HIGH |
| P03 Color-coded patient activation indicators | Response includes authorized `activation_status`. | Directory uses `render: row => activationLabel(...)`, returning plain text. Detail also uses plain strong text. `components/UI.tsx` Badge is not used, and its tone map lacks these six states. | S,F; **MISSING**. | Add one shared activation badge with text/icon plus accessible colors: activated, awaiting, expired/revoked, review-required, and unavailable. Color alone must not carry meaning. | MEDIUM |
| P04 Correct patient detail state | GET `/patients/{id}` and `/patients/{id}/activation-status`; `can_read_status()` requires staff plus activation/account-read permission. | People detail mounts PatientActivation only for authorized non-patient users; refresh/loading/error states and explanations exist. | S,L,B,F; **UNVERIFIED** in live UI. | No missing state endpoint. Browser-check detail/list consistency after issuance and navigation, with both authorized and restricted staff. | MEDIUM |
| P05 Six activation states | `activation_states()` gives link precedence, then any consumed-token history, then latest invitation and expiry/revocation. Existing schema sufficient. | All six labels/descriptions exist; no extra editable activation field. | S,L,B; **VERIFIED** state derivation and contract. | No new state model required. Group/filter this existing truth rather than replacing it. Live data currently exercises only NOT_ACTIVATED; remaining states verified with synthetic fixtures. | LOW |
| P06 Invitation issue/reissue | POST `/patients/{id}/activation-token`, PATIENT_ACCOUNT_ACTIVATE plus staff separation, CSRF, locking and audit. Old unused invitations revoked; no delivery infrastructure implied. | Identity confirmation dialog, manual-delivery text, one-time token display, expiry, hidden-tab/close cleanup and explicit error handling. No automatic POST retries. | S,B,F; **UNVERIFIED** in live UI. | Verify with an approved synthetic account in an authorized browser; do not issue a real invitation for this audit. Keep activation secrets out of URLs/logs/storage. | MEDIUM |
| P07 Expired/revoked/consumed/invalid tokens | POST `/patient/activate`; generic invalid-token response, expiry boundary, patient-first lock, account/link creation and token consumption in one transaction. Consumed history blocks duplicate activation. | Existing public Activation page handles errors; no account/state details exposed in the generic token error. | S,B; **VERIFIED** backend/API behavior under synthetic fixtures. | No confirmed backend gap. Interactive public-form checks remain part of the browser checklist, not evidence of a live token redemption here. | LOW |
| P08 Existing patient-account links | PatientAccountLink, unique associations, patient-role assignment and historical-link precedence; no identifier rewrite or automatic relinking. | Authorized account association shown on patient detail; linked state suppresses invitation actions. | S,B,L; **VERIFIED** model/service behavior, including synthetic historical links. | Preserve numeric relationships and existing credentials. No repair/relink action should be added to a simple activation filter. Active database has no linked patients to inspect interactively. | LOW |
| P09 Portal access and permissions | `api/patient_portal.py`, `dependencies/patient.py`, MFA/session enforcement and ownership-filtered reads. | `auth/PatientAccess.tsx`, PatientShell and patient Portal/Security/PatientReport routes exist. | S, prior cutover/regression evidence, L; **BLOCKED — CONFIG/DATA** for live portal verification. | Zero patient links and no authorized patient browser session. Use separately approved synthetic activation/MFA setup for a real portal walkthrough; do not bypass auth or infer access from staff pages. | MEDIUM |

### Safe grouping of the six states

| Detailed state | Group for the requested filter | Warning/action retained |
| --- | --- | --- |
| ACTIVATED | Activated | Link exists; suspension, disabled state and MFA still independently govern access. |
| NOT_ACTIVATED | Not activated | No portal account/invitation; invitation may be issued by authorized staff. |
| TOKEN_ACTIVE | Not activated | Invitation pending; preserve expiry and deliberate reissue behavior. |
| TOKEN_EXPIRED | Not activated | Invitation expired, not an account suspension. |
| TOKEN_REVOKED | Not activated | Invitation revoked; do not call it “pending.” |
| REVIEW_REQUIRED | Not activated, prominently flagged | Consumed token without link; no automatic reissue/relink. Provide a dedicated review filter/count as well. |

“Unregistered” is ambiguous: these are already registered Patient records but
may lack portal accounts. Keep permanent patient codes immutable. Filter/search
counts must apply the same authorization and state rules as displayed rows.

## 5. Laboratory workspace: frontend reachability and workflow

Core backend files: `api/workflow.py`, `services/workflow_service.py`,
`api/results.py`, `services/result_service.py`, `api/reporting.py`,
`services/reporting_service.py`, `services/report_release_service.py`.
Frontend files: `pages/Orders.tsx`, `Specimens.tsx`, `Results.tsx`, `Reports.tsx`,
`components/LaboratoryProgress.tsx`, `ReportPreview.tsx`, `App.tsx`.

| ID / requirement | Backend / endpoint | Frontend and permission/state behavior | Evidence / status | Gap and required correction | Priority |
| --- | --- | --- | --- | --- | --- |
| W01 Order list/filtering | GET `/lab-orders`: search, status, priority, date bounds, pagination; LAB_ORDER_READ. | Orders page exposes all filters, refresh, clear, priority/status badges and order links. Specimen/result list modes additionally require their read permission. | S,F,L; **UNVERIFIED** in live UI. | Verify composed filters, empty/error states and mobile layout in an authorized browser. No missing filter identified here. | LOW |
| W02 Patient/order details | GET `/lab-orders/{id}` includes PatientSummary with patient_id, patient_code and name, order notes/priority/date. | Orders shows patient through generic `Details`/`display()`; object formatting shows the name but drops the available patient code. No patient-detail link in that summary. Request notes are on Overview. | S; **PARTIAL**. | Display immutable patient code alongside name and add an appropriately permissioned patient link. This is display work, not a change to code generation or access to additional PHI. | HIGH |
| W03 Requested tests/panels | OrderDetail contains panels and expanded numeric-ID-linked items/provenance. | Requested panels/items table and workflow progress present; individual versus panel source is visible. | S,F,B catalog integration; **UNVERIFIED** in live UI. | Verify a multi-panel order and shared analytes interactively; no missing expansion API. | LOW |
| W04 Collection/receipt | POST `/lab-orders/{id}/specimens`, `/specimens/{id}/collect`, `/receive`; mapping and state validation retained. | Register dialog in Specimens tab; Open specimen → Collect/Receive confirmations on detail. Requires register/collect/receive permissions and an open order. Timestamps/history visible. | S,F,B; **UNVERIFIED** in live UI. | Actions exist. Validate the extra order-to-specimen-detail navigation and return path; inline actions are optional usability work, not a missing backend transition. | MEDIUM |
| W05 Specimen rejection | POST `/specimens/{id}/reject` requires SPECIMEN_REJECT. Reason list GET `/lab/rejection-reasons` instead requires REJECTION_REASON_MANAGE. | Reject control exists for COLLECTED/RECEIVED specimens; reason lookup is gated by REJECTION_REASON_MANAGE. Reason/details/recollection history and registration link exist. | S,F; **PARTIAL** for least-privilege operational access. | A user allowed to reject but not manage reasons cannot populate the lookup. Define a narrow read contract for allowed reasons or document/provision the necessary role composition. Do not solve by granting unrelated management rights or weakening rejection authorization. | HIGH |
| W06 Result entry | POST `/lab-order-items/{id}/result`, PATCH `/results/{id}`; drafts only, specimen validation, audit and transactional safeguards. | Results tab lists drafts and opens result form for unfinished items; edit controls disappear after review. New-result form needs LAB_MASTER_READ to fetch the test type. | S,F,B; **UNVERIFIED** in live UI. | Verify operator role includes required read dependencies as well as LAB_RESULT_ENTER. No missing submit button; do not confuse an intentionally blocked lookup with a missing endpoint. | MEDIUM |
| W07 Numeric/qualitative results | `result_service.py` and schemas enforce NUMERIC/TEXT/POS_NEG values and decimal handling. | Numeric input is decimal; POS_NEG uses text; TEXT uses textarea. All result values capped at 100 characters, with separate remarks. | S,F,B; **UNVERIFIED** in live UI. | Verify both numeric and qualitative entry with configured tests. No unsupported dropdown vocabulary should be invented; TEXT summary limitations are documented under catalog. | MEDIUM |
| W08 Units/reference ranges | Resolver and result response return reference context; snapshots prefer selected range unit then test default. | Results table uses selected reference unit first; ranges/flags shown. Entry form shows catalog unit/method; computed context appears after save. | S,F,B,V; **UNVERIFIED** in live UI. | Validate absent and one-sided ranges. UI currently prints low–high with em dashes when a bound is absent; PDF uses explicit ≤/≥. Harmonizing this presentation would improve clarity. | MEDIUM |
| W09 Result review/verification | POST `/results/{id}/review`, `/verify`; separate LAB_RESULT_REVIEW/VERIFY, immutable reviewed/verified values. | Both actions and confirmations exist, selected by DRAFT/REVIEWED state; remarks and provenance timestamps are expandable. | S,F,B; **UNVERIFIED** in live UI. | Verify with distinct authorized roles and rejected out-of-order actions; no missing transition identified. | MEDIUM |
| W10 Report signing/approval | POST `/reports/{id}/signatories`, `/sign`, `/approve`; linked staff identity must sign its own assignment; at least one assignment, all signed and valid sources required for approval. | Reports detail has assign, identity-matched Sign, and conditional Approve actions. Needs SIGNATORY_MANAGE/READ, REPORT_SIGN or REPORT_APPROVE as appropriate; report read remains separate. | S,F,B,Q; **UNVERIFIED** in live UI. | Workflow controls exist. Validate actual signatory/account setup; prerequisite creation itself is missing from UI (W14), not signing logic. | HIGH |
| W11 Report generation/release | POST `/lab-orders/{id}/reports`, POST `/reports/{id}/release`; COMPLETED/verified order and APPROVED report gates. | Generate on completed order's Reports tab; Release on report detail with REPORT_RELEASE. Generated/approved guidance and confirmations present. | S,F,B,Q; **UNVERIFIED** in live UI. | Verify a synthetic full flow after setup. Generate remains visible for a completed order that already has a report; backend correctly rejects duplicates and asks for revision. Hiding/explaining that invalid action is a usability improvement. | MEDIUM |
| W12 Revocation/amendment | POST `/reports/{id}/revoke`, `/revise`; history kept and revised version starts signing/approval again. | Revoke with reason on RELEASED; Revise on RELEASED/REVOKED; version links and status guidance present. | S,F,B; **UNVERIFIED** in live UI. | No missing operation. Validate with synthetic data only; a separate follow-up order does not substitute for an amendment. | MEDIUM |
| W13 PDF/verification access | GET `/reports/{id}/pdf`, POST `/print`, GET `/verification`, public GET `/verify/{token}`. Stored hash checked; download and print auditing retained. | Authenticated preview modal, download, print-copy action, hash/verification URL and blockchain anchoring component. REPORT_DOWNLOAD is distinct from REPORT_READ; preview revokes blob URLs. | S,F,Q,V,C; **UNVERIFIED** in live authenticated UI. | Verify actual browser PDF controls and permissions; API/render behavior is verified, but no live preview click was performed. | MEDIUM |
| W14 Report prerequisite administration | Facility-profile, report-template, signatory CRUD APIs and staff linking exist in `api/reporting.py` / administration services. | Reports selects existing templates/signatories and can assign them. App routes contain no facility-profile, report-template or signatory-profile creation/editing screen. | S; **MISSING** frontend administration. | Add focused authorized setup surfaces using existing APIs, immutable template codes and safe branding handling. Distinguish creating a signatory profile from assigning one to a report. Do not invent signatures or supply privileged default actors. | HIGH |
| W15 Match original visual reference | No backend counterpart. | Original D attachment requests a supplied reference, but available attachments contain zero image/PDF files; no supplied reference found in project docs. | S, attachment inventory; **BLOCKED — REFERENCE**. | Obtain the original file before claiming fidelity. Neutral existing design can be audited independently; do not infer the missing image's layout. This also limits PDF-reference matching. | LOW |
| W16 Repeat testing/referral | No repeat-item/provenance or external-referral operation in existing workflow APIs. New orders are supported. | LaboratoryProgress offers “New request for this patient,” explicitly a new order, not amendment or referral. Recollection registration is separate. | S,F; **PARTIAL** relative to the broader original request. | Existing-business-rule scope is honestly represented. If true repeat/referral remains required, define parent-result linkage, authorization, audit and external workflow first. Do not add a cosmetic referral button or overwrite verified results. | MEDIUM |

### Navigation and detail gaps

The workflow is accessible through real frontend operations; it is not merely
backend functionality. However:

- Overview pending counts are not deep links into filtered work queues.
- “Specimens” and “Results” entry points first show an order directory. Specimen
  transitions require another detail navigation. This is usable but adds clicks;
  batch/inline actions would require explicit state/permission handling.
- Order patient objects display names without their available permanent codes
  (W02), and several mapping/result-entry cells expose numeric request IDs instead
  of a useful test/panel label. Keep IDs for relationships, improve labels only.
- Report actions leave the order tabs for report detail. The return/version link
  exists; signing and release are intentionally distinct stages.
- Report prerequisite creation has no frontend surface (W14). A role's ability
  to assign an existing signatory does not mean it can configure the first one.
- Result draft detection in “Enter a result” checks the currently loaded results
  page. For orders exceeding 20 results, a draft on another page may still offer
  an entry action; backend uniqueness remains authoritative. This is a **source-
  identified pagination risk, not reproduced in this audit**. Add a focused case
  before classifying it as a confirmed defect or changing behavior.

## 6. PDF v2: actual synthetic output inspection

Code: [`report_pdf_v2.py`](../app/services/report_pdf_v2.py),
[`report_presentation.py`](../app/services/report_presentation.py),
[`report_pdf.py`](../app/services/report_pdf.py),
[`reporting_service.py`](../app/services/reporting_service.py),
[`report_release_service.py`](../app/services/report_release_service.py).
Private nullable JSON migration: `migrations/versions/20261018_01_report_presentation.py`.

An audit-only pytest wrapper copied **synthetic** bytes returned by the real
renderer. It did not alter outputs, test assertions, application files or live
storage. Rendering/viewing used pypdfium2 5.14.0 installed only under the temporary
audit directory; no application dependency or lockfile changed.

Directly viewed: the one-page signed v2 report, one-page synthetic-logo report,
both pages of the catalog workflow report, and pages **2, 24 and 47** of the
47-page stress report. The existing stress test also checked all 100 analytes,
end-of-remarks preservation, repeated headers and actual paragraph positions/
non-overlap across the generated output. Not every stress page was visually
inspected, and printer/device or real QR-camera scanning was not performed.

| ID / requirement | Existing backend and PDF surface | Actual evidence / status | Gap and required correction | Priority |
| --- | --- | --- | --- | --- |
| F01 Facility header/branding | Facility snapshot and template heading; safe optional local logo captured at generation. No live remote-image fetch. Report prerequisite UI is absent (W14). | S,B,V confirms real header/logo rendering with synthetic fixture; L shows no REPORT_LOGO_DIR; **BLOCKED — CONFIG/DATA** for deployed branding. | Supply approved facility branding and protected configuration through an authorized setup process. Do not invent a logo or make private directories web-accessible. Header itself works without a logo. | MEDIUM |
| F02 Patient information | Frozen ReportPatientSnapshot: name, permanent code, DOB, sex, age at generation and requesting physician. | S,B,V; **VERIFIED** synthetic PDF output. | No confirmed missing field in the requested scope. Continue using frozen values, not live patient lookups at download. | LOW |
| F03 Laboratory order details | Snapshot captures order code/date/priority; PDF summary displays them. | S,B,V; **VERIFIED**. | No required correction. Display UTC precision can be simplified for readability without changing recorded timestamps. | LOW |
| F04 Department/panel grouping | Captured department/panel plus section labels; ordered groups and repeated table headers. | S,B,V; **VERIFIED** including actual Renal Function Tests grouping. | No confirmed grouping gap. Full-catalog clinical composition remains a separate review. | LOW |
| F05 Test/result/flag/unit/reference | Five-column real snapshot table; numeric and qualitative output, selected reference-unit precedence, bold abnormal values. | S,B,V; **VERIFIED**. | No clipped/lost values found in samples. Keep empty values honestly empty; never manufacture reference intervals. | LOW |
| F06 Specimen information/timestamps | Captures specimen code, collection/receipt and verification timestamps per result. | S,B,V; **PARTIAL**. | **Specimen/sample type is not captured or printed.** Add a frozen specimen-type label for future presentations; never backfill/re-render old released artifacts. Existing type relationships can supply it during generation. | MEDIUM |
| F07 Laboratory remarks/methodology | Frozen result remarks/methodology and report remarks; long paragraphs split independently of result table. | S,B,V; **VERIFIED**. | No lost remarks in stress output. Repeating specimen metadata per analyte is verbose; compact grouping is optional design work. | LOW |
| F08 Real authorized signatories | Successful identity-bound signing captures actual name/designation/capacity/license/time; incomplete signing presentation fails closed. | S,B,V; **VERIFIED** with synthetic authorized identities, not invented production staff. | No required electronic-attribution correction. V2 does not render scanned handwritten signature images; do not claim it does. An unconfigured signature directory does not invalidate electronic signing. | LOW |
| F09 Approval/release metadata | Report code, version, released status, generated/approved/released timestamps and amendment reference. | S,B,V; **VERIFIED**. | No required correction. PDF is an immutable release artifact; subsequent revocation is conveyed by verification/current metadata, not by rewriting its RELEASED text. | LOW |
| F10 QR verification | `qr_png()` receives only the existing public verification URL; release digest and redacted verification response tested. | S,Q,V,C; **VERIFIED** payload/integrity behavior. | QR is visible and URL-only; a physical camera scan is not claimed. Public URL currently returns the existing API verification representation. No patient values or credentials encoded. | LOW |
| F11 Multi-page formatting | A4, repeated group/table headers, report identifier/version/page footer, splittable rows/remarks. | B,V; **VERIFIED** for the inspected and automated stress cases. | No clipping/overlap found. Continuation pages repeat report ID but not patient name/code; adding minimal patient identification and reducing long UTC microsecond strings are optional readability improvements. No original reference available to judge visual matching. | LOW |
| F12 Historical report preservation | NULL legacy presentation uses v1 until release; released downloads read stored bytes/hash, never rerender. New revisions receive v2 independently. | S,B,Q,C,L; **VERIFIED**. | Preserve this behavior. Active database currently has no v2 reports; synthetic output, not a live new release, supplies v2 audit evidence. | LOW |

Synthetic artifacts (temporary, not committed):

- `/tmp/rhu-original-audit-KAZrYt/test_presentation_freezes_sources_signatories_and_is_private-1.pdf` — one page.
- `/tmp/rhu-original-audit-KAZrYt/test_catalog_order_specimen_results_and_pdf_history-1.pdf` — two pages.
- `/tmp/rhu-original-audit-KAZrYt/test_long_multiline_report_repeats_headers_and_preserves_all_values-1.pdf` — 47 pages.
- Corresponding `*-page-N.png` visual evidence, `pdf-inventory.json`, and test logs.

No real patient PDF was regenerated or released for this audit.

## 7. Philippine catalog: import, simulation and clinical readiness

Code: [`philippine_laboratory_catalog.json`](../app/data/philippine_laboratory_catalog.json),
[`starter_catalog_service.py`](../app/services/starter_catalog_service.py),
[`laboratory.py`](../app/api/laboratory.py),
[`StarterCatalog.tsx`](../frontend/src/components/StarterCatalog.tsx),
[`Laboratory.tsx`](../frontend/src/pages/Laboratory.tsx).

Confirmed structural inventory: **5 departments, 39 tests, 5 specimen types,
5 panels, 39 specimen links and 32 panel-member links**. Types: **31 NUMERIC,
5 POS_NEG, 3 TEXT**. Panels: CBC 14 members, differential 5, lipid 4, liver 7,
renal 2. Differential reuses existing CBC test definitions. Every referenced
department/specimen/test/source key is validated; duplicate aliases/members and
unknown relationships are rejected.

| ID / requirement | Backend / frontend implementation | Evidence / status | Gap and required correction | Priority |
| --- | --- | --- | --- | --- |
| C01 Complete linked starter definitions | Versioned manifest and Catalog validators, additive dependency-ordered import, 39 TestSampleType and 32 PanelTest links. `StarterCatalog` exposes definitions and relationships. | S,B and direct manifest inventory; **VERIFIED** structural completeness of the specified inventory. | No count/link defect found. This does not certify assay suitability or a comprehensive national test menu. Plasma and Microbiology are intentionally unassigned placeholders; they must not imply implemented assays. | LOW |
| C02 Preview/confirmation | GET/POST `/lab/starter-catalog`; preview fingerprint, explicit inactive-review acknowledgement, all management permissions plus LAB_MASTER_READ, staff separation/CSRF, transactional import and audit. Stale/conflicting previews fail; reimport creates nothing. | S,B,F,L; **UNVERIFIED** in deployed authenticated UI. | Source/API/component behavior verified. Browser-check preview, all entries, confirmation, conflict/no-change/error states with isolated data. No live POST was performed. | MEDIUM |
| C03 Catalog administration access | `/lab/departments`, `/sample-types`, `/tests`, `/panels`, metadata, sample mapping, sections, memberships and reference/rule APIs. Laboratory/resource pages expose tabs, editors and inactive administrative lookups. | S,F; **UNVERIFIED** in live UI. | Verify realistic operator/admin permission combinations and mobile editors. Do not confuse absence of imported records with absence of the administration screens. | MEDIUM |
| C04 Select tests/panels in orders after activation | Orders lookup active catalog entries; backend rejects inactive tests/panels. Existing API permits explicit authorized configuration/activation. | S,B,L; **BLOCKED — CONFIG/DATA** in the active system. | No starter import; no live panels. Plan reviewed inactive import and separately approved synthetic simulation configuration. No automatic clinical activation. A preview saying “54 proposed additions” does not mean those rows exist. | HIGH |
| C05 Specimen compatibility enforcement | Manifest keys/links validated; specimen registration/results enforce allowed TestSampleType mappings. UI shows allowed samples and specimen guidance. | S,B; **VERIFIED** structural mapping and application enforcement. | Facility assay/container/additive/SOP suitability is **not clinically verified by this audit**. One proposed specimen per assay is not universal method approval. Keep unsupported mappings inactive until reviewed. | MEDIUM |
| C06 Enter configured result types | Real NUMERIC/POS_NEG/TEXT backend contracts and Results form types; synthetic workflow includes creatinine/BUN, pregnancy qualitative result and ABO/Rh text. | S,B,F,V; **UNVERIFIED** in live UI. | No generic type-entry gap found. Urinalysis/stool are 100-character TEXT summaries plus remarks, not structured multi-component examinations. Do not represent them as complete structured clinical forms; approve reporting scope or configure components before clinical use. | MEDIUM |
| C07 Panel components in orders/reports | Order expansion preserves component IDs/provenance; PDF snapshots capture group labels and values. Orders/Reports display them. | S,B,F,V; **UNVERIFIED** in deployed UI. | Synthetic renal panel verified end-to-end; all five memberships structurally checked. Interactive/full end-to-end execution of every panel and all 39 tests was not performed. Extend scenarios before claiming exhaustive coverage. | MEDIUM |
| C08 Simulation using approved synthetic configuration | Existing integration fixture imports inactive definitions, proves rejection, explicitly activates/configures selected synthetic entries via APIs, receives specimens, enters/reviews/verifies results, signs/approves/releases PDF and checks later retirement preserves it. | Fresh `test_catalog_order_specimen_results_and_pdf_history`, B,V; **VERIFIED** representative isolated simulation. | Simulation capability exists for a tested subset; active-site readiness remains C04. This is not proof that the entire catalog is clinically approved or that the live workflow is populated. | LOW |

### Three different readiness decisions

1. **Import readiness:** the definition graph, preview, idempotency, rollback,
   permissions and inactive defaults pass focused tests. Active read-only preview
   has no conflicts. The import itself was not executed live. No claim of a new
   native-MySQL bulk-import concurrency run is made by these SQLite tests.
2. **Simulation readiness:** a representative synthetic API-to-PDF flow passes.
   The live database is not populated/configured for the requested broad catalog
   simulation. Establish approved synthetic values and linked signatories in a
   controlled simulation context; do not import demonstration units/ranges into
   clinical use accidentally.
3. **Clinical-use approval:** remains outside software test evidence. Qualified
   facility review must establish capabilities, assay methods, specimens, units,
   applicable ranges and complete reporting. The importer intentionally does not
   seed clinical intervals, units, methodology or activation. Source links in the
   manifest are provenance, not proof of this facility's authorization. External
   clinical sources were not independently revalidated in this software audit.

## 8. Consolidated corrective implementation plan

No item below is implemented by this audit. Keep Workstream A accepted and
unchanged; all references continue using numeric IDs and immutable display codes.

### Batch 1 — Restore the missing dashboard requirements

**HIGH: D01, D03, D05–D09, D11–D12.**

- Extend dashboard API/schema/service and frontend/types with permissioned
  activation, account, failed-login and signing-stage aggregates. Define windows,
  distinct-record counting, null/unavailable/freshness behavior and filtered links.
- Reuse stored LoginLog/account/link/token/signatory data. Signing-stage counts
  must not change report lifecycle enums or bypass approval validations.
- Decide presence semantics before implementation. If adding last activity,
  bound write frequency, exclude revoked/expired/ineligible sessions, respect
  patient/staff separation and test multiple sessions for one staff identity.
- Add node attention based on actual monitor errors/staleness. Add service
  observation only through a bounded safe interface; no generic remote-command
  endpoint or fictional worker heartbeat.
- Files: `app/api/dashboard.py`, `app/schemas/dashboard.py`,
  `app/services/dashboard_service.py`, `frontend/src/types/dashboard.ts`,
  `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/BlockchainQueue.tsx`,
  `frontend/src/styles/dashboard.css`, `tests/test_dashboard.py`,
  `frontend/src/test/dashboard.test.tsx`. Presence may additionally require
  `app/models/auth_session.py`, `app/dependencies/auth.py`, auth/activity services,
  an explicitly reviewed migration and their tests. Monitor changes, if needed,
  belong in `app/services/blockchain_monitor_service.py`, its schema and the
  existing read-only monitor interface, without changing Fabric infrastructure.
- Acceptance: exact fixture counts across mixed permissions and empty datasets;
  unknown/failed services never shown as healthy zeroes; unknown-user failed
  attempts counted; no duplicate report counts from multiple signatories;
  signed/unsigned/unassigned report states distinguished; browser drilldowns.

### Batch 2 — Patient activation directory completion

**HIGH P01/P02; MEDIUM P03.**

- Add shared SQL state/group predicates matching `activation_states()` precedence,
  applied before totals/pagination. Keep unauthorized state information omitted;
  do not allow a filter to become an unauthorized state-discovery oracle.
- Add stable allowlisted sorts, activation-group/detail filters and a shared
  accessible badge. Preserve REVIEW_REQUIRED as conspicuous and non-issuable.
- Files: `app/api/patients.py`, `app/services/patient_activation_service.py`,
  patient query schemas as needed, `frontend/src/pages/ResourcePage.tsx`,
  `resources.ts`, `PatientActivation.tsx`, `components/UI.tsx`, associated styles,
  `tests/test_patient_activation_states.py`,
  `frontend/src/test/patient-activation-staff.test.tsx`.
- Acceptance: all six states, same name/different code, ties, multiple pages,
  filtered totals, search+sort combinations, expiry boundary, consumed-history
  anomaly, restricted staff, patient-role denial, refresh after reissue. Never
  change the patient code or create another activation-state database truth.

### Batch 3 — Complete workflow setup and reduce navigation obstacles

**HIGH W02/W05/W14; MEDIUM navigation refinements.**

- Show patient code/name and an authorized patient link in order context.
- Resolve reason-lookup authorization with a narrowly reviewed read capability
  or explicit role policy; retain separate manage/reject permissions and CSRF.
- Add existing-API setup screens for facility details, report templates and real
  signatory profiles, with private asset selection only where supported. Preserve
  immutable template codes, approved-template restrictions and staff identity
  binding. Do not invent browser uploads or delivery infrastructure without a
  corresponding reviewed backend capability.
- Add clear prerequisites to unavailable actions; condition duplicate generation
  on known history and link to revisions. Test the paginated-draft risk before
  fixing it. Consider filtered queue links and inline specimen controls only if
  they preserve all current transition confirmations and permissions.
- Files: `frontend/src/pages/Orders.tsx`, `Specimens.tsx`, `Results.tsx`,
  `Reports.tsx`, `resources.ts`, `App.tsx`, navigation components,
  `app/api/workflow.py` / permission catalog for a reviewed reason-read change,
  relevant workflow/frontend tests. Report setup should initially reuse
  `app/api/reporting.py` and its existing validation/services.
- True repeat/referral (W16) requires a separate agreed workflow definition;
  retain the honest new-request behavior until that exists. No speculative
  external-referral subsystem is recommended merely to add a button.

### Batch 4 — PDF detail and approved presentation

**MEDIUM F01/F06; LOW readability/reference matching.**

- Configure approved private branding separately from source deployment.
- Capture specimen type for newly generated presentations and print it with its
  existing code/timestamps. Design compatibility for existing snapshots missing
  that key; never backfill or rerender released PDFs.
- Optionally compact repeated specimen details, format timestamps for readability
  and repeat minimal patient identification on continuation pages. Validate long
  names/remarks and page headers again with raster inspection.
- Files: `app/services/report_presentation.py`, `report_pdf_v2.py`,
  `tests/test_report_pdf_v2.py`; configuration/runbook updates for approved assets.
  No column change is presently demonstrated necessary for the additional
  future JSON presentation field. Obtain the missing visual reference before
  claiming reference fidelity.

### Batch 5 — Approved simulation configuration and browser acceptance

**HIGH active-catalog readiness; MEDIUM verification closure.**

- Review the real preview, then separately authorize inactive import and a
  clearly bounded synthetic configuration. Do not activate all services simply
  to make selection lists nonempty. Review TEXT summary scope explicitly.
- Complete real staff/signatory associations and synthetic portal activation/MFA
  only through existing authorized operations in the selected test context.
- Extend representative simulation to all five panels, remaining result types,
  wrong specimen, missing references, inactive member, duplicate request, and
  corrected-report paths as appropriate. Reuse `tests/test_starter_catalog.py`
  rather than creating a replacement workflow framework.
- Browser acceptance: administrator and restricted staff dashboard; every filter
  and badge; invitation expiry/reissue; patient login/MFA/ownership; order through
  specimen/result/review/sign/approve/release; PDF preview/download/QR; catalog
  conflict/confirmation/idempotency; desktop and mobile loading/empty/error states.
- Close the 23 UNVERIFIED rows only with evidence from authorized browser sessions.
  Keep source/test-backed, browser-backed and clinical-approval claims separate.

## 9. Reproduction and change boundary

Focused commands executed from the main worktree (tests force synthetic settings
and block network access before importing application modules):

```bash
PYTHONPATH=/tmp/rhu-original-audit-KAZrYt:$PWD .venv/bin/python -m pytest \
  -p audit_capture tests/test_dashboard.py tests/test_patient_activation_states.py \
  tests/test_report_pdf_v2.py tests/test_starter_catalog.py \
  -q -ra --tb=short --maxfail=3

.venv/bin/python -m pytest \
  tests/test_phase_5b_release.py::test_release_snapshots_pdf_qr_hash_and_download \
  -q -ra --tb=short

cd frontend
npm run test -- --run src/test/dashboard.test.tsx \
  src/test/patient-activation-staff.test.tsx \
  src/test/laboratory-workspace.test.tsx src/test/starter-catalog.test.tsx \
  src/test/workflows.test.tsx
```

Evidence directory: `/tmp/rhu-original-audit-KAZrYt` (`backend.log`, `frontend.log`,
`qr-check.log`, `live-readonly.json`, synthetic PDFs/PNGs and renderer inventory).
Temporary evidence may be removed by host cleanup; the substantive findings and
exact test results are recorded here. To rerun tests without capturing PDFs, omit
the temporary plugin/PYTHONPATH argument; normal fixtures remain unchanged.

Repository deliverable: **only this document**. No source, schema, dependency
manifest, lockfile, accepted automatic-code behavior, live service configuration,
database record, historical PDF, credential or Fabric asset was modified by the
audit. No migration, restart, deployment, commit or push was performed.
