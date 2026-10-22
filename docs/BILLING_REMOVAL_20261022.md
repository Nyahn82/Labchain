# Billing retirement — 22 October 2026

RHU LabChain now exposes only laboratory management and report verification workflows. The starting commit was `30e87aa` on `main`. No application redesign, schema migration or clinical rule change is part of this release.

## Removed active functionality

- Order payment-history card, record-payment dialog/actions, financial status styling and frontend payment fields.
- Financial wording in operational analytics, payment distributions and recorded-amount metrics.
- GET and POST `/api/v1/lab-orders/{order_id}/payments`, their request/response schemas and the payment-recording service.
- Embedded `payments` from laboratory order responses and all workflow/analytics reads of the financial table.
- Payment permission bootstrapping and grants from the declared laboratory-role policy. Policy version is now 1.1.0: 16 laboratory-staff permissions, 31 supervisor permissions, and the unchanged single signer permission.
- Obsolete payment stages in the operator end-to-end validation script.

No standalone billing/cashier/invoice routes existed. The existing laboratory sequence already had no payment prerequisite; no replacement stage or bypass was introduced. Orders, specimen compatibility/quality processing, result review/verification and report signing/release retain their existing rules.

## Historical data and authorization

`lab_payment` remains an archived table, with its model and original migration retained so schema metadata does not suggest dropping historical records. No API, schema, runtime workflow or analytics service accesses it. Old `PAYMENT_READ` and `PAYMENT_RECORD` permission/grant rows are also retained. They are excluded from effective permissions, authority calculations and permission discovery; new bootstrap operations do not recreate or grant them. The role-policy reconciliation tool tolerates these known retired rows while continuing to reject unknown active grants. All other permission metadata and authorization rules are unchanged.

Blockchain transactions/commit receipts and specimen receipt events are unrelated to finance and remain intact. Historical documentation describes earlier releases; this document records the current active contract.

## Verification

- Frontend: 376 tests passed; TypeScript validation and Vite production build passed. The existing main-bundle size warning remains (approximately 519 kB minified / 152 kB gzip); no dependency or styling framework was added.
- Focused backend: **725 cases passed after targeted reruns; 3 optional export tests skipped**. Coverage includes order/specimen processing, results, report generation/signing/release, analytics, administration/RBAC, catalog availability, QR and blockchain outbox behavior. New checks verify former financial routes return 404, archived rows are preserved, processing never queries `lab_payment`, and retired grants are neither effective nor re-created.
- **10 native MySQL cases and 78 operator end-to-end validation tests passed**. Native MySQL tests run on a disposable Unix socket, covering concurrency, snapshot integrity, code collisions and rollback. No test uses the active MySQL database.
- Real Chromium with the full isolated API completed order creation, compatible specimen registration/collection/receipt, barcode download, result entry/edit/review/verification, report generation/signing/approval/release and official PDF preview. The server rejected **any SQL access to `lab_payment`** throughout this journey.
- QR browser regression passed controlled camera-video and image decoding, cleanup/fallbacks, public privacy, staff PDF access and authenticity evidence. Physical-device testing was not performed.
- Eighteen desktop/mobile browser views showed no billing controls, financial requests or page overflow. Authenticated order, permissions and analytics responses contain no financial fields.
- OpenAPI comparison with the live starting deployment: only the payment path (GET/POST) is removed. Every other path/method contract is unchanged. Only financial schemas and the financial members of `OrderDetail`/`Metric` changed.

The wider regressions exposed older assertions about duplicated panel components, live edits rewriting captured examination definitions, authentication presence updates and an outdated migration count. Reporting, release, analytics and migration-count failures reproduced in an isolated archive of the unchanged starting commit. Their test fixtures/assertions were aligned with the existing deduplicated, immutable-definition behavior, session heartbeat and 13-revision migration chain. No corresponding clinical, reporting or authentication behavior was changed.

## Deployment and recovery

Protected backup location: `/var/backups/rhu-labchain/20261022-no-billing`. It contains a consistent MySQL dump, original source archive, previous frontend, and database/report/environment hash manifests. Deployment installs hashed frontend assets before atomically replacing the entry point, preserving previous asset files for existing tabs and rollback. Only `rhu-labchain-node1` needs restarting to load the removed API routes. No migration, permission-table mutation, Fabric restart or worker restart is required.

Live acceptance uses the existing synthetic laboratory identity for read-only views and unsaved examination selection, then restores its original disabled state/credential and revokes its sessions. Financial GET/POST requests are tested only against the removed route and must return 404. No live clinical record is created or modified. Final verification compares historical financial/clinical tables, permission grants, automatic codes, PDF files and environment bytes, checks served asset hashes and health/readiness, and validates the existing released report against actual Fabric evidence.

Local evidence is under `/tmp/rhu-scan-no-billing`, `/tmp/rhu-no-billing-deploy`, and `/tmp/rhu-no-billing-*.log`; durable copies are preserved in the protected deployment backup. Deployment metadata is recorded in `/var/log/rhu-labchain-deployments/20261022-no-billing.json`.
