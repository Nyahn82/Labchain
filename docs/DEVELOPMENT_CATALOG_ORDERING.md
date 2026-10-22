# Development catalog ordering

The existing availability predicate permits active `UNREVIEWED` tests and panels only when both `ENVIRONMENT=development` and `DEVELOPMENT_CATALOG_ORDERING_ENABLED=true`. The flag defaults to false and has no effect in production, staging or test environments. Facility status, approval notes and definitions remain unchanged; availability for simulations is not clinical approval.

The existing catalog API and order endpoint share this predicate. Active departments, compatible active specimens, panel membership, permissions and dedicated-workflow restrictions still apply. Restricted HIV screening remains unavailable even if accidentally activated. Master-data clinical approval rules, result/report workflows, frontend source and built assets are unchanged.

## Focused verification

`tests/test_clinical_catalog.py` covers opt-in/environment rejection, unchanged review state, inactive dependencies, restricted HIV, individual ordering and the four requested panels. CBC with Differential (19 components), Urinalysis (19), Fecalysis (6) and Lipid Profile (4) are saved and associated with compatible specimens using isolated synthetic data. Existing catalog/report/QR tests in the same file retain their prior behavior with the flag disabled.

`tests/browser/development-catalog.mjs` uses the existing deployed frontend against an isolated HTTPS SQLite backend. It selects and saves all four panels and Hemoglobin through the real order screen, reloads orders, and selects/registers EDTA whole blood, urine, stool and serum specimens. No clinical approvals or live test orders are created by this automation. Public browser acceptance was subsequently completed against `https://labchain.online` using a dedicated synthetic account and patient, as recorded below.

## Controlled activation and recovery

The owner explicitly authorized activation on the development website. Before activation: verify main/remote, actual MySQL identity/revision, current inactive import state, service inventory, HTTPS and secure cookies. Fence API/worker and other database writers, preserve restart/account/scheduler state, and capture a protected consistent database/private-file/configuration/application/frontend backup. Verify restoration into a separate socket-only MySQL server and verify encrypted recovery checksums.

Select existing imported rows by the `STARTER_CATALOG_CREATE` audit entries for `ph-clinical-2026.10.21-v1`, cross-check test/panel metadata, and update only `is_active` in one transaction. Expected activation: eight departments, 165 tests, 27 panels and 20 specimens. The one restricted HIV test remains inactive. Keep all 166 imported tests and 27 panels `UNREVIEWED`; append explicit `DEVELOPMENT_CATALOG_ACTIVATE` audit entries with no impersonated staff actor. Do not reimport or allocate codes. Compare all other table hashes, audit history, imported columns and private PDF files before commit.

Set the two development switches in the protected host configuration, preserving all other values, permissions, HTTPS and secure cookies. Restart the actual API/worker units with their previous policies, check readiness, availability, historical PDF/Fabric evidence and heartbeat, then reopen traffic. No migration or frontend rebuild is required; revision stays `20261021_01`.

To disable simulation ordering, set `DEVELOPMENT_CATALOG_ORDERING_ENABLED=false` and restart the API through the normal coordinated procedure. Production rejects these unreviewed entries regardless of the flag. Do not relabel them APPROVED to restore availability. Preserve any orders created after activation and their frozen definitions; never restore an older database over new clinical/audit/ledger activity. A catalog deactivation should be a separately audited transaction restricted to the recorded activation IDs.

Deployment evidence and backup references are retained outside Git under `/var/backups/rhu-labchain/20261022-development-catalog` and `/var/log/rhu-labchain-deployments`. Live acceptance status is recorded there after execution.

## Verified deployment — 22 October 2026

The pre-activation backup was restored into a separate socket-only MySQL instance: all 54 table hashes, the stored PDF, frontend files and protected configuration matched. Its encrypted recovery bundle and decryption checksum were verified before the controlled activation transaction. The transaction activated exactly eight departments, 165 unrestricted tests, 27 panels and 20 specimens, appended 220 activation audit entries, and left the restricted HIV test inactive. All imported examinations remain `UNREVIEWED`.

Public HTTPS browser automation used the unchanged deployed order interface and a dedicated synthetic patient to select, save and reload CBC with Differential (19 components), Urinalysis (19), Fecalysis (6), Lipid Profile (4), and individual Hemoglobin. The same interface registered EDTA whole blood, urine, stool and serum specimens for the four panels. All save/register requests returned HTTP 201; restricted HIV ordering returned HTTP 409. There were no browser JavaScript errors. The five synthetic orders were cancelled through the existing endpoint afterward, and the synthetic account was disabled with all sessions revoked. Their records and audit history remain; no synthetic results or reports were created.

Focused catalog and workflow regression tests: **194 passed, 2 skipped** (optional fixture exports). Development opt-in, production/staging/test rejection, active dependencies and restricted workflows are covered. Public health/readiness, historical PDF byte comparison, QR verification routes and live Fabric verification passed. Frontend files, Nginx configuration and historical PDF files match their pre-activation hashes. Original service restart policies and database account/scheduler state were restored; the worker heartbeat is healthy.

Detailed evidence: `/var/log/rhu-labchain-deployments/20261022-development-catalog.md`. Recovery bundle: `/var/backups/rhu-labchain/20261022-development-catalog/recovery.tar.enc`; its key remains separately protected. This records automated public-browser acceptance, not a physical-device or staff walkthrough.
