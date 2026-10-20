# QR, blockchain and report authenticity completion

Review date: 20 October 2026 (Asia/Singapore).
Development baseline: `95a185cbd9212fe284b8fd6e6780ccd7727ff4ae`.
Database baseline and target: `20261019_01`; **no database migration**.

## Meaning of verification

A public QR lookup now identifies a registered report, not an authentic presented
sheet. The public response separates lifecycle status, submitted-document comparison,
stored-artifact integrity, historical issuer evidence and independent blockchain evidence.
The UI shows **Verified document match** only when the report is current, uploaded
bytes match, the official artifact passes its digest check, a historical issuer
snapshot exists, and independent Fabric evidence is verified and fresh.

| Dimension | Outcomes |
| --- | --- |
| Registration/lifecycle | REGISTERED, REVOKED, SUPERSEDED, NOT_FOUND, UNAVAILABLE |
| Submitted PDF | NOT_COMPARED, MATCH, MISMATCH |
| Official stored artifact | MATCH, MISMATCH, UNAVAILABLE |
| Historical issuer | SNAPSHOT, LEGACY_UNAVAILABLE |
| Independent blockchain | VERIFIED, PENDING, FAILED, UNAVAILABLE |

A mismatch means different bytes; it does not by itself prove malicious editing.
A matching historical revoked/superseded PDF remains noncurrent. Missing historical
issuer context is not reconstructed from today's mutable facility configuration.
Licensing, accreditation, clinical correctness and surrounding printed text are not
certified by a QR lookup or blockchain commitment.

## Reused architecture and preserved behavior

Existing opaque 256-bit tokens, immutable released PDF storage, SHA-256 verification
records, frozen presentation snapshots, signing/approval/revision lifecycle, transactional
outbox, chaincode, direct signed peer queries and committed transaction validation are
reused. No competing ledger, contract redeployment, code reassignment or database rebuild.
Automatic-code allocation, clinical workflow services, PDF renderers, outbox capture,
patient ownership and MFA mechanisms remain unchanged.

Historical PDF bytes and embedded QR URLs are not rewritten. GET
`/api/v1/verify/{token}` retains JSON for API clients; requests accepting HTML receive
a 303 to `/#/verify/{token}`. Existing printed QRs therefore open the updated page.
The public API contract deliberately replaces the former unconditional VERIFIED label
and MySQL-only blockchain badge with the dimensions above; API consumers must adopt it.

## Public UI and authorized comparison

The responsive page displays the registered report code, historical issuing facility
when available, version, release time, lifecycle state, each check's outcome and evidence
timestamps. It has explicit copied-QR and printed-text limitations, keyboard-labeled
file input, live status/error messages, and readable outcome text independent of color.
Evidence expires visually after one minute. Changing the token/file invalidates prior
comparison; aborted or failed uploads cannot leave a successful prior comparison active.

Public responses exclude patient names/codes/results, PDF paths, tokens, canonical
payloads, transaction IDs, source MSPs and private ledger identifiers. Users seeking the
original report are directed to existing patient or staff report pages, which enforce
normal sign-in, ownership, permissions and MFA. This does not grant a new public download
or allow a patient to see another patient's report. Historical downloads remain subject
to existing patient/staff policies.

## PDF comparison and safeguards

POST `/api/v1/verify/{token}/compare` accepts a raw `application/pdf` body, not a client
supplied digest or filename. It streams SHA-256 over exact bytes; only small prefix/tail
buffers and the digest are retained. No uploaded document is saved, rendered, decompressed,
executed or parsed with a PDF engine. PDF header/EOF checks reject wrong envelopes;
this is not a claim of full semantic PDF validation or malware scanning. An unrelated
PDF with a valid envelope returns MISMATCH rather than receiving authenticity status.

Limits: 10 MiB default (`VERIFICATION_UPLOAD_MAX_BYTES`, configurable 1 KiB–25 MiB),
30-second upload deadline, two concurrent verifications, 20 requests per IP/minute by
default (`VERIFICATION_REQUESTS_PER_MINUTE`), and a global 60 requests/minute/process.
Both declared and streamed sizes are enforced. Invalid lengths, encodings, cross-site
browser submissions and incomplete bodies are refused. Busy/rate-limited requests get
safe 503/429 responses. Forwarded headers are interpreted only by the existing trusted
Uvicorn proxy configuration; the limiter does not trust arbitrary client X-Forwarded-For.

Admission state is bounded in memory for the current single API process. It resets on
restart and is not a distributed quota; scaling to multiple processes/hosts requires a
shared or edge quota. Deployment must align the Nginx upload cap with the configured
application cap and disable request buffering for this route. Uvicorn verification
access records are suppressed so capability tokens are not persisted there. No filenames,
uploaded bytes or document hashes are included in error messages or application logs.

The handling follows the size/type/resource controls described in the
[OWASP upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html),
with an intentionally public, nonpersistent byte-comparison endpoint instead of a stored
upload feature. The server never redistributes submitted content.

## Independent Fabric checks

The existing local monitor's anchor projection now also returns its already validated
source node/MSP. These fields remain internal. The chaincode already enforces membership
and node-to-submitting-MSP correspondence; the gateway validates the returned mapping.
No chaincode/channel/MSP/certificate changes are required.

For every relevant release/revocation/supersession event, verification checks canonical
payload/hash validity, report UUID and version, artifact digest, release timestamp,
predecessor hash/link and replacement-report UUID when applicable. Confirmed events then
require an independent anchor query and a committed-block transaction query. Anchor ID,
entity reference, event type, content hash, previous hash, source organization, transaction
ID, valid transaction code and recorded block number must agree. MySQL CONFIRMED alone
never produces VERIFIED. Unconfirmed events remain PENDING; failed/dead or inconsistent
evidence fails; missing, stale or inaccessible ledger evidence is unavailable. Report
lifecycle is reread after ledger queries to detect concurrent revocation/supersession.

The commitment binds the frozen canonical payload containing the PDF digest and report
version. Issuing-facility display comes from the authorized historical application snapshot;
there is no independently maintained legal-facility-to-MSP accreditation registry. Old
reports lacking this snapshot remain explicitly limited. A trusted configured peer is
queried independently of MySQL, not independently of the existing Fabric trust domain.

## Validation

| Check | Result |
| --- | --- |
| New synthetic security suite | 23 passed: `tests/test_public_authenticity.py`; `/tmp/rhu-qr-backend-final.log` |
| Release, outbox/status, monitor, patient privacy and historical PDF compatibility | 197 cases: 196 initially passed; one obsolete REVOKED expectation was corrected to SUPERSEDED and its complete scenario passed in the next run. `/tmp/rhu-qr-compatibility.log` |
| Corrected portal lifecycle + hosting | 8 passed, including the corrected case and seven hosting tests. `/tmp/rhu-qr-corrections.log` |
| Distinct backend cases | 227 across these runs, excluding the rerun |
| Frontend verification, blockchain presentation and patient reports | 77 passed across three files. `/tmp/rhu-qr-frontend.log` |
| Gateway protocol/monitor | 58 passed, including validated issuer projection and wrong-MSP rejection. `/tmp/rhu-qr-gateway-final.log` |
| TypeScript/Vite | Passed; output staged outside the running asset directory in `/tmp/rhu-qr-build`. `/tmp/rhu-qr-build.log` |
| Source checks | Python syntax and Git whitespace checks passed. Protected generator, clinical workflow, PDF renderer and outbox capture sources byte-identical to baseline. |

The copied-QR test alters an actual laboratory result text object in a synthetic PDF,
asserts the changed extracted result, and proves the original QR image bytes survived.
The original matches; the changed document mismatches despite genuine registration and
valid simulated ledger evidence. Invalid/tampered tokens, different versions, revoked and
superseded versions, missing issuer history, unavailable/incorrect ledger data, invalid
transactions, wrong issuer/block, size/rate/concurrency limits and private-field exclusion
are covered. Existing portal tests cover patient ownership and protected PDF access.

Gateway and backend unit doubles test contracts and failure handling; they are **not proof
of live Fabric integration**. No full backend regression was rerun. Existing framework
deprecation warnings remain. jsdom verifies mobile semantics and controls, not physical
layout, QR cameras or real signed-in browser behavior.

## Deployment and live evidence

Prepared for the authorized coordinated update. Live results and the deployed code commit
will be recorded after the cutover; no deployment success is claimed in this preparation
record. Required operations: fresh protected consistent backup and isolated restore;
maintenance and API/worker exclusion; deploy matched frontend/backend; restart the local
read-only monitor for its extended projection; verify existing stored PDF and real ledger,
raw uploaded match/mismatch, HTTPS and authorization boundaries; restore traffic and prior
restart policies. Database revision must remain `20261019_01` throughout.

No clinical records, reports, signatures, approvals, invitations, catalog imports or
Fabric write submissions should be created as smoke-test fixtures. Real-site upload checks
use the existing authorized stored artifact and altered bytes only in memory.

## Remaining limits

- Authorized signed-in browser and genuine camera walkthrough pending unless recorded
  below; component tests do not establish either.
- Full printed-text validation requires a private comparison with the official document.
- Missing historical issuer snapshots cannot be invented or silently backfilled.
- A regenerated or re-saved PDF can differ benignly; mismatch does not identify an editor
  or establish fraudulent intent.
- No assertion of current DOH licensing/accreditation, clinical accuracy, malware absence
  or trust beyond the configured laboratory/Fabric identities.
