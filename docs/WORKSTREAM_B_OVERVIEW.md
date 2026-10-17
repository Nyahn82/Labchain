# Workstream B: enhanced Overview Dashboard

The staff Dashboard now presents current workflow totals, pending stages, status
breakdowns and the existing blockchain observations. Counts come from authorized
system records; loading, unavailable and empty states remain distinct. The
interface makes no claim that all-time counts describe today's throughput.

## API and access

`GET /api/v1/dashboard/overview` uses existing session authentication and the
private response wrapper (`Cache-Control: no-store`). Patient-role accounts and
patient-linked accounts are denied, including a patient with an administrator
role. Every returned section is filtered by its existing read permission:

| Field | Required permission | Meaning |
| --- | --- | --- |
| patients | PATIENT_READ | Registered patient records |
| orders | LAB_ORDER_READ | All orders grouped by current status |
| specimens | SPECIMEN_READ | All specimens grouped by current status |
| results | LAB_RESULT_READ | Result items grouped by current status |
| reports | REPORT_READ | All report versions grouped by current status |

The existing active SYSTEM_ADMIN permission bypass applies to staff accounts.
Denied sections are omitted, not reported as zero. Roles and permissions are
checked on every request. Disabled/suspended sessions and inactive roles retain
existing behavior. No new permission, table, migration, write endpoint, CSRF
exception or authentication flow is introduced.

The service performs at most five aggregate data queries after authorization;
it does not fetch patient names, identifiers, clinical values or report content.
No joins inflate counts. Every report version counts separately, including
superseded versions. `generated_at` is the UTC response snapshot timestamp.
Query failures return a generic private 503 response, never fabricated zeroes.

## Frontend behavior

- Responsive totals, accessible status breakdowns and a pending-work panel.
- Pending stages show requested orders, specimens pending collection/receipt,
  draft/reviewed results, and generated/approved reports. These counts do not
  bypass signing, approval or release prerequisites and are not added together
  into a misleading count of unique patients or requests.
- Recent orders reuse the authorized existing list endpoint, limited to five.
  The overview displays order identifiers, priority, status and date; patient
  and clinical details remain in the order workspace.
- Quick actions honor destination permissions, including LAB_ORDER_READ for
  the specimen/result workspaces. Analytics navigation requires ANALYTICS_VIEW.
- The existing BlockchainQueue component remains under BLOCKCHAIN_STATUS_VIEW.
  Fabric observations reuse `/admin/blockchain/overview` under
  BLOCKCHAIN_EXPLORER_VIEW. Cached network observations and queue activity are
  explicitly separate; neither is represented as a live service uptime check.
- Whole-page and section refresh controls use the existing cancellable request
  hook. Old requests are aborted; role/user changes remount permission-sensitive
  sections. Health failures do not hide successful workflow data and vice versa.
- Empty database states show actual zeroes. Missing/malformed summary data and
  HTTP failures show unavailable states with retry controls. Patient names and
  raw server error details are not rendered by the overview.

## Focused verification

Run in the development worktree only:

```bash
.venv/bin/python -m pytest tests/test_dashboard.py -q -ra --tb=short
```

Inside `frontend`:

```bash
npm run test -- --run src/test/dashboard.test.tsx src/test/blockchain.test.tsx src/test/polish.test.tsx src/test/auth.test.tsx
npm run build
```

Backend tests exercise real cookie authentication and aggregate queries against
isolated synthetic SQLite fixtures under the repository's network guards.
Frontend integration tests mount the real application routes with mocked API
responses, covering totals, permissions, patient privacy, loading, zeroes,
malformed data, retries, partial failures, session expiry and cancellation.
They do not constitute a live production/MySQL/Fabric smoke test.

Workstream A is recorded in local commit `38ea407`. Its outstanding native
migration-rehearsal verification remains a **production-release prerequisite** in
[AUTO_CODE_MIGRATION.md](AUTO_CODE_MIGRATION.md). Dashboard implementation does not
remove that gate or authorize a migration, push or deployment.
