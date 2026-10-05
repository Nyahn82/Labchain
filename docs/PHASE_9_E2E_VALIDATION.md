# Phase 9 synthetic end-to-end validation

`scripts/phase9_e2e_validation.py` is an operator HTTP client, not an application
CLI that imports database settings. `scripts/` is new: existing `app/cli` tools
bootstrap accounts/roles or run the worker, whereas this tool must use the public
application API and must never acquire a SQL or Fabric write path.

No production workflow was authorized for execution during implementation. Run
preflight first. Login creates the normal authentication session/audit records;
preflight creates no patient, order, payment, specimen, result, report, account,
activation token, or outbox event. It does not probe systemd, Fabric, or secrets.

## Inspected contracts and state machines

Sources: `app/api/{auth,security_cookies,health,laboratory,patients,staff,physicians,
referring_facilities,administration,workflow,results,reporting,verification,
patient_activation,patient_portal,mfa,blockchain}.py`; corresponding schemas and
services; `app/dependencies/{auth,patient}.py`; `app/models/{identity,workflow,
reporting,auth,blockchain}.py`; `app/main.py`; and the frontend order, specimen,
result, report, patient activation/access, and blockchain presentation code.
There is no `app/auth/` directory: authentication lives in `app/api/auth.py`,
`app/dependencies/auth.py`, `app/security/`, and the auth/MFA services.

The existing Phase 4A/4B, 5A/5B, 6A/6B and 8B status tests were inspected. In
particular, `test_register_mapping_and_selective_processing_without_payment`,
`test_review_verify_provenance_and_immutability_same_actor_allowed`, and the
report signing tests establish optional payment, permitted same-actor result
review/verification, and mandatory staff-account signing identity.

All paths below have the `/api/v1` prefix. Every authenticated POST/PUT/PATCH
requires the session cookie and `X-CSRF-Token`. GETs require no CSRF. Login and
pre-session MFA use the application's same-origin check; unauthenticated
patient activation uses its one-time token. Successful create responses are 201;
transitions and reads are 200. Backend permissions and state checks remain the
authority, including on an interrupted or concurrent run.

| Step | Method and path | Request schema / payload | Permission | Prerequisite → result; returned IDs |
|---|---|---|---|---|
| Patient | POST `/patients` | `PatientCreate`: unique `patient_code`, `first_name=Phase9`, `last_name=Validation-<run-id>` | `PATIENT_CREATE` | New synthetic identity → `patient_id`; DOB/sex/contact fields optional and omitted |
| Order / test selection | POST `/lab-orders` | `OrderCreate`: returned `patient_id`, `physician_id=1`, `priority=ROUTINE`, `test_ids=[1]`, `panel_ids=[]`, synthetic `request_reason` | `LAB_ORDER_CREATE` | Active test/physician → REQUESTED order and item; `order_id`, `items[].order_item_id` |
| Panels (not needed) | POST `/lab/panels`; POST `/lab/panels/{panel_id}/sections`; PUT `/lab/panels/{panel_id}/tests` | `PanelCreate`, `SectionCreate`, `PanelReplacement` | `TEST_PANEL_MANAGE` | Active panel with configured tests may be requested via `OrderCreate.panel_ids`; runner creates no panel |
| Payment (skipped) | POST `/lab-orders/{order_id}/payments` | `PaymentCreate`: `payment_status`, optional amount/method/reference | `PAYMENT_RECORD` | Existing order → append-only `payment_id`; no processing/release gate and no payment update endpoint |
| Specimen | POST `/lab-orders/{order_id}/specimens` | `SpecimenCreate`: `sample_type_id=1`, returned `order_item_ids`, synthetic remarks | `SPECIMEN_REGISTER` | REQUESTED/IN_PROGRESS order/item, compatible sample → specimen PENDING and order/item IN_PROGRESS; `specimen_id` |
| Collection | POST `/specimens/{specimen_id}/collect` | No JSON body | `SPECIMEN_COLLECT` | PENDING → COLLECTED |
| Receipt/acceptance | POST `/specimens/{specimen_id}/receive` | No JSON body | `SPECIMEN_RECEIVE` | COLLECTED → RECEIVED; no separate accept endpoint |
| Result entry | POST `/lab-order-items/{order_item_id}/result` | `ResultCreate`: `result_value="42"`, returned `specimen_id`, synthetic remarks | `LAB_RESULT_ENTER` | No existing result; linked RECEIVED/PROCESSED specimen → DRAFT, specimen PROCESSED; `result_item_id` |
| Result review | POST `/results/{result_item_id}/review` | No JSON body | `LAB_RESULT_REVIEW` | DRAFT with consistent provenance → REVIEWED |
| Result verification | POST `/results/{result_item_id}/verify` | No JSON body | `LAB_RESULT_VERIFY` | REVIEWED → VERIFIED; item COMPLETED; all noncancelled items completed → order COMPLETED |
| Report generation | POST `/lab-orders/{order_id}/reports` | `GenerateRequest`: `template_id=1`, synthetic remarks | `REPORT_GENERATE` | COMPLETED order, exactly one VERIFIED result per item, issuing facility, no previous report → GENERATED immutable snapshots; `report_id` |
| Assign signatory | POST `/reports/{report_id}/signatories` | `AssignRequest`: `signatory_id=1`, `signatory_type=LAB_IN_CHARGE`, `sort_order=1` | `SIGNATORY_MANAGE` | GENERATED, active signatory/staff → unsigned assignment; `report_signatory_id` |
| Sign | POST `/reports/{report_id}/sign` | `SignRequest`: returned `report_signatory_id` | `REPORT_SIGN` **and staff-account link** | GENERATED, unsigned assignment belonging to report, actor linked to signatory staff 1 → `signed_at` |
| Approve | POST `/reports/{report_id}/approve` | No JSON body | `REPORT_APPROVE` | GENERATED, valid verified snapshots, every assignment signed → APPROVED |
| Release | POST `/reports/{report_id}/release` | No JSON body | `REPORT_RELEASE` | APPROVED, intact signed snapshots, active matching template, configured PDF storage/public URL → RELEASED, AUTHENTIC verification, transactional outbox release event |
| Staff detail/anchoring | GET `/reports/{report_id}` | None | `REPORT_READ` | `anchoring.status` plus separate `release`, `revocation`, `supersession`; each has `status`, `confirmed_at`, `transaction_id`, `block_number` |
| Global queue | GET `/blockchain/status` | None | `BLOCKCHAIN_STATUS_VIEW` plus SYSTEM_ADMIN/LAB_STAFF/LAB_SUPERVISOR/DOCTOR role | MySQL counts and queue-derived `worker_health`; null `delivery_enabled` means unknown, never disabled |
| Staff verification | GET `/reports/{report_id}/verification` | None | `REPORT_READ` | Released/revoked verification → `verification_status`, `verification_url`, hash/timestamps; runner never prints URL/token |
| Public verification | GET `/verify/{verification_token}` | None; anonymous client | Public | VERIFIED/REVOKED/ALTERED/NOT_FOUND remain primary; safe `blockchain_status`, optional `blockchain_confirmed_at`; exact field allowlist enforced |
| Patient access | GET `/patient/me`; GET `/patient/reports`; GET `/patient/reports/{report_id}`; GET `/patient/reports/{report_id}/pdf` | None; list supports bounded filters | PATIENT role, account ownership, required MFA | Only own RELEASED reports; safe `blockchain_verification={status,confirmed_at}`; foreign/revoked reports return 404 |
| Revoke (later gate) | POST `/reports/{report_id}/revoke` | `RevokeRequest`: synthetic `reason` | `REPORT_REVOKE` | RELEASED → REVOKED + verification revoked + revocation outbox event; historical PDF retained |
| Revise (later gate) | POST `/reports/{report_id}/revise` | `GenerateRequest` | `REPORT_REVISE` | RELEASED/REVOKED → a new GENERATED version with `supersedes_report_id`; original remains current until replacement is signed/approved/released |
| Supersede (later gate) | POST replacement `/reports/{report_id}/release` | No JSON body | `REPORT_RELEASE` | Replacement APPROVED → RELEASED; original revoked, supersession event for original and release event for replacement |

No endpoint adds tests to an already-created order: requested individual tests
and panels are selected in `OrderCreate`, which expands panels server-side.
`"42"` fits NUMERIC DECIMAL(12,3) exactly. It is synthetic and has no medical
meaning. Reference ranges are not required; missing ranges produce no flag.

Existing master IDs are all 1: issuing facility, department P9LAB, sample type,
test P9NUM, referring facility, requesting physician, staff P9SIGN01, signatory,
and template P9REPORT. Preflight reads and verifies these and test/sample mapping.
Facility profiles and referring facilities have no `is_active` field; the runner
checks identity/existence instead. No records are seeded or repaired by preflight.

Read permissions: `PATIENT_READ`, `LAB_ORDER_READ`, `SPECIMEN_READ`,
`LAB_RESULT_READ`, `REPORT_READ`, `LAB_MASTER_READ`, `FACILITY_PROFILE_READ`,
`REFERRING_FACILITY_READ`, `PHYSICIAN_READ`, `STAFF_READ`, `SIGNATORY_READ`,
`REPORT_TEMPLATE_READ`, and `BLOCKCHAIN_STATUS_VIEW`. Write permissions are those
listed for the baseline rows above. The signer needs only `REPORT_SIGN` for its
separate client; the operator does report reads/assignments. SYSTEM_ADMIN bypasses
permission checks but **does not** bypass staff identity or PATIENT ownership.

## Commands and authentication

From `/opt/rhu-labchain`:

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --preflight --signer-login
# Same safe default:
.venv/bin/python scripts/phase9_e2e_validation.py --signer-login
```

Username uses `input`; passwords/TOTP/recovery codes use `getpass`. No password
CLI flag, environment credential, credential file, cookie dump, or traceback is
used. HTTP redirects are refused so credentials cannot follow another origin.
Use `--signer-login` to authenticate a separate account linked to staff 1
(`P9SIGN01`). Omitting it fails preflight; there is no operator fallback.
The signer must be ACTIVE, have one non-admin/non-patient role, and have exactly
`REPORT_SIGN` as its effective permissions. Configurable cookie **names** support installations
with renamed cookies. Values stay in memory. Every write has CSRF except login,
pre-session MFA, and the application's public activation endpoint.

If staff 1 has no linked account, an administrator must separately provision it
using POST `/staff/1/account` (`StaffAccountCreate`: username, password, role_codes;
permission `ACCOUNT_CREATE`, plus `ROLE_ASSIGN` and grant-subset checks for a
non-admin), with a role granting only REPORT_SIGN. See
[signer setup](PHASE_9_SIGNER_SETUP.md) for supported discovery, safe provisioning,
and the current missing role-management API blocker. The runner does
not create staff credentials, grant roles, link admin implicitly, or modify SQL.
The user/account must be active. The existing `/auth/me` staff identity is the
preflight source of truth; no database query is necessary.

**Later, only after successful preflight and explicit operator authorization:**

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --execute --signer-login
```

The operator and signer must have different user IDs, including before each signing action.
This command creates a synthetic patient, order, specimen, result and report;
signs/approves/releases it; and thereby causes the existing outbox/worker to
submit evidence. It does not directly call Fabric. A successful baseline leaves
the report RELEASED. It never automatically revokes or revises it.

Run IDs use UTC `P9-YYMMDDhhmmss-XXX` (random suffix), 19 characters to fit the
actual 20-character patient-code bound. Journals default to `.phase9-runs/`,
ignored by Git, with mode 0600 and an exclusive file lock. They contain run ID,
origin, returned numeric IDs, steps, safe receipt metadata, and queue counts only.
No credentials, patient body, results payload, public token, or activation token
are persisted. `--state-file` must name a new file; existing files are not replaced.

Before a workflow write, the runner re-reads relevant IDs, ownership, and states,
then fsyncs a pending intent. A failed, timed-out, malformed or interrupted write
stops later steps. **There is no automatic POST retry.** A pending intent requires
manual reconciliation through supported read APIs; do not delete it and blindly
rerun the baseline. The tool intentionally cannot resume incomplete baseline
writes. Even a crash after server commit but before journal confirmation fails
closed. A journal interrupted after a recorded successful release can resume
polling/public checks without creating another record:

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --execute --signer-login \
  --resume-state .phase9-runs/<journal>.json
```

Polling defaults to 10 seconds, 300-second deadline. Options permit 5–60-second
intervals and 5–1800-second deadlines. PENDING/PROCESSING/RETRYING are observed
without requiring every intermediate state. FAILED/NOT_ANCHORED/unknown states
fail; CONFIRMED must have a staff receipt. Queue deltas are informational because
the global queue includes concurrent work. The per-report receipt proves this
report's committed evidence; the tool does not claim to check live peer/service
availability. PDF storage/public-base-url readiness has no supported preflight
endpoint and is only proven by the later normal release. No outage tests occur.

## Separately gated later subphases

These require `--execute --resume-state` from a **previously confirmed** baseline.
Lifecycle modes additionally prompt to type the synthetic run ID, revalidate the
patient code/name, order and report snapshots, and only touch that run's report:

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --execute --signer-login \
  --resume-state .phase9-runs/<journal>.json --test-revocation
# Or on a still-released baseline:
.venv/bin/python scripts/phase9_e2e_validation.py --execute --signer-login \
  --resume-state .phase9-runs/<journal>.json --test-revision
```

Revocation checks its lifecycle confirmation and REVOKED public state. Revision
generates a new snapshot, signs/approves/releases it, confirms both the replacement
release and original supersession, and checks both public states. These modes are
mutually exclusive and are not part of the first baseline. If interrupted during
either subphase, reconcile via APIs; automatic lifecycle-write replay is refused.

Patient activation is normal staff issuance plus public redemption:
POST `/patients/{patient_id}/activation-token` (`PATIENT_ACCOUNT_ACTIVATE`, CSRF),
then POST `/patient/activate` (`ActivationRequest`, one-time token, username,
12+ character password). It creates only PATIENT role membership and does not
auto-login. The patient subsequently uses `/auth/login` and, if challenged,
`/auth/mfa/verify` or `/auth/mfa/recovery`. Required initial MFA enrollment must be
completed through the normal patient UI; the runner never displays TOTP secrets,
disables MFA, resets MFA, or bypasses enrollment.

Default baseline skips the portal. For a separately activated synthetic account:

```bash
.venv/bin/python scripts/phase9_e2e_validation.py --execute --signer-login \
  --resume-state .phase9-runs/<journal>.json --patient-portal
```

To explicitly request activation of **only the journal's synthetic patient**, add
`--activate-patient`. Credentials are entered interactively, and the one-time token
is consumed only in memory. If MFA enrollment is required, the tool stops and the
operator finishes enrollment via `/patient/login` before rerunning portal checks
**without** `--activate-patient`. No repeated token issuance or activation on an
uncertain outcome is attempted. Patient validation uses its own cookie jar, checks
`/auth/me` and `/patient/me` against the journal patient, and uses only the owned
report endpoint. It does not test other patients' production IDs. Unit tests cover
wrong-owner/admin rejection and privacy independently of production.

## Focused verification

```bash
.venv/bin/python -m pytest tests/test_phase9_e2e_validation.py -vv -ra --tb=long
git diff --check
```

The test suite uses mocked HTTP and local journals. The repository's existing
`tests/conftest.py` blocks network access and supplies synthetic configuration
before importing OpenAPI. No production API writes, direct SQL, Fabric operations,
full-suite run, deployment, service restart, commit, or push are part of these tests.

## Implementation validation results (4 October 2026)

- Focused runner tests: **49 passed**, using mocked HTTP with the repository
  network guard. Python compilation and `git diff --check` passed.
- Production command run: `.venv/bin/python scripts/phase9_e2e_validation.py --preflight`.
- Health, MySQL readiness, deployed route/schema compatibility, operator
  permissions, all nine existing master records, and default test/sample mapping
  passed.
- Queue: pending 0, processing 0, confirmed 1, failed 0, dead 0; queue state IDLE;
  worker enablement not reported. No service or peer liveness inference was made.
- Preflight returned **FAIL (exit 1)** because the authenticated `admin` account
  was not linked to staff 1. This is a real prerequisite, not a permission bypass
  opportunity. Supply an existing valid linked signer with `--signer-login`, or
  separately provision that account through normal administration, before execution.
- No `--execute` invocation, patient/order/report creation, release, new outbox
  event, direct SQL, Fabric submission, account activation, deployment, service
  restart, commit or push was performed during this implementation task.
