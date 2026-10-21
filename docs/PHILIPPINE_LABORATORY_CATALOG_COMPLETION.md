# Philippine clinical laboratory catalog and workflow integration

## Release status

Deployment SUCCESS; acceptance PARTIAL pending the owner’s authenticated live catalog/order walkthrough and physical built-in scanner/staff acceptance. Implementation, controlled import, automated acceptance and operational verification are complete as recorded below. Do not infer that proposed services are clinically approved. No new live patient, result, signature, report release or Fabric submission is part of this update.

Baseline: `main` and `origin/main` at `549207111c854985ed598825de759a767c55712c`; clean before implementation. Last running application artifact: `1a493ec055da8e728e5857f703ea2f0421ebc510` (subsequent baseline commits documented acceptance). Active MySQL: `rhu_labchain`, revision `20261019_01`, server UUID verified before maintenance. API, delivery worker and read-only monitor were active; inactive legacy API unit was also identified. Nginx serves `/var/www/rhu-labchain`, while proxied assets also require the matching `frontend/dist` artifact.

## Gap inventory and coverage

| Database entity | Original | Actual after controlled import | New definitions |
|---|---:|---:|---:|
| Departments | 1 | 9 | 8 |
| Tests / analytes | 1 | 167 | 166 |
| Examination panels | 0 | 27 | 27 |
| Specimen types | 1 | 21 | 20 |

The original database contained one test/specimen relationship, no panel membership or reference intervals, and one existing order, result and report. Its existing codes and records are retained. The older file-only starter catalog contained 39 tests, five panels, five departments and five specimens; it remains unchanged for compatibility. The expanded version is `ph-clinical-2026.10.21-v1`, in `app/data/philippine_clinical_catalog.json`.

Existing order, collection/rejection, review/verification, approval/signature/release, immutable PDF, QR and Fabric paths were reused. Gaps addressed: substantial database catalog population; facility review state; searchable integrated ordering; overlapping panel deduplication; order-time definition snapshots; examination-specific structured findings; specimen collection metadata and protected barcode labels; read-only structured result review; frozen PDF presentation of findings.

The 166 entries are distinct examinations **and individually reportable analytes**, including CBC differential and urinalysis components. This is not a claim of 166 independent diagnostic services. There are 94 numeric, 70 text and two positive/negative entries. Thirty-six entries carry structured configuration, comprising 25 distinct schema definitions and 79 fields; scalar CBC/chemistry analytes retain the established numeric result path. Culture configuration supports bounded organism/antimicrobial observations with method and interpretation-standard provenance, without inferred susceptibility or treatment advice.

Proposed tiers: 46 routine, 57 general, 47 referral-only and 16 specialized entries. These are scope labels, not facility availability. All 166 new tests and 27 panels import as `UNREVIEWED` and inactive; new departments/specimens also begin inactive. Existing active services are preserved. HIV screening entries remain blocked from approval/ordering pending a dedicated authorized confidentiality/consent workflow. Blood-bank entries describe laboratory investigations; this update does not implement transfusion administration, blood-product inventory or compatibility authorization.

The 27 panels include CBC, CBC with differential, differential count, hemoglobin/hematocrit, urinalysis, urine microscopy/dipstick, fecalysis/stool microscopy, lipid/liver/renal/electrolyte/basic/comprehensive chemistry, bilirubin/protein/iron, urine albumin/creatinine, CSF, coagulation, thyroid, hepatitis B/acute hepatitis, dengue, ABO/Rh and glycemic assessment. Panel memberships are explicit; urine/fecal sections retain physical, chemical and microscopic grouping. Mixed-specimen panels retain each component's specimen requirements.

## Sources and clinical limits

Source identifiers, titles and URLs accompany the manifest and imported test metadata. Administration exposes the provenance and review note. General source review dated 2026-10-21 is **not** a clinical sign-off.

- [DOH CFERMTC laboratory menu](https://cfermtc.doh.gov.ph/laboratory-services/), [DOH Bataan pathology/laboratory](https://bataanghmc.doh.gov.ph/pathology-and-laboratory/), [DOH Bicol serology](https://www.bmc.doh.gov.ph/rates-and-fees/laboratory/serology), [DOH Bicol chemistry](https://bmc.doh.gov.ph/rates-and-fees/laboratory/clinical-chemistry), [DOH Zamboanga laboratory](https://zcmc.doh.gov.ph/laboratory-fees/), and [DOH SPMC pathology](https://spmc.doh.gov.ph/pathology/) support Philippine service-name coverage. Some DOH sites returned HTTP 403 on full-page retrieval; their indexed service information supports names only, not validated assay specifications.
- [Mayo CBC/differential](https://www.mayocliniclabs.com/test-catalog/overview/9109) supports component and EDTA whole-blood distinctions; [Mayo comprehensive metabolic panel](https://www.mayocliniclabs.com/test-catalog/overview/113631) supports general serum chemistry composition.
- [Cleveland Clinic urinalysis with microscopy](https://clevelandcliniclabs.com/test/urinalysis-with-microscopic/), [Mayo collection guidance](https://www.mayocliniclabs.com/specimen/collection-and-preparation), [Mayo urine culture](https://www.mayocliniclabs.com/test-catalog/overview/60515), and [Mayo semen analysis](https://www.mayocliniclabs.com/test-catalog/Overview/81641) inform specimen/result categories. Additional source links for HbA1c, ABO/Rh, bilirubin, urate, hepatitis and dengue are retained in the manifest.

No universal reference ranges, critical cutoffs, instrument-specific containers, stability periods, clinical interpretation or reference population were fabricated. Unknown collection instructions remain explicitly facility-SOP-required. Proposed units, test format/options, specimen mapping, panel composition and referral arrangements require qualified local review against the actual method/manufacturer instructions. General numeric dimensionless measurements still need an explicit locally approved unit convention. No license, capability or accreditation is implied by catalog inclusion.

## Implementation and administration

Migration `20261021_01` follows `20261019_01`. It adds nullable catalog/approval/specimen metadata, order/panel definition snapshots and structured result values, plus specimen-code uniqueness and a facility-status index. Existing rows are not backfilled. Downgrade refuses destructive removal of snapshots/results.

The existing importer now accepts the expanded version. It validates relationships/schema, detects ambiguous/name/code/history collisions, uses existing transactional automatic-code allocation, preserves matched/manual configuration, audits inserted definitions, and commits atomically. A fingerprint binds the preview to the applied plan. `scripts/import_clinical_catalog.py` previews by default and accepts `--apply-fingerprint` for the controlled import. Reruns preserve configuration and consume no new identifiers. Conflicts require reconciliation; they are not silently overwritten. Seven automatic-code generators remain in place; only new department/test/panel allocations advance their respective counters.

Permissions are reused: `LAB_MASTER_READ`, `TEST_CATALOG_MANAGE`, `TEST_PANEL_MANAGE`, `SAMPLE_TYPE_MANAGE`, existing department/range permissions, `LAB_ORDER_CREATE`, `SPECIMEN_READ`/registration/status permissions, and existing result/report permissions. Import requires the established combined management permissions and staff boundary. Public catalog import, private PDF and barcode access are denied without appropriate authorization. Barcode downloads produce Code128 accession labels, omit patient identifiers and audit `SPECIMEN_LABEL_VIEW`.

Enhanced screens/routes:

- `/laboratory`: database-backed catalog, name/code/alias search, department/specimen/availability filters and component details; controlled expanded import.
- `/laboratory/tests/:id`, `/laboratory/panels/:id`: facility status/approval note, method/unit/reference configuration, structured field editor, provenance, panel membership and specimen mapping/collection guidance.
- `/orders/new`: existing patient/physician/priority form now selects individual examinations and panels from the catalog, displays unique components and mixed specimen requirements, and posts to the existing order API.
- `/orders/:id` and specimen/result/report tabs: preserved order definitions and memberships, compatible registration, collection/receipt/rejection, barcode labels, configured result fields and draft resumption; structured observations are visible before review.
- Existing report detail/PDF preview and `/reports/scan` retain permission-protected original PDF viewing beside blockchain evidence. Public `/#/verify` remains privacy-safe.

One order item is created per unique test, even across overlapping panels. Every panel membership remains in the immutable order definition; shared results complete all relevant panels. New orders freeze test names/types/units/schema, department, specimens and panel membership/sort/section. Structural changes to already referenced tests and semantic changes to referenced reference intervals are rejected. Changes to approved test structure, specimen mapping or panel composition return affected availability to review. New manually created tests/panels also start unapproved. Historical rows with null snapshots retain their established compatibility path.

New report presentation snapshots retain structured observations and frozen grouping. Existing PDF files and verification hashes are never regenerated. No new migration alters Fabric data or infrastructure.

## Acceptance evidence and scope

Isolated SQLite integration scenarios cover CBC with differential, routine urinalysis, comprehensive chemistry and a combined CBC/differential/glycemic/urine order: deduplication, mixed specimen rejection/acceptance, draft resumption, review/verification, signature/approval/release, actual PDF content, exact-byte QR comparison and permission-protected staff resolution. Fabric is an explicit test double in these synthetic scenarios. Culture tests cover required fields, bounded susceptibility, forbidden fields, reviewed-result immutability and structured PDF findings.

Native MySQL uses a new socket-only disposable server, never the active database. It tests the additive migration, old-row preservation, import, no-op rerun, code/configuration preservation and catalog projection.

Real Chromium automation against an isolated HTTPS backend passed actual login, alias search, panel plus individual ordering, reopen persistence, separate EDTA/serum specimens, collection/receipt, barcode downloads, draft edits, review/verification, report assignment/signing/approval/release and PDF preview. A 390px viewport had no horizontal overflow. QR regression used the real ZXing decoder with controlled camera video and image input; staff scanning fetched the exact stored PDF, displayed a blob-backed viewer/full PDF link and independent witness evidence, and supported another scan. Camera denial and unrelated QR fallbacks also passed. These are browser tests, not physical-phone acceptance.

The owner's earlier phone report established Android native scanner → Chrome → website only. It did not establish a signed-in staff scanner walkthrough. No live staff session has been invented for acceptance; authenticated live catalog/order acceptance remains a qualified operator walkthrough after deployment. New services must first receive legitimate local approval; synthetic approvals stay isolated.

Final test totals and operational evidence follow.

## Coordinated recovery procedure

Use the existing runbooks (`deploy/README.md` and section 8 of `docs/MAJOR_UPDATE_RELEASE_READINESS.md`). Fence Nginx traffic and all discovered writers, suppress unit restarts, lock application and OS-maintenance database accounts, disable the event scheduler, drain connections/transactions and take a fresh consistent dump. Include private reports, previous frontend/application/dependencies, protected configuration and references. Restore into a separate socket-only MySQL instance and compare every table and private artifact before schema changes; encrypt the recovery archive with a separately protected key.

Run the migration once with the verified application database target and a bounded host-DBA connection while application accounts remain locked. Any partial MySQL DDL failure stops the update under maintenance; do not stamp, blindly retry or downgrade. Apply the reviewed catalog fingerprint and compare all historical-column projections, original PDF/file hashes, generated-code deltas, audit prefixes and outbox records. Activate matching assets in both existing frontend locations only after verification, preserve Nginx/HTTPS and permissions, restore prior unit restart policies, and require health/readiness/Fabric checks plus advancing worker heartbeat before traffic resumes.

Recovery is a coordinated decision using the tested encrypted pre-update set. Retain the original schema/data/files/artifacts and reconcile all post-backup activity before any restore. A compatible application rollback or forward repair is preferable once new writes exist. Never overwrite newer clinical/audit/ledger history, reset MySQL, reset Fabric or delete/replay outbox entries automatically.

## Final implementation checks (before deployment)

| Check set | Result |
|---|---|
| Laboratory master, migration, order/result workflow, native MySQL regression (429 cases) | 424 initially passed; five stale expectations corrected and all affected cases passed in the 11-case correction run |
| Catalog/starter/PDF/public authenticity/staff QR integration (101 cases) | 98 passed, two explicit optional exports/rehearsals skipped; barcode authorization test fixture corrected and passed |
| Expanded catalog/native MySQL/latest migration chain (14 cases) | 11 passed, one optional export skipped; two anonymous-request fixture errors corrected and passed |
| Final correction run | 11 passed, zero failed |
| Entire frontend suite (372 cases across 21 files) | 371 initially passed; one stale navigation expectation corrected; its complete 11-case file passed |
| TypeScript and Vite build, dependencies installed with `npm ci` | Passed; staged outside both active web roots |
| Chromium clinical workflow and public/staff QR regression | Passed with synthetic data and explicit Fabric double |

These sets overlap; counts must not be summed as distinct tests. No known unresolved failure remains in the listed scopes. Framework deprecation warnings and the Vite large-chunk advisory are nonblocking. Broader testing was performed at the integration milestone, followed by targeted corrections rather than repeated full regression cycles. Native MySQL verified import idempotency and preservation; no live database has been used for synthetic tests.


## Operational deployment — 21 October 2026

Deployed application commit: `8204a5486602b5000f707b1e96f1ab9d6b4e0a3c`.
Database: `rhu_labchain`, verified revision `20261021_01`.
Normal traffic resumed at **22:58:06 Asia/Singapore** (14:58:06 UTC).
Final operational verification: **23:03:36 Asia/Singapore**.

The database now contains **9 departments, 167 tests/analytes, 27 panels and 21 specimen types**. Import inserted 221 master records, updated zero and rejected zero; it also created 160 panel memberships, five sections and 173 test/specimen mappings. Repeat preview proposes zero creations. Every new test/panel is inactive and `UNREVIEWED`; the one previously available legacy test remains orderable. No live clinical approval, patient, order, result, signature, report or ledger event was fabricated.

Writer exclusion covered the actual API and blockchain-delivery units, the inactive legacy API unit, application database accounts and the discovered `debian-sys-maint` database account. No application cron writer or MySQL event was found. Accounts were locked and the scheduler disabled while migration/import ran through a bounded host-DBA socket connection targeting the application-configured database. The read-only monitor and Fabric infrastructure stayed running. Previous account locks, event scheduler state and unit restart policies were restored.

Recovery set:

- Encrypted archive: `/var/backups/rhu-labchain/20261021-clinical-catalog/recovery.tar.enc`.
- SHA-256: `7f11a6878076bd3e587edec1ab840308ce4126343853d60cf0b2d68902a92114`.
- Separate root-only key reference: `/var/backups/rhu-labchain-keys/20261021-clinical-catalog.key`.
- Before migration, all 54 tables restored with exact hashes into a fresh socket-only MySQL server; database restore took 2.64 seconds. The historical PDF, frontend and protected configuration matched, and encrypted decryption/checksum verification passed.
- Sanitized durable deployment report: `/var/log/rhu-labchain-deployments/20261021-clinical-catalog.md`. Protected manifests, stage scripts, import summary, tests and browser evidence are retained with the backup.

Historical-column projections matched after migration/import and before traffic resumed. Existing account, patient, clinical/report, original audit and blockchain/outbox data remained intact. Only new catalog allocations advanced DEPARTMENT by 8, TEST by 166 and PANEL by 27; the other four code counters stayed unchanged. Original generated identifiers and private report files were unchanged.

After traffic resumed, an ordinary login added a session/login record and changed an account’s `last_login_at`. A separate comparison against the encrypted pre-update backup, restored to another isolated MySQL instance, confirmed that **all other account fields remained identical**. Final integrity checks permit these observed post-resume authentication additions and the advancing worker heartbeat; they do not describe the live database as byte-for-byte unchanged.

Frontend activation preserved existing Nginx configuration, HTTPS and directory permissions. The same staged files were installed in `/var/www/rhu-labchain` and `frontend/dist`; public HTTPS responses matched all staged SHA-256 hashes:

| Asset | SHA-256 |
|---|---|
| `index.html` | `d56dd97206c4d2c06cffe6536eb487afe6e84fa11067d6a164727e36b519637f` |
| `assets/index-japnnnYz.js` | `2ad5bdbb7c6296648ed9cb8b73874de4f546910b572aad7b6b7b33ce12eca9ec` |
| `assets/index-0O6uKZgj.css` | `3481335bac0c51e483fc0277a41f154728ff92b9f7deb6b036c637b7867d2555` |
| `assets/esm-CuJYLdlD.js` | `02759e6503485affa4dd1ba65a61d96c737e69f2aaf871a1eda12588e04ce78d` |

HTTPS, API health and MySQL readiness returned 200. API, delivery worker and monitor are active with zero restart failures; API retains on-failure/5 seconds, worker and monitor on-failure/10 seconds. The worker’s healthy heartbeat advanced. Catalog and specimen-label endpoints returned 401 to anonymous clients. The catalog service/API projection against active MySQL returned the exact counts above; the full authenticated browser workflow was tested against the isolated backend, not by manufacturing a live session.

The historical released PDF remains an exact stored-byte match. Public comparison accepted the official bytes and rejected an altered in-memory copy. Real Fabric queries independently verified the historical anchors; four peers and the orderer remain ONLINE at height 7, and the same two outbox entries remain CONFIRMED. No Fabric infrastructure or cryptographic material was changed. The historical report still correctly reports `LEGACY_UNAVAILABLE` issuer context; no historical issuer was invented.

Real Chromium against **the running HTTPS website** passed ZXing camera-video decoding, QR extraction from the historical full PDF rendered at 150 DPI, independent Fabric evidence, absence of a public private-PDF viewer, repeated image scanning, unrelated-QR rejection, manual fallback, camera-denial handling and desktop/mobile overflow checks. Camera input was controlled video, not a physical phone. Temporary historical PDF derivatives were removed after verification.

Remaining acceptance: the owner has offered to perform the live staff catalog/order walkthrough; results have not yet been reported. Physical built-in camera scanning and the live signed-in staff original-PDF/evidence workflow remain unverified. The previous Android native-camera-to-Chrome observation is preserved without expanding its meaning. Clinical activation remains a separate qualified facility decision, as required; unsupported services and unknown reference intervals remain disabled/unset.
