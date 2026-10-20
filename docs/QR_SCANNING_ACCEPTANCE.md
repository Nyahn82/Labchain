# QR scanning and authorized original-report acceptance

Baseline: `baa7e27194650490823b911b21d5198df3601f79` (deployed application code
`5832428cca1daa9793accaf727be7684fd34e6f7`). Database: `20261019_01`.

## Workflows and security boundaries

Public `/#/verify` now offers **Scan QR Code**, an explicit-permission live camera
preview, front/rear preference switching, local QR image decoding, and the existing
manual token entry and exact-PDF comparison. Camera tracks stop on success, close,
page exit, hidden tab, permission failure, and late permission responses after cleanup.
Denied/unavailable/unsupported cameras retain image/manual alternatives. Scanning
another report does not require an application restart.

Only 43-character opaque tokens and exact supported HTTPS RHU verification URLs are
accepted from QR images. Decoded content is never used as a navigation destination:
the extracted token selects an internal route. External hosts, credentials, extra query
parameters, non-HTTPS schemes, ambiguous paths and malformed contents are rejected.
Frames and selected QR images are decoded locally; only the token reaches the server.
Images are restricted to PNG/JPEG/WebP, 10 MiB, 25 million decoded pixels, and a maximum
2400-pixel decoding canvas. The pinned `@zxing/browser` 0.2.1 dependency uses the
[ZXing browser implementation](https://github.com/zxing-js/browser), with its QR decoder
rather than requiring the unevenly supported native BarcodeDetector API. It is loaded
on demand from the site's own assets, not a third-party CDN.

Personnel enter **Reports → Scan QR and view official report** (`/#/reports/scan`).
Scanning resolves the exact report ID and historical version using
`POST /api/v1/verify/staff/resolve`. This endpoint requires normal authenticated sessions,
CSRF, an active personnel role, REPORT_READ **and** REPORT_DOWNLOAD, and an active
linked staff identity unless SYSTEM_ADMIN. PATIENT roles are excluded, including mixed
roles. Existing MFA/session/account policies still apply. No permission is granted by
possessing a QR. No new privilege or role is bootstrapped.

The UI then fetches the original through the existing `/reports/{id}/pdf` endpoint.
It checks the artifact SHA-256 and permission again, returns the exact stored bytes,
and writes the existing REPORT_DOWNLOAD audit. The application displays an inline PDF
with patient identification, tests/results, specimens, ranges, dates and signatures as
recorded in that historical original; nothing is regenerated or filled in from today's
records. **Open full official PDF** opens the same authorized blob. Scan changes and
session loss clear the embedded viewer and revoke its object URL. Browser-native PDF
support varies; the full-PDF link remains the fallback.

Live public verification evidence appears alongside the private original. Staff with
both existing BLOCKCHAIN_EXPLORER_VIEW and BLOCKCHAIN_INTEGRITY_VERIFY also see the
independently validated PDF hash, canonical commitment, transaction/block, issuer MSP,
queried peer and observation time. Other authorized personnel see the same privacy-safe
live verification outcome available publicly. MySQL CONFIRMED alone is never proof.
The existing checks bind report UUID/version, digest, lifecycle, issuer organization,
committed valid transaction and observation freshness. Partial/stale/unavailable evidence
never overrides the overall outcome.

Successful personnel lookups write REPORT_QR_VERIFY with the actor, exact report/version
and outcome dimensions. Audit payloads exclude QR tokens, images, clinical values and
PDF bodies. The existing bounded verification admission limits apply. Responses are
no-store. Revoked/superseded historical versions stay explicitly noncurrent while
remaining available through established staff download rules. Patient ownership and
public privacy are unchanged.

## QR generation and historical compatibility

The PDF renderers are unchanged: error correction M, four-module quiet border, six-pixel
source modules; displayed size is 102 points for legacy v1 and 90 points for v2. The
existing historical report contains a 270×270 QR image. Its original PDF hash was checked
before rasterizing the page at 150 DPI for browser decoding. No historical PDF or QR
was rewritten. Existing `/api/v1/verify/{token}` QR URLs retain their HTML redirect to
`/#/verify/{token}` and JSON API behavior. The exact report/version is checked in tests.

A QR scan identifies a registered report; it cannot read all surrounding printed text.
The PDF-upload feature still compares exact bytes and rejects an altered document even
when its copied QR refers to a valid report. Authorized personnel compare the presented
sheet against the private original within the scanner workflow.

## Validation and deployment evidence

Predeployment checks passed: 35 public authenticity/security tests, 11 personnel scanner
API tests and the optional synthetic browser fixture export; 49 frontend tests covering
verification, scanner lifecycle, permissions and patient reports. TypeScript/Vite and a
production-dependency audit passed (zero reported advisories). An initial fixture setup
omitted a required role-assignment timestamp and revision signatory; both fixtures were
corrected and the complete personnel suite passed. Camera DOMException handling was
made independent of JavaScript realm identity after a focused test exposed that issue.

Real Chromium 156 browser automation decoded actual QR pixels from controlled camera
video and an embedded PDF image, rejected an unrelated QR, used manual fallback, stopped
camera tracks, and showed no horizontal overflow at 390px and 1280px. In the isolated
synthetic database it performed a real login, authorized QR resolution, PDF retrieval,
SHA-256 comparison of the exact blob rendered in the native PDF viewer, full-PDF link,
ledger-witness display and a second scan. The rendered PDF and side-by-side evidence were
visually inspected. Camera-denial behavior was simulated explicitly in this browser
check and covered by component tests; it is not a physical-device permission test.
The first headless-shell harness lacked camera prompt/PDF support; the final test used
full Chromium with controlled camera approval. Temporary browser libraries were extracted
under `/tmp`, without installing host packages.

Checked-in reproducibility tools: `tests/browser/serve_qr_fixture.py` only accepts a
`/tmp/rhu-scan-*` synthetic SQLite export and replaces MySQL/Fabric dependencies;
`tests/browser/qr-scanning.mjs` exercises the built frontend. Export with
`RHU_SCANNER_EXPORT_DIR` and the optional fixture test in `tests/test_qr_scanning.py`.
Browser tools, local-only TLS certificate, build output and fixture files belong outside
Git and the public web root. Live deployment results are recorded below. Synthetic Fabric doubles are not evidence
of live Fabric; live public-site checks are reported separately.

No database migration is required. Deployment uses the established coordinated writer
fence, fresh encrypted database/files backup, isolated restore verification, matched
frontend/backend activation and controlled worker/traffic resumption. Fabric peers,
identities, channels and ledger storage are not restarted or altered.

## Deployed website and real ledger evidence

**Deployment: SUCCESS. Physical phone and owner's live staff acceptance: pending.**
Application code `1a493ec055da8e728e5857f703ea2f0421ebc510` is deployed at
[labchain.online](https://labchain.online/). Public scanner:
[Verify](https://labchain.online/#/verify). Personnel scanner:
[Scan and view official report](https://labchain.online/#/reports/scan).
Implementation was committed and pushed normally to `main`; the documentation follow-up
records the completed deployment without changing running code.

Traffic resumed **21 October 2026, 07:10:34 Asia/Singapore**. At 07:11:47,
API/worker/monitor were active, with original on-failure restart policies (5s/10s/10s),
zero automatic restarts, and an advancing HEALTHY worker heartbeat. The monitor and
Fabric infrastructure were not restarted. Database identity/revision remained
`rhu_labchain` / `20261019_01`; no migration or permission bootstrap was performed.

| Actual live check | Result |
| --- | --- |
| Chromium camera pipeline using controlled video of the existing historical QR | PASS: actual ZXing decode, exact token/report, live Fabric evidence, stream stopped |
| Full historical PDF page rasterized at 150 DPI and selected as a QR image | PASS: actual QR decoded to the correct public report/version; image stayed local |
| QR compatibility | Existing API URL returns HTML 303 to the correct SPA route and JSON evidence to API clients |
| Live public privacy | No private PDF or clinical data in the public workflow; anonymous personnel resolution and private PDF routes denied |
| Live public PDF comparison | Official bytes MATCH; altered bytes MISMATCH; stored artifact MATCH; independently queried Fabric VERIFIED |
| Invalid/external QR and manual fallback | External URL rejected without navigation; malformed/unknown token neutral NOT_FOUND |
| Frontend | Index, main JS, decoder JS and CSS hashes match the staged build; old hashed assets retained |
| Assets | `index-B7hp_rbG.js`, `esm-CuJYLdlD.js`, `index-0O6uKZgj.css` |
| HTTPS/API | Public health and database readiness HTTP 200 |
| Layout | Real Chromium at 390px and 1280px, no horizontal overflow; desktop original PDF rendering visually inspected using synthetic authorized data |
| Fabric/outbox | Four peers and orderer ONLINE, height 7; both existing outbox events CONFIRMED and unchanged |
| Data preservation | All 53 non-observation tables retain exact predeployment row hashes; only worker heartbeat changes; original PDF bytes/hash preserved |
| Historical issuer | Explicit LEGACY_UNAVAILABLE for the existing old report; no invented snapshot or full-success badge |
| Edge safeguards | Upload over 1 MiB streams successfully, 10 MiB cap returns 413; verification probe token absent from API/Nginx access logs |

Live browser evidence is separate from the synthetic staff/Fabric-double evidence.
The owner confirmed availability to perform the real staff and physical phone walkthrough;
results are requested and remain unconfirmed in this record. Automated video input and
viewport resizing do not certify Android, iPhone, Safari, optics or printed-paper quality.

### Backup and recovery

Fresh protected recovery bundle:
`/var/backups/rhu-labchain/20261021-1a493ec/recovery.tar.enc`.
SHA-256: `4d77af5e24ee4d6c29f3e8fae47ccf65f41302314ee793ad3e74bc706bb3d527`.
Separate root-only key reference:
`/var/backups/rhu-labchain-keys/20261021-1a493ec.key`.

All 54 tables were restored to an isolated socket-only disposable MySQL instance;
exact row hashes, private report hashes, prior frontend and protected configuration
matched. Database import took 1.98 seconds, not a full operational recovery-time claim.
Encryption/decryption checksum verification passed. Recovery instructions, source/artifact
archives and sanitized evidence are retained in the protected backup directory. Recovery
requires writer fencing and reconciliation of any post-backup writes; no destructive
restore or ledger reset was performed. Nginx configuration and TLS were unchanged.

Sanitized durable deployment report:
`/var/log/rhu-labchain-deployments/20261021-1a493ec.md`.
Protected evidence includes `final-evidence.json`, `public-acceptance.json`,
`https-assets.json`, `synthetic-browser-evidence.json`, `live-browser-evidence.json`,
and focused test/build logs. Test fixture corrections and harness limitations are
retained honestly rather than represented as live clinical or physical-camera proof.

## Owner's physical and live-staff acceptance

Physical Android/iPhone, printed-paper scanning and a real authorized live staff browser
session are pending unless explicitly recorded below. Chromium automation with controlled
camera video does not establish physical-camera, Safari/WebKit or real-device behavior.

1. Sign in through the normal staff login with existing report read/download permissions.
   Open historical report **RPT-20261008-4D938ED495115106, version 1** from Reports and
   its official PDF. Use only your authorized copy; do not post it publicly.
2. Display the PDF at normal size on another screen or print it at 100% without cropping
   the QR/quiet border. Scan it with an ordinary Android/iPhone camera, then open the
   HTTPS link. No sign-in is needed for this public verification step.
3. Expect this exact report/version, REGISTERED, document NOT_COMPARED, stored artifact
   MATCH and current independent Fabric evidence. The existing historical report lacks
   an issuer snapshot: expect that limitation, not a full green document-match claim.
4. In public Verify, select Scan QR Code, allow camera access, scan, switch cameras,
   close/reopen, and scan again. Try a QR image and manual token. Denying permission
   must retain those alternatives; an unrelated site's QR must never open that site.
5. In the signed-in staff workspace choose Reports → Scan QR and view official report.
   Scan the same QR. Confirm version 1's original patient/results/specimen/range/date/
   signatory content appears in the embedded PDF alongside real verification evidence.
   Open the full PDF and compare it privately with the presented sheet. Detailed ledger
   witnesses require the existing explorer/integrity permissions.
6. Scan another QR without restarting. Confirm the previous private PDF clears while the
   next loads. Confirm REPORT_QR_VERIFY and REPORT_DOWNLOAD in authorized audit review.
7. Repeat anonymously and with an account lacking download permission: neither may
   receive the private original. For copied-QR testing, use a synthetic altered document,
   never edit/re-release a live clinical report. Different bytes must show MISMATCH.

Record device/OS/browser versions, screen versus printed source, time, each outcome and
any failure. This task does not expand the laboratory catalog, add payments, change codes,
create live clinical fixtures, invent issuer credentials or overwrite report history.
