# Step 26 regression triage

Diagnosis uses `/tmp/rhu_step25.ej3BEv/backend.log`, `frontend.log` and
`build.log`, plus development source inspection. No backend tests, migrations,
MySQL probes, live API calls or provisioning commands were executed in this step.
The saved build passed TypeScript and Vite. The backend summary contains 108
failures, 77 setup errors, 1,728 passes, 17 skips and two deprecation warnings.

## Root causes and counts

All 185 unsuccessful backend cases are accounted for below. Counts describe
observed stopping points; further assertions may become reachable after fixes.

| Group | Failed | Setup errors | Automatic-code related? |
| --- | ---: | ---: | --- |
| Shared release helper submits forbidden `template_code` | 79 | 34 | Yes: outdated test API request |
| Old global Alembic head expectation | 18 | 11 | Yes: new migration head |
| Current model inventory omits `code_sequence` | 2 | 0 | Yes: new model |
| Phase 9 validation CLI uses manually assigned patient codes | 3 | 0 | Yes: actual CLI compatibility defect |
| Missing Fabric `cryptogen` executable | 0 | 32 | No: development prerequisite |
| Missing gateway-adapter `@grpc/grpc-js` dependency | 6 | 0 | No: separate Node package installation |
| **Total** | **108** | **77** | **147 code-related; 38 unrelated** |

### 1. Shared release fixture/helper: 113 cases

`tests/test_phase_5b_release.py:ready()` creates `/report-templates` with
`{'template_code': 'GEN', ...}`. The create schema correctly rejects this field.
The error is `AssertionError: {"detail":"Invalid request fields or query parameters."}`
followed by `assert 422 == 201` in `test_phase_4a_workflow.py:create()`.

Affected modules and observed outcomes:

- `tests/test_phase_5b_release.py`: 32 failures.
- `tests/test_phase_8b_outbox.py`: 31 failures.
- `tests/test_phase_8b_status.py`: 16 failures and 7 setup errors.
- `tests/test_phase9_monitor.py`: 9 setup errors.
- `tests/test_phase_6a_patient_portal.py`: 17 setup errors.
- `tests/test_phase_6b_mfa.py`: 1 setup error.

Representative: `test_phase_5b_release.py::test_release_snapshots_pdf_qr_hash_and_download`.
A setup-error example is `test_phase9_monitor.py::test_integrity_verified_is_read_only_and_does_not_return_pdf`.
The same helper runs either inside a test body (FAILED) or while building the
`released`/`two_reports` fixture (ERROR). These are not 113 independent defects
in release, audit, MFA, report immutability or blockchain processing: those checks
are blocked before their intended behavior is exercised.

Recommended correction: remove the manual field from `ready()`, verify the returned
`TMP-` code, and retain all existing release/security/snapshot assertions. Preserve
manually seeded historical identifiers; those direct ORM fixtures are valid.

Sequence initialization is already present: the function-scoped SQLite `env`
clones current model metadata; `lab_api` seeds DEPARTMENT/TEST/PANEL;
`workflow_api` seeds REJECTION_REASON; `reports_api` seeds REPORT_TEMPLATE.
The release fixture chain imports these updated fixtures. No missing-sequence
exception appears in this log. Do not add speculative global seed state.

### 2. Shared migration-head assumption: 29 cases

`tests/test_phase_2a_migration.py:revision()` asserts the current head equals
`HEAD = "20261005_01"`. The actual development head is `20261015_01`.
Representative error: `assert ['20261015_01'] == ['20261005_01']` in
`test_phase_2a_migration.py::test_relational_constraints_and_round_trip` (setup).
`test_alembic_online_environment_reuses_application_engine` instead reports the
same mismatch as scalar strings after using its substituted SQLite engine.

Affected modules: `test_phase_2a_migration.py` (7 failed/1 error),
`test_phase_2b_migration.py` (1/1), `test_phase_2c_migration.py` (1/4),
`test_phase_2d_migration.py` (1/5), `test_phase_3a_migration.py` (2/0),
`test_phase_6a_migration.py` (2/0), `test_phase_6b_migration.py` (2/0),
`test_phase_8b_migration.py` (1/0), `test_phase_10_migration.py` (1/0).
All are under `tests/`.

Recommended correction: distinguish the current repository head from fixed
historical revision constants. Update the current-head assertion to `20261015_01`,
while retaining Phase 10's revision `20261005_01` and its parent `20260924_01`.
Do not blindly change every `HEAD`: Phase 10 imports the shared constant both as
latest head and as the specific migration to upgrade/downgrade. Other modules
alias their historical revision as HEAD and the repository head as CURRENT_HEAD.
Keep historical SQL scope, foreign-key, data-preservation and downgrade assertions.
Do not enable downgrading the automatic-code migration or generate its data-reading
upgrade as though it were a historical pure-DDL offline script.

### 3. Model inventory: two cases

`test_phase_3a_migration.py::test_session_schema_and_only_one_new_infrastructure_table`
and `test_phase_6a_migration.py::test_activation_model_and_exact_infrastructure_scope`
compare the entire current `Base.metadata.tables` against a pre-automatic-code
allowlist. Actual error: `Extra items in the left set: 'code_sequence'`.

Recommended correction: explicitly include `code_sequence` in the current-model
inventory, retaining exact table-set checks for each historical migration. Do not
remove the new model or loosen schema checks to arbitrary subsets.

### 4. Phase 9 CLI contract drift: three failures

Affected: `tests/test_phase9_e2e_validation.py`:
`test_preflight_never_writes_and_checks_actual_contract`,
`test_contract_drift_fails_before_writes`, and
`test_main_defaults_to_preflight_without_a_journal`.

Actual diagnostic: `Planned payload includes unsupported fields.` The preflight
returns false / exit 1; the drift test expects a `required fields` diagnostic but
hits the already-invalid baseline first.

This is a real compatibility defect in `scripts/phase9_e2e_validation.py`, not an
allocator defect. `check_contracts()` still includes `patient_code` in its sample
PatientCreate request. The execution path also posts `patient_code=self.run_id`
and compares patient responses, report snapshots and portal responses to that
run ID. Merely adjusting the test's expected message would leave the CLI broken.

Recommended correction: omit the field from sample and real create requests;
capture the generated patient code from the response and preserve it in the
journal/resume path for all later identity/snapshot checks. Keep the distinct run
marker in supported descriptive fields and preserve ownership, resume, no-write
preflight, journal validation and security checks. Update the fake backend and
contract fixtures accordingly. Keep existing manually seeded reference data such
as P9SIGN01/P9REPORT unless its separate provisioning contract changes.

### 5. Fabric prerequisites: 32 setup errors

`blockchain/network/tests/test_app_client.py`: 11 errors.
`blockchain/network/tests/test_monitor_client.py`: 21 errors.
Representative: `test_app_client.py::test_pinned_extend_and_runtime_unchanged_idempotent`.
Actual error: `FileNotFoundError: [Errno 2] No such file or directory: 'cryptogen'`.

Both use the same module-scoped `original` fixture (imported by monitor tests).
It prepares a separate synthetic network with the repository tools directory on
PATH; failure happens before per-test copied fixtures and assertions run. The
network configuration pins Fabric 2.5.16. Other Fabric tests explicitly skip when
`LABCHAIN_FABRIC_TOOLS` is unavailable (the 17 skips); these fixtures currently do
not make the missing prerequisite equally clear.

Recommended correction: prepare the pinned tooling in the development test
environment and validate the fixture's expected tools path. Add explicit, honest
prerequisite reporting consistent with the native-test policy if appropriate;
do not replace real crypto verification with permissive mocks or disable security
checks. Provisioning or installing tools is outside this diagnosis step.

### 6. Gateway-adapter dependencies: six failures

Affected: `tests/test_phase_8b_worker_deployment.py`.
Representative: `test_preparation_idempotent_client_only_and_no_secret_file`.
Actual error: `Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@grpc/grpc-js'`
imported by `blockchain/gateway-adapter/src/connection.js`.

The fake host invokes the real offline `check-credentials.js` against copied
synthetic certificates. The development gateway adapter has its own package.json
and lockfile; frontend `npm ci` does not install these dependencies. Node 24 matches
the adapter's declared engine. Install its locked dependencies in that development
package in a separately authorized preparation step, then rerun the module. Keep
the real credential validation and refusal tests intact.

## State, ordering and other observations

- There is no logged `Code sequence is not configured`, `no such table:
  code_sequence`, `PendingRollbackError`, `InvalidRequestError`, or transaction-
  already-begun error. No evidence here identifies an allocator concurrency or
  transaction defect. Blocked tests could expose additional issues after repair.
- SQLite API fixtures use per-test temporary databases and fresh apps with
  monkeypatch teardown. Only the password hash is module-scoped. Directly seeded
  legacy patient/staff/test codes are deliberate and must remain valid.
- Shared-helper and constant imports explain the fan-out; this is not evidence
  that test order mutates data. The Fabric original fixture is module-scoped but
  fails before initialization; tests ordinarily operate on per-test copies.
- No order-randomization or isolated backend reruns were performed, so absence of
  hidden ordering dependencies is not proven. Validate in focused batches first.
- The two saved warnings are Starlette's httpx TestClient deprecation and AnyIO's
  BlockingPortal alias deprecation. Neither is the stopping cause of these cases.

## Frontend correction

`frontend/src/test/monitor.test.tsx` assigned the promise resolver only when the
mock overview request was invoked, then used it immediately after finding the
heading and loading text. `useResource` initializes loading before its effect
starts the request. Rendering the heading therefore does not guarantee that the
mock resolver exists. This is a test synchronization defect, unrelated to codes;
no monitor application defect was identified.

The test now uses Testing Library `waitFor` to observe the actual mocked overview
GET before asserting loading and resolving the deferred response. Existing
healthy-peer, OFFLINE/DEGRADED, authentication and permission assertions remain.
There are no sleeps or weakened assertions. Mocks are restored and globals
unstubbed after each test by the existing setup.

Executed only:

```bash
npm --prefix frontend run test -- --run src/test/monitor.test.tsx
```

Result: **16 passed, 0 failed**, one test file. `git diff --check` also passed.

## Recommended correction order and focused commands

These commands are recommendations for later correction batches, not commands
executed during this diagnosis. Run from `/home/rhuadmin/rhu-labchain-dev`.

1. Fix the shared release helper first, then unblock the shared migration helper
   and explicit model inventories. Start with a representative from each affected
   downstream API family rather than rerunning all 113 blocked cases immediately:

```bash
.venv/bin/python -m pytest -q -ra --tb=short --maxfail=3 \
  tests/test_phase_5b_release.py::test_release_snapshots_pdf_qr_hash_and_download \
  tests/test_phase9_monitor.py::test_integrity_verified_is_read_only_and_does_not_return_pdf \
  tests/test_phase_6a_patient_portal.py::test_detail_snapshots_and_internal_fields_not_exposed \
  tests/test_phase_6b_mfa.py::test_cross_patient_after_real_mfa \
  tests/test_phase_8b_outbox.py::test_release_atomic_capture_offline_and_uuid \
  tests/test_phase_8b_status.py::test_staff_detail_and_public_release_status
```

2. Validate historical revision separation and exact inventories using the nine
   migration modules. These checks compile SQL or use isolated SQLite; exclude
   the Phase 10 native MySQL test:

```bash
.venv/bin/python -m pytest -q -ra --tb=short --maxfail=3 \
  tests/test_phase_2a_migration.py tests/test_phase_2b_migration.py \
  tests/test_phase_2c_migration.py tests/test_phase_2d_migration.py \
  tests/test_phase_3a_migration.py tests/test_phase_6a_migration.py \
  tests/test_phase_6b_migration.py tests/test_phase_8b_migration.py \
  tests/test_phase_10_migration.py -k 'not native_mysql'
```

3. Correct the Phase 9 client contract and generated-code journal/resume behavior,
   then validate its mocked offline tests (do not execute the CLI against a server):

```bash
.venv/bin/python -m pytest tests/test_phase9_e2e_validation.py -q -ra --tb=short --maxfail=3
```

4. Resolve the unrelated development prerequisites, then run each group separately:

```bash
.venv/bin/python -m pytest blockchain/network/tests/test_app_client.py blockchain/network/tests/test_monitor_client.py -q -ra --tb=short --maxfail=3
.venv/bin/python -m pytest tests/test_phase_8b_worker_deployment.py -q -ra --tb=short --maxfail=3
```

Reassess actual application defects only after shared setup and contract blockers
are removed. Expand to the six affected API modules after representative cases
pass. Do not use a complete backend run as the first feedback loop.

## Complete affected-module inventory

| Module | Failed | Errors |
| --- | ---: | ---: |
| blockchain/network/tests/test_app_client.py | 0 | 11 |
| blockchain/network/tests/test_monitor_client.py | 0 | 21 |
| tests/test_phase9_monitor.py | 0 | 9 |
| tests/test_phase_2a_migration.py | 7 | 1 |
| tests/test_phase_2b_migration.py | 1 | 1 |
| tests/test_phase_2c_migration.py | 1 | 4 |
| tests/test_phase_2d_migration.py | 1 | 5 |
| tests/test_phase_6a_patient_portal.py | 0 | 17 |
| tests/test_phase_6b_mfa.py | 0 | 1 |
| tests/test_phase_8b_status.py | 16 | 7 |
| tests/test_phase9_e2e_validation.py | 3 | 0 |
| tests/test_phase_10_migration.py | 1 | 0 |
| tests/test_phase_3a_migration.py | 3 | 0 |
| tests/test_phase_5b_release.py | 32 | 0 |
| tests/test_phase_6a_migration.py | 3 | 0 |
| tests/test_phase_6b_migration.py | 2 | 0 |
| tests/test_phase_8b_migration.py | 1 | 0 |
| tests/test_phase_8b_outbox.py | 31 | 0 |
| tests/test_phase_8b_worker_deployment.py | 6 | 0 |

Only the frontend test and this report changed in Step 26. Backend implementation,
network guards, security checks, production files/services and database state were
not modified.
