# Major update release readiness: Workstreams A–E

Review completed 19 October 2026 (Asia/Singapore). Regression artifacts are dated
18 October 2026 UTC. Development: `/home/rhuadmin/rhu-labchain-dev`, branch
`major-update-v1`. **Recommendation: NOT YET READY FOR DEPLOYMENT.**

The integrated development checks have no unresolved failure after the focused
corrections below. Release authorization still requires native migration evidence,
verified recovery capability, an operational writer fence, and a dependency-risk
decision. Passing application tests does not establish those conditions.

## 1. Release identity and repository review

| Workstream | Local commit | Scope |
| --- | --- | --- |
| A | `38ea407050fbaa30d5de14d785aa0c9388b9a81f` | Transactional automatic identifiers for seven resources |
| B | `ae37c1bb290abbde1b50d64d8d8a95e751bc6524` | Permission-aware Overview Dashboard |
| C | `6d3e527c98b27cbaddc3afd6435097a5beb772e9` | Patient activation states and secure staff invitation workflow |
| D | `42b276bd7ad2aaabfef21ed6ff5e3b9fb38110af` | Laboratory workspace and frozen PDF v2 presentation |
| E | `dcb6bfb4d81963bd62791f9384adf5f68efa4924` | Inactive Philippine starter catalog and atomic, idempotent import |

E was committed locally during this review. Its 11 files contain only intended
API/service code, catalog JSON, frontend components, tests and documentation:

- `app/api/laboratory.py`
- `app/data/philippine_laboratory_catalog.json`
- `app/services/starter_catalog_service.py`
- `docs/WORKSTREAM_E_LABORATORY_CATALOG.md`
- `frontend/src/components/StarterCatalog.tsx`
- `frontend/src/pages/Laboratory.tsx`
- `frontend/src/pages/ResourcePage.tsx`
- `frontend/src/pages/resources.ts`
- `frontend/src/test/starter-catalog.test.tsx`
- `tests/test_phase_3c_laboratory.py`
- `tests/test_starter_catalog.py`

Review and a non-disclosing pattern scan found no passwords, private keys,
credential-bearing database URLs, production data or generated artifacts in E.
All new clinical/catalog entities are inactive. No database import was executed.

The following integration corrections and this report are included in the
authorized local integration commit; `dcb6bfb` alone does not reproduce the
corrected validation state:

- `frontend/src/test/automatic-codes.test.tsx`: scope the Hematology option query
  to the creation form's required select, avoiding the new directory filter.
- `scripts/mysql_migration_rehearsal.py`: select the exact ancestors of its pinned
  automatic-code head instead of copying later release migrations into an
  intentionally ten-revision harness. Revision bytes and isolation checks remain.
- `tests/test_mysql_migration_rehearsal_safety.py`: retain exact inventory and byte
  checks, verify exclusion of the later PDF migration, and reject an unexpected
  historical ancestor inventory.
- `docs/MYSQL_MIGRATION_REHEARSAL.md`: explicitly document that historical scope.
- `docs/MAJOR_UPDATE_RELEASE_READINESS.md`: this review and proposed release procedure.

The integration commit also includes [the native release rehearsal plan](NATIVE_RELEASE_REHEARSAL_PLAN.md).
Before release, record the final approved commit and artifact checksums. No application business rule, migration identifier,
manifest or dependency version was changed during the corrective work.

Keep `.env`, virtual environments, `node_modules`, `frontend/dist`, test caches,
logs, local Fabric tools, generated identities/certificates, ledgers, bundles,
wallets, report PDFs and private runtime assets outside Git. Existing ignore rules
remain. Logs are in `/tmp` and must not be treated as durable release evidence;
archive sanitized results in the approved private evidence store before cleanup.

## 2. Verification results and limits

| Check | Observed result |
| --- | --- |
| Single comprehensive permitted backend run | **2,107 passed, 1 failed, 0 errors, 0 skipped**, 3 deselected; 17m04s |
| Focused backend correction | **163 passed**, 0 failed: rehearsal safety, read-only verifier safety and automatic-code migration tests |
| Fabric tests previously skipped | **17 passed**, 0 failed/skipped, included in the backend run above |
| Complete frontend run | **340 passed, 1 failed**; 17 files passed, 1 failed |
| Focused frontend correction | **23 passed**, 0 failed, `automatic-codes.test.tsx` |
| TypeScript and Vite production build | **PASS**, `tsc --noEmit && vite build` |
| Migration metadata | **PASS**, one linear 11-revision chain, head `20261018_01` |
| Corrected Python syntax | **PASS**, compile-only, no execution or database connection |
| `git diff --check` | **PASS** |
| Runtime-only npm audit | **0 vulnerabilities** reported |
| Full npm audit | **1 high** development/build dependency advisory; see section 6 |

The backend failure was the historical rehearsal copying the newer PDF revision
and rejecting its chain. It was reproduced offline and fixed without weakening
its pin or modifying any database. The frontend failure was a duplicate option
selector after E added the department filter; production form behavior was intact.
No arbitrary sleep, skip, mock substitution for cryptography, or assertion removal
was used. Full suites were not repeated after these corrections.

Across the original run and focused correction, all **2,108 original executed
backend cases** have passing evidence, plus **one new guard case** (2,109 distinct
cases). All **341 frontend cases** have passing evidence across the full and
focused runs. These are reconciled results, not claims that a second clean full
run occurred. The focused counts overlap the original run and must not be added
to it as if they were all new tests.

### Native MySQL exclusion required by this task

The request prohibited applying migrations to MySQL. The repository contains tests
that start disposable socket-only MySQL and apply real migrations. **74 such tests
were not executed**: 71 from ten ignored modules and three explicitly deselected
cases. Collection-only verification counted them without invoking their fixtures.
This is comprehensive coverage of the permitted suite, not an unrestricted full
backend certification. Network protections were not weakened.

Ignored modules:

```
tests/test_phase_3b_mysql.py
tests/test_phase_3c_mysql.py
tests/test_phase_4a_mysql.py
tests/test_phase_4b_mysql.py
tests/test_phase_5a_mysql.py
tests/test_phase_5b_mysql.py
tests/test_phase_6a_mysql.py
tests/test_phase_6b_mysql.py
tests/test_phase_8b_delivery_mysql.py
tests/test_phase12_mysql.py
```

Deselected cases:

```
tests/test_phase_8b_migration.py::test_mysql_migration_and_constraints
tests/test_phase_10_migration.py::test_native_mysql_migration_queries_and_login_serialization
tests/test_phase_11_mysql.py::test_native_analytics_with_rich_synthetic_data
```

The reported earlier 10/10 native allocator-probe success remains historical
evidence; it was not rerun or treated as a combined migration rehearsal. Obtain
separate authorization for the omitted native regression and release rehearsal.

Fabric tools were executable version **2.5.16**, commit `f871cf9`, under
`/home/rhuadmin/rhu-labchain-dev/blockchain/network/tools`.
`LABCHAIN_FABRIC_TOOLS` was set to that directory for this run.
The nine `BootstrapTests` in `blockchain/network/tests/test_network.py` and eight
`SingleBootstrapTests` in `blockchain/network/tests/test_single_vps.py` used
synthetic identities and temporary directories. No production Fabric state or
credentials were used. Local cryptographic verification remained real.

Evidence:

- `/tmp/rhu-major-integration-backend.log` and `.xml`
- `/tmp/rhu-major-focused-rehearsal.log`
- `/tmp/rhu-major-native-excluded-collection.log`
- `/tmp/rhu-major-integration-frontend.log`
- `/tmp/rhu-major-focused-automatic-codes.log`
- `/tmp/rhu-major-integration-build.log`
- `/tmp/rhu-major-integration-npm-audit.json`
- `/tmp/rhu-major-runtime-audit.json`

Two existing backend deprecation warnings remain: Starlette's httpx TestClient
integration and AnyIO's old BlockingPortal alias. They are maintenance items,
not failed authorization or transaction checks.

## 3. Integrated workflow and security review

| Area | Verified contract and evidence |
| --- | --- |
| Catalog → order | Import preview is read-only; authenticated staff import requires all management permissions and CSRF. New departments, specimen types, tests and panels are inactive. Sequence locks, stale-preview fingerprint checks, records, links and audits participate in one transaction. Existing mappings remain unchanged; replay is idempotent. Inactive clinical choices are rejected by order creation. `test_starter_catalog.py` covers these rules, collisions and rollback. |
| Patient/identifiers | CREATE/PATCH schemas forbid all seven client-supplied codes, including for administrators. Responses retain codes. Frontend forms submit configured editable fields and keep generated identifiers visible. Numeric IDs still define relationships. Phase 9 journal captures actual allocated Patient codes and preserves valid legacy references. |
| Allocation | MySQL row lock plus targeted sequence flush prevents stale repeated allocation under `autoflush=False`, without committing the caller or flushing unrelated pending records. Capacity checks occur before counter/timestamp changes. Record and audit rollback includes sequence allocation. Unique destination indexes remain the final collision guard. |
| Specimen → result → review | Existing specimen collection/receipt/rejection and item mappings remain. Draft results use authorized entry and separate review/verification transitions; reviewed/verified results remain protected. D reuses these APIs and displays actual counts and units. |
| Approval → release → PDF | Identity-bound signatory, sign/approve/release permissions and prerequisites remain. Release writes stored PDF, digest, audit and outbox through existing safeguards. Nullable presentation snapshots preserve legacy rendering; new reports freeze v2 presentation. Downloads validate and serve stored bytes rather than rerendering history. |
| PDF → blockchain verification | Existing immutable digest/outbox, retries, ownership, public verification redaction and gateway behavior remain; release/outbox/blockchain tests and native local Fabric checks pass. This does not certify live network reachability or a real production ledger submission. |
| Activation | Derived states are NOT_ACTIVATED, TOKEN_ACTIVE, TOKEN_EXPIRED, TOKEN_REVOKED, ACTIVATED and REVIEW_REQUIRED. Existing account links take precedence; consumed history without a link requires review. Reissue invalidates old invitations, expiry/replay fail safely, and account/link/audit creation is transactional. Staff actions are separated from patient access; MFA/account restrictions remain independent. Tokens are hashed at rest and shown only to authorized issuing staff once; no invented email/SMS service or URL token delivery. |
| Dashboard | Aggregates use existing read permissions; unauthorized sections are omitted, not fabricated as zero. Patient-associated accounts are excluded. No names or clinical values enter aggregate responses. Loading/empty/error states and cached network-observation labels remain distinct. |

The integrated catalog scenario in
`tests/test_starter_catalog.py::test_catalog_order_specimen_results_and_pdf_history`
rejects inactive ordering, explicitly activates synthetic configurations, creates
an order, collects/receives specimens, records numeric and qualitative results,
reviews/verifies, generates/signs/approves/releases a PDF, then retires a catalog
entry and verifies exact prior PDF bytes and clinical snapshots are unchanged.
`tests/test_phase_5b_release.py`, `tests/test_phase_8b_outbox.py` and blockchain
regressions cover the downstream security/atomicity contracts. No single test is
represented as a live production end-to-end deployment.

Identifier capacities, with the current three-letter prefixes and separator:

| Resource | Column length | Format | Maximum safe counter |
| --- | ---: | --- | ---: |
| Patient | 20 | PAT-000001 | 9,999,999,999,999,999 |
| Staff | 20 | STF-000001 | 9,999,999,999,999,999 |
| Department | 30 | DEP-001 | 9,223,372,036,854,775,807 |
| Test | 30 | TST-0001 | 9,223,372,036,854,775,807 |
| Panel | 30 | PNL-0001 | 9,223,372,036,854,775,807 |
| Rejection Reason | 30 | REJ-001 | 9,223,372,036,854,775,807 |
| Report Template | 30 | TMP-001 | 9,223,372,036,854,775,807 |

Padding is a minimum, not a maximum. The allocator checks actual rendered length
against model column capacity and signed BIGINT exhaustion. No column resize or
historical renumbering is needed. No Report Template creation UI was added.

## 4. Migration chain and remaining native verification

Validated offline:

```
20260914_01 → 20260914_02 → 20260914_03 → 20260914_04
→ 20260915_01 → 20260916_01 → 20260920_01 → 20260924_01
→ 20261005_01 → 20261015_01 → 20261018_01
```

| Revision | Change | Preservation / recovery policy |
| --- | --- | --- |
| `20261015_01` | InnoDB `code_sequence`, seven seeded rows, primary key and named nonnegative/padding CHECKs | All historical-code preflight completes before table DDL. Seed high-water marks use existing effective MySQL column collations. Existing codes and indexes are not rewritten. Downgrade refuses identifier reuse. |
| `20261018_01` | Nullable JSON `lab_report.presentation_snapshot` | No backfill, artifact regeneration, report digest rewrite or blockchain modification. Old rows remain NULL. Downgrade refuses loss of frozen presentation history. |

B, C and E add no migration. Confirm the **actual production** revision/schema
separately; Git branch state is not database revision evidence. This review did
not connect to production or development MySQL.

Automatic-code preflight requires native MySQL 8.0.16+ with enforced CHECKs,
InnoDB, supported effective utf8mb4 collations and sufficient table permissions.
It handles case, padding and MySQL-equivalent historical variants conservatively;
ambiguous generated-looking values, unsupported metadata and overflow fail before
DDL. Nonstandard legacy codes are preserved. Do not normalize, rename or delete
historical identifiers to force deployment. Rehearse the actual column collations
and relevant history distribution, not just database default collation. Rehearse
representative data volume, DDL lock duration and the approved migration
connection timeouts; the ordinary application engine uses five-second I/O timeouts.

`RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED=1` is only an operator acknowledgement.
It does not stop or lock out writers. MySQL DDL can implicitly commit: seed or
version-write failure can leave a created table/column with the previous Alembic
revision. Re-running successful Alembic upgrades is normally a no-op; bypassing
its version state with a direct upgrade call, stamp, dropped table or reset counter
is not a supported recovery procedure.

### Previous automatic-code rehearsal

The user-reported state reached `20261015_01`, with the seven sequence rows and
correct CHECK names. Expected synthetic counters were:

```
PATIENT=31, STAFF=23, DEPARTMENT=31, TEST=23, PANEL=31,
REJECTION_REASON=23, REPORT_TEMPLATE=31
```

These match the intended PAD SPACE / NO PAD fixture reservations. The subsequent
CHECK validation was most likely classified incorrectly: PyMySQL maps MySQL error
3819 to `OperationalError`, not `IntegrityError`. The current harness catches only
that structured native CHECK error through `DBAPIError`; other errors propagate.
Offline driver-packet and harness tests pass. The marker records scenario
initialization, **not successful completion**. Those counters also do not prove
the post-migration allocation and repeat-upgrade checks finished.

Preserve that populated isolated database. Do not rerun `--scenario success`,
reset it or infer completion from the marker. Use the separately authorized
read-only verifier in [MYSQL_MIGRATION_REHEARSAL.md](MYSQL_MIGRATION_REHEARSAL.md)
with its strict loopback/database/account identity and SELECT-only privilege
requirements. Do not grant it write privileges merely to pass verification.

The corrected historical harness is intentionally A-only. It cannot certify D.
A separate combined release rehearsal must be approved and recorded:

1. Preserve existing rehearsal evidence; provision a separately approved empty
   incarnation or an approved, protected isolated copy of the pre-release schema.
   A production-derived copy requires separate data-access/privacy authorization;
   synthetic fixtures are sufficient for initial failure-path development.
2. Establish isolated writer exclusion and verified native MySQL identity. Use
   the production-compatible version, collations, SQL modes and privileges.
3. Start at confirmed `20261005_01`. Record table/index/constraint inventories,
   historical code bytes, source high-water marks, report statuses/snapshots and
   SHA-256 of stored released PDFs. Include legacy draft and released reports.
4. Upgrade explicitly to `20261015_01`; verify seven seeds and real CHECK error
   3819 behavior, allocation/rollback/concurrency and unchanged history. Repeat
   the normal upgrade and prove counters are not reset.
5. Upgrade to `20261018_01`; verify nullable JSON and unchanged existing rows/PDFs,
   legacy draft rendering and newly generated v2 snapshots, signing, release,
   immutable stored bytes and outbox hashes using isolated synthetic records.
6. Repeat the final upgrade and verify no changes. In separately isolated failure
   scenarios, inject A seed/version-write failures and D failure after ALTER but
   before revision advancement. Preserve observations and prove the documented
   recovery against backups; never reset an unrelated or populated database.
7. Archive sanitized evidence, exact source hashes, version/collation inventory,
   restore timings and operator approval. Run the 74 omitted native regressions
   under separate migration authorization. Stop if any assertion or recovery
   assumption fails. No native procedure in this section was executed here.

## 5. Clinical approval and report controls

The starter catalog proposes five departments, 39 tests, five specimen types and
five panels. All newly imported entries remain inactive. The import approval is
an acknowledgement to **review inactive definitions**, not clinical validation
or automatic activation. Existing compatible records, including their active
state and clinical metadata, are preserved; that is not retrospective approval.

Before activating a test/panel, the facility's authorized laboratory leadership
must record approval under its existing quality process: service capability,
validated assay/method, specimen/container/handling requirements, units, reference
intervals and applicability, critical/qualitative interpretation rules, panel
composition, required reporting and staff competence. No imported reference range,
price or method is implied by a blank field. This application does not implement
a new regulatory approval system; ordinary authorized `is_active` changes must
follow the facility process and remain audited.

CBC/differential components share existing test IDs. Urinalysis/stool are summary
TEXT definitions with a 100-character result and separate remarks, not complete
structured microscopy panels. Approve sufficient reporting or configure component
tests before clinical activation. Microbiology is a category without seeded
assays; plasma is not assigned to starter tests without method-specific review.
Source citations are provenance, not proof of facility suitability.

Confirm actual signatories' identities, roles, licenses, authorization and private
signature/logo storage before release. Signing remains tied to the authenticated
signatory and separate approval/release controls. Public verification must expose
only the existing permitted metadata and integrity result; patient portal access
must remain owner-scoped. Do not rewrite already released PDFs or their hashes to
adopt the new layout, refresh a logo, or change a signatory description.

Clinical approval blocks clinical use of the affected inactive entries, **not**
installation of an otherwise approved release with the catalog still inactive.
Do not automatically call the import endpoint during deployment.

## 6. Dependency advisory

Installed frontend transitive `source-map-js` is **1.2.1**. The full read-only npm
audit reports one high-severity advisory,
[GHSA-68fv-2mgg-jv7q / CVE-2026-93749](https://github.com/advisories/GHSA-68fv-2mgg-jv7q):
malicious indexed source-map offsets can block the event loop. Versions before
1.2.2 in the affected range are vulnerable;
[upstream 1.2.2](https://github.com/7rulnik/source-map-js/releases/tag/v1.2.2)
is the published patch.

Local chains are `vite → postcss → source-map-js` and
`jsdom → css-tree → source-map-js`. Both parents permit `^1.2.1`, so 1.2.2 fits
the existing semver constraints without a top-level manifest change. The registry
returns the patched package and integrity metadata. This is a suitable **targeted
patch candidate**, not a claim of completed compatibility testing: the installed
package and lockfile were not changed in this review.

The affected paths are development/test/build tooling; `npm audit --omit=dev`
reports zero findings. No application endpoint was found that processes indexed
source maps. This narrows runtime exposure but does not remove risk from untrusted
build inputs or CI dependencies. Do not expose a Vite development server as the
production application. Serve the built static artifact.

Recommended separate remediation: update only the resolved transitive package to
1.2.2 in a reviewed lockfile change, inspect its integrity/diff, install through
`npm ci`, run affected frontend tests and the TypeScript/Vite build, and repeat
both audit scopes. Reject unrelated package upgrades; do not use blanket
`npm audit fix`. Before release, record either verified remediation or explicit,
time-bounded security-owner acceptance with build-input restrictions. No dependency
upgrade or risk acceptance is implied by this document.

## 7. Release gates and nonblocking findings

| Severity / scope | Finding | Required disposition |
| --- | --- | --- |
| High operational — blocker | Combined native migration and recovery evidence is incomplete; old rehearsal completion unproven | Read-only verification of preserved run, fresh authorized A+D success/failure/restore evidence; separately authorized native regression coverage |
| High operational — blocker | Production schema/collations, backups, restoration and complete writer inventory not inspected here | Authorized preflight; tested consistent recovery set, RPO/RTO, operational exclusion and named release/recovery owners |
| Release provenance — development correction finalized | Integration corrections included in the authorized local commit | Freeze final security-patched artifact/lock/source hashes before release |
| High advisory, build scope — release decision required | Installed source-map-js 1.2.1 | Targeted validated patch or documented security-owner acceptance |
| Clinical — use gate | Starter entries require local approval/configuration | Keep new entries inactive until qualified facility authorization; no deployment seed |
| Low maintenance — nonblocking | Two framework deprecation warnings | Track separately; no security protection was disabled |
| Test-only integration — resolved | Duplicate option selector; historical harness copied newer migration | Focused fixes pass; include corrections in the release artifact |

No new unresolved application defect was identified by the permitted run and
review. This statement does not certify unexecuted native tests or production
configuration. External/manual API consumers must also be assessed: valid CREATE
and PATCH requests can no longer send immutable generated codes, and generated
codes must be captured from successful responses.

## 8. Combined production release and recovery procedure — NOT EXECUTED

These are planned operator steps, not authorization to change production. Do not
run the development rehearsal/probe against production. Stop at any failed gate.
Actual paths, service inventory and credentials must be approved during preflight;
checked-in templates are not evidence of live service configuration.

### Ordered deployment sequence

1. **Approve and freeze.** Close section 7 gates, record the final integration
   commit, reviewed migrations and checksums, frontend build, Python/Node locks,
   security decision, maintenance window, release owner and recovery decision
   deadline. Preserve the previous application/frontend/dependency artifacts.
   Include all API consumers and operator CLIs in the immutable-code cutover.
2. **Read-only production preflight.** Under separate authorization verify actual
   Alembic revision, table/column/index/CHECK state, MySQL version, engines, SQL
   mode, effective collations, capacity/high-water marks, available space and DDL
   privileges. Expected baseline for this plan is `20261005_01`; a different or
   partial state requires a revised plan, not a blind `upgrade head`. Record
   report/private-asset storage locations without placing secrets in evidence.
3. **Prepare artifacts away from live paths.** Use the approved commit and locked
   dependencies; retain current production `.env`, permissions, private assets,
   keys and certificates. Do not copy development `.env`, synthetic data, test
   tools, identities, wallets, caches or source-map test fixtures into production.
   Verify static frontend artifact checksums and API compatibility together.
4. **Enter maintenance and fence every writer.** Block new mutating traffic and
   drain in-flight requests/transactions. Stop all API instances, delivery workers,
   scheduled jobs, importers and CLI/manual writers on every host sharing this
   database; prevent automatic restarts until the release owner clears the fence.
   Verify active transactions/connections with an authorized DBA account. The
   checked-in writer units are `rhu-labchain-node1.service` and
   `rhu-labchain-blockchain-worker.service`; enumerate other actual writers rather
   than assuming these are exhaustive. Preserve queued events and allow safe
   in-flight worker completion. Do not stop/reset Fabric peers or channels.
5. **Take the final consistent recovery set while fenced.** Use the approved
   private backup tool/account, never a password in command arguments or logs.
   Include all application tables (audit, accounts/token hashes, MFA state,
   report snapshots, verification/outbox/blockchain history and Alembic state),
   stored PDFs/attachments, private logos/signatures, configuration and encryption
   key references, previous binaries/static assets and dependency locks. Protect
   secret material separately with restrictive permissions and encryption. Record
   checksums, file ownership, schema inventory and binlog/GTID recovery position
   where configured. The database and report/files backup must represent the same
   fenced point. Do not use Git or public object storage as the backup destination.
6. **Prove restoration before schema changes.** Restore that recovery set to an
   approved isolated target, check integrity, historical PDF hashes/downloads,
   account/MFA key compatibility and report/outbox/ledger references. Confirm
   measured RPO/RTO and sufficient retention. Do not test restoration by
   overwriting production. Any failed restore check blocks migration.
7. **Migrate with writers still fenced.** Use the staged approved application and
   a reviewed, protected production migration environment. The normal Alembic
   env imports `app.database`; `DB_*` settings and the application settings must
   deliberately target the approved database. A `DATABASE_URL` or an alternate
   ini URL alone does not replace this application's engine configuration.
   Verify database identity in the authorized session before running either
   command. Never print settings or use the development probe's credentials.
   Planned commands, from the approved release directory only:

   ```bash
   RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED=1 .venv/bin/alembic upgrade 20261015_01
   # STOP and verify revision, seven seeds, constraints and unchanged history.
   .venv/bin/alembic upgrade 20261018_01
   # STOP and verify revision, nullable presentation_snapshot and unchanged history.
   ```

   The acknowledgement may be set only after the actual writer fence. Do not
   swallow a command failure, stamp a revision, manually reset counters or
   downgrade. Validate normal no-op repeat behavior in rehearsal; production
   inspection must not consume identifiers just to check counter behavior.
8. **Activate the coordinated application/frontend artifact.** Only after both
   revisions and preservation checks pass, switch the approved release while
   maintaining private storage/configuration and ownership. Install only built
   frontend content at the verified web root; the checked-in Nginx template uses
   `/var/www/rhu-labchain`, but live HTTPS configuration must be retained and
   verified separately. Avoid a mixed old frontend/new API interval. Do not
   publish source, `.env`, private report files or signatures under the web root.
9. **Controlled application verification, worker still paused.** Start approved
   application instances under maintenance access. Check readiness, session/MFA
   behavior, patient/staff permission separation, permission-aware dashboard,
   existing records, activation status without issuing real invitations, and
   authorized stored historical PDFs/hashes. Confirm signing/approval/verification
   configuration and no unintended catalog activation. Any mutating smoke test
   needs separately approved synthetic data and an audit-aware cleanup policy;
   this plan does not authorize creating test patients in production.
10. **Resume background work and traffic deliberately.** Reconcile pending/in-flight
    outbox state against existing Fabric transaction records before resuming the
    worker. Preserve idempotency and retries; never delete ledger data or replay
    events indiscriminately. Verify existing gateway/monitor configuration and
    cached-observation timestamps without modifying identities, channels or peers.
    Reopen traffic after owner sign-off; monitor API errors, auth failures, code
    collisions, release/PDF failures and outbox lag without logging secrets/PHI.
11. **Post-release acceptance.** Archive sanitized evidence, final revisions,
    artifact hashes, backup references, decisions and timings. Keep the recovery
    set for the approved retention period. Catalog preview/import and clinical
    activation remain a separate authorized facility process; deployment does
    not call import or automatically enable any starter entry.

### Failure and recovery decision table

| Observed state | Required response |
| --- | --- |
| Preflight refusal before A DDL | Keep writers fenced; preserve diagnostic category and metadata, investigate unsupported/ambiguous history. Do not alter historical identifiers to force success. |
| Parent revision plus existing `code_sequence` | Treat as partial A migration. MySQL DDL may have persisted even if seed/version DML rolled back. Preserve all rows and evidence; no normal retry, stamp, DROP, or zeroing. Choose reviewed forward repair or complete tested recovery. |
| A head plus existing PDF column but version not advanced | Treat as partial D migration. Inspect actual column definition and report rows read-only; do not blindly re-add it or stamp head. Obtain a specific reviewed repair/recovery plan. |
| Schema upgraded; no new application writes or blockchain submissions | A coordinated restore of the tested pre-release database, files and old artifact may be possible under approved recovery authority. Verify no post-backup writes first. Keep traffic/workers fenced throughout restore and validate before reopening. |
| Any new records, issued identifiers, released PDFs, audit events or ledger submissions | Prefer reviewed forward repair. Retain database, artifacts and audit evidence. Restoring an old database would lose writes and can reuse issued identifiers or diverge from the immutable ledger. A data-preserving incident/reconciliation plan is required; do not simply run the old application writable against the new schema. |

Both migration downgrades intentionally refuse. An application-only rollback is
not automatically safe: old manual-code creators do not maintain counters, and
old renderers do not understand frozen v2 presentation. Database/file/ledger state
must be evaluated together. Fabric history is not rolled back with MySQL; never
reset channels, peer volumes or certificates as an application recovery shortcut.

## 9. Final disposition

Workstream E is locally committed, the permitted integrated regression is complete,
and the two discovered integration failures are corrected with focused evidence.
The build and static migration-chain checks pass. **NOT YET READY FOR DEPLOYMENT**
until the explicit release gates above are closed and the final corrected artifact
is approved. The native execution and operator approval details are in
[NATIVE_RELEASE_REHEARSAL_PLAN.md](NATIVE_RELEASE_REHEARSAL_PLAN.md).

Production Git remains clean on `main` at `8622444`. No production file, database,
service, Fabric identity, certificate, channel or peer was modified. No MySQL
connection or migration was attempted in this task. There was no push, merge,
deployment, service restart or global dependency change. Workstream E and the separately authorized integration corrections are local
commits only. No production release is implied.
