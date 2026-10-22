# Frontend usability refinement — 22 October 2026

The existing React application retains its soft, raised surfaces while making daily laboratory work easier to navigate. This release changes frontend presentation and interaction only. The starting source and deployed frontend were inspected at `4177ebd`; no routes or API contracts were removed.

## Changes and route inventory

| Existing areas (before and after) | Refined behavior |
| --- | --- |
| `/dashboard`, `/administration/analytics` | Compact heading and quick actions; operational counts, pending work and recent orders precede secondary statistics; real service errors remain visible. |
| `/patients`, `/patients/:id`, `/physicians`, `/facilities`, `/staff`, `/staff/:id` | Consistent searchable directories, readable codes, optional activation filters, grouped registration fields and shared detail/form styling. |
| `/laboratory`, `/laboratory/{departments,samples,tests,panels,reasons}`, test/panel details | Catalog immediately accessible; setup links remain visible; import tools use progressive disclosure. Compact examination rows show availability, review status, specimens and expandable composition. |
| `/orders`, `/orders/new`, `/orders/:id`, `/orders/:id/{specimens,results,reports}`, `/specimens`, `/specimens/:id`, `/results` | Patient/request first, examination search next, unique selection and specimen summary last. Create action stays visible. Workspaces prioritize active tasks and retain optional workflow/reference details. Wider result forms and readable status badges. |
| `/reports`, `/reports/:id` | Shared table/filter/action improvements and a wider stored-PDF preview with a full-document link. Historical PDF content is untouched. |
| `/verify`, `/verify/:token`, `/reports/scan`, `/reports/scan/:token` | Shared responsive controls, scanner/preview surfaces, and readable evidence. The staff scanner navigation uses existing role, staff-link and report permissions. |
| `/administration`, `/administration/:id`, `/administration/{report-setup,activity,blockchain}` | Consistent tables, settings, audit/monitor cards and optional detail sections; existing authorization and error indicators retained. |
| `/login`, `/patient/login`, `/patient/mfa`, `/patient/activate`, `/patient/setup-mfa` | Shared spacing, boundaries, typography, visible focus and accessible forms. |
| `/patient`, `/patient/{reports,profile,security,access-history}`, `/patient/reports/:reportId` | Same restrained visual system, simpler mobile surfaces and wider official PDF dialog. Ownership and MFA rules unchanged. |

Navigation groups existing destinations into Overview, Patients, Laboratory, Reports, Configuration and Administration. Groups collapse; the desktop sidebar can become an icon rail. Mobile navigation traps keyboard focus, closes with Escape, restores focus to the opener and prevents background interaction. Existing deep links and permission gates remain intact.

Shared CSS tokens standardize spacing, colors, contrast, radii and subtle shadows. Important surfaces remain raised; controls have visible borders and inset treatment. Dense tables scroll inside their own regions. Forms associate help text with controls and focus validation summaries. Status text, rather than color alone, conveys state. Reduced motion remains supported. No UI framework or runtime dependency was added.

Available UNREVIEWED examinations explicitly say **Simulation only · not clinically approved**. Availability continues to come from the API. No catalog records, activation rules, backend code, payment functionality or result/report rules changed.

## Verification

- Baseline frontend: 372 tests passed. Final frontend: 376 tests passed across 21 files; TypeScript and production build passed. One existing loading-state test had a race between authentication loading and the deferred activity request; it now waits for that request before resolving it.
- Focused clinical-catalog and QR API regressions: 32 passed, 3 skipped (optional exports).
- Real Chromium against the isolated full FastAPI/SQLite application: select individual tests plus panels, save/reopen an order, register compatible EDTA/serum specimens, collect/receive, download barcode PDFs, enter/edit results, review/verify, generate/sign/approve/release a report, and preview its PDF.
- Separate development fixture: CBC with Differential, Urinalysis, Fecalysis, Lipid Profile and Hemoglobin selected and saved; compatible specimen registration succeeds; UNREVIEWED status and restricted-workflow protection remain intact.
- Patient journey through real isolated endpoints: registration/search, invitation, activation, actual TOTP enrollment, recovery-code acknowledgment, returning MFA login, owned reports/PDF preview, and denial of staff administration.
- Existing QR browser suite: local image decoding, controlled camera-video decoding and cleanup, unrelated-image rejection, camera denial, staff PDF/evidence, scan-again, public privacy and verification states. No physical-phone camera claim.
- Before/after matrix: eight representative routes at 360, 390, 768, 1280 and 1440 pixels (40 cases each). Patient portal: five routes at the same five widths. No page-level overflow or JavaScript errors.
- Expanded route audit: 34 staff/public routes at 390 and 1280 pixels (68 cases), no page overflow, no JavaScript errors, and no axe WCAG 2 A/AA or 2.1 AA violations detected. Keyboard drawer trapping/Escape/focus restoration and desktop collapse passed. Automated audits are not a formal accessibility certification.
- Screenshot inspection covered dashboard, ordering, result workspace, patient portal, public verification and staff PDF preview. Narrow dashboard overflow and split status words found during review were corrected.

The repeatable route/keyboard/axe harness is [tests/browser/ui-refinement.mjs](../tests/browser/ui-refinement.mjs). It accepts external Playwright/axe paths and only targets the isolated loopback fixture. Existing clinical and QR browser suites remain unchanged. Evidence, screenshots and local runner scripts are retained under `/tmp/rhu-scan-ui-20261022`; separate development acceptance is under `/tmp/rhu-scan-ui-development`.

## Screenshots

All committed screenshots use isolated synthetic data.

| View | Before | After |
| --- | --- | --- |
| Desktop dashboard | [Before](screenshots/ui-refinement/dashboard-before.png) | [After](screenshots/ui-refinement/dashboard-after.png) |
| Desktop order form | [Before](screenshots/ui-refinement/order-before.png) | [After](screenshots/ui-refinement/order-after.png) |
| Mobile | — | [Dashboard](screenshots/ui-refinement/dashboard-mobile.png), [patient reports](screenshots/ui-refinement/patient-mobile.png) |

## Deployment and preservation

Deployment follows the existing frontend process: protect the previous served frontend and local dist, publish hashed assets first, preserve earlier hashes for open tabs, and replace `index.html` atomically. No database migrations, backend/Fabric restarts or clinical writes are needed. Protected deployment evidence and rollback files are in `/var/backups/rhu-labchain/20261022-ui-refinement` and `/var/log/rhu-labchain-deployments/20261022-ui-refinement.json`.

The live acceptance procedure uses the pre-existing synthetic laboratory identity for read-only navigation and unsaved selections, restoring its disabled state and original credential afterward and retaining authentication/audit events. Live patient, catalog, order, specimen and result mutations are excluded from this UI release. Database-table, historical report-file and environment hashes are compared before/after; public HTTPS assets and verification are checked against actual MySQL/Fabric.

Known limits: Vite still warns that the existing main bundle exceeds 500 kB (about 521 kB minified / 152 kB gzip). No new runtime dependency contributes to it. Browser checks use Chromium, including controlled camera media; physical devices and other browser engines were not exercised. Wide clinical tables intentionally retain horizontal scrolling within their labeled table regions. No blocking visual or usability defect remained in the tested paths.

### Completed live acceptance

Frontend source commit **`d20f3cd73d22ece1c7bdfb564383ad6339a25110`** was deployed to `https://labchain.online`. The public root HTML and all three current CSS/JavaScript assets match the tested release byte for byte. Health and readiness return HTTP 200. The existing server serves the entry point at `/`; direct `/index.html` remains an existing 404 and was not reconfigured.

Real Chromium signed in with the existing synthetic laboratory account, exercised the grouped navigation and keyboard drawer, reopened its existing order, and selected all four requested imported panels plus Hemoglobin in the actual live ordering form. The combined selection correctly showed 48 unique components and EDTA Whole Blood, Serum, Stool and Urine. UNREVIEWED/simulation wording remained visible, Create order was enabled, and all restricted catalog entries remained unavailable. Live ordering layouts passed at all five widths; the public verification page had no detected axe violations or browser errors. This UI release made zero live clinical writes; save and specimen/result/report transitions were exercised in the isolated full-API journeys described above.

Live public verification of the existing released report returned stored-artifact MATCH and Fabric VERIFIED; the original PDF comparison matched, altered bytes mismatched, malformed PDF upload returned 415, and anonymous private-PDF access remained denied. The orderer and all four peers were ONLINE at ledger height 7; both existing blockchain outbox events remained CONFIRMED.

Final integrity comparison preserved all **49 non-operational database tables**, historical report files, automatic-code state, roles/permissions and environment bytes. Only expected authentication/audit/service-observation activity changed. The existing synthetic account's original password hash and disabled state were restored and all its sessions revoked. Prior frontend assets remain available for rollback/open tabs. API, worker, monitor and Nginx PIDs were unchanged throughout deployment. No backend or Fabric restart occurred.
