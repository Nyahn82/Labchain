# Laboratory report PDF layout — 23 October 2026

The existing snapshot-based PDF renderer now follows the supplied blue-header preview: blue facility letterhead, compact patient/order metadata, upper-right verification QR, department/panel result sections, specimen details and recorded notes, and authorized signatories at the bottom of the final page.

## Scope and historical safety

- Only `app/services/report_pdf_v2.py` changes application behavior. No database migration, catalog update, frontend change, permission change, or workflow change.
- Facility identity, optional logo/contact information, patient data, result values/flags/units/ranges, actual department/panel labels, specimens, remarks and signatories continue to come from the existing report snapshots. The preview's example identities, illustrative logo and placeholder QR are not copied.
- Existing simulation and not-for-clinical-use text in report titles, remarks and template notes is retained. Missing clinical values remain absent; the layout does not infer reference ranges, diagnoses, clinical notes or signatures.
- Signatures remain the existing captured electronic signing attribution. No signature graphic is invented.
- The QR uses the existing generated verification URL. No release, approval, signing, hashing, blockchain submission or verification service changes.
- Final PDF bytes are still hashed by the release service after rendering. Downloads and prints still return the stored bytes; previously released PDFs are never rerendered. The legacy renderer remains unchanged.
- Continuation pages repeat report/version and patient identifiers, page numbering, and the current result group/table headings. Long notes and large signatory lists can continue across pages.

## Visual acceptance

All examples below contain isolated synthetic data; they are not clinical records. Their example-domain QR does not identify a report on the live website.

- [One-page short report](screenshots/pdf-layout-20261023/short.png) / [synthetic PDF](screenshots/pdf-layout-20261023/synthetic-short.pdf).
- [One-page ten-test panel](screenshots/pdf-layout-20261023/panel.png).
- [Continuation page from a 65-test, three-page report](screenshots/pdf-layout-20261023/continuation.png).

The examples were rasterized and visually inspected. QR decoding from the final PDF raster succeeded at two resolutions. An additional isolated API acceptance exercised actual report generation/signing/approval/release: the decoded QR matched the generated token URL, stored and downloaded bytes matched, SHA-256 matched the final file, public PDF comparison returned `MATCH`, and the release outbox contained that PDF hash.

## Regression and deployment evidence

- PDF layout, report lifecycle/release and patient portal: **257 passed**.
- Blockchain outbox, public authenticity and QR scanning: **120 passed**, one optional browser-fixture export skipped.
- Additional isolated release-to-raster-QR-to-public-comparison acceptance: **1 passed**.
- Layout checks cover short one-page reports, upper-right QR position, bottom signatories, unconfigured optional data, mixed specimens, captured logos, 100 long results/notes without clipping or overlap, 30 signatories, long footer continuation, and historical download/print byte preservation.
- Frontend production assets are unchanged; no frontend build or application dependency changes are required. Rasterization/QR tools used for inspection were installed only in `/tmp`.

Protected predeployment source and stored-PDF backups, file hashes, read-only database fingerprints, environment hash and service state are under `/var/backups/rhu-labchain/20261023-pdf-layout`. Deployment acceptance is recorded after the API restart and public checks.

## Deployment acceptance

- Deployed source commit: `a9d716faf82b7e88c3a9324b95a04f6e1ad40376`.
- Only `rhu-labchain-node1` was restarted. Worker, monitor and nginx process IDs remained unchanged; Fabric was not restarted.
- Public HTTPS `/`, `/api/v1/health` and `/api/v1/ready`: HTTP 200.
- Both previously stored PDF files remained byte-for-byte unchanged. All 53 non-operational database tables matched their predeployment fingerprints; only routine service observations changed. Frontend files and environment configuration were unchanged.
- Both existing live released reports: official PDF comparison `MATCH`, altered in-memory PDF comparison `MISMATCH`, stored artifact `MATCH`, live blockchain evidence `VERIFIED`, QR browser redirect 303, and unauthenticated private PDF access denied.
- All four Fabric peers and the orderer remained online at ledger height 8; all three existing outbox events were confirmed. No synthetic report was inserted into the active database for this layout deployment.
- Newly generated files were tested through the isolated release endpoint and inspected visually. Production acceptance checked the deployed source/API restart and existing official reports without modifying their clinical records or artifacts.

Detailed checks are retained in the protected backup directory as `release.json`, `final-integrity.json` and `verification-evidence.tar.gz`; the deployment manifest is `/var/log/rhu-labchain-deployments/20261023-pdf-layout.json`.
