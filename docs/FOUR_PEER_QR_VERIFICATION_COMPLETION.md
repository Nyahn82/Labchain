# Four-peer QR verification — 23 October 2026

Completed on the running development website, https://labchain.online. Application commit: `7a8fc17d02b70c0036a952ac55ab14ac2928fdef`. Live public/staff browser acceptance completed on 23 October 2026 at 17:35 Singapore time (09:35 UTC). The following documentation-only commit records acceptance; it requires no service restart.

## Implementation

Previously, public QR authenticity checked the report anchor and committed transaction on peer1; the four-peer dashboard checked network health separately. The QR path now requests bounded `report_evidence` observations through the existing protected monitor Unix socket. Existing explorer/dashboard actions keep their established behavior.

The monitor opens four independent TLS-verified Endorser connections: peer1/Org1MSP:7051, peer2/Org1MSP:8051, peer3/Org2MSP:9051, peer4/Org2MSP:10051. Each uses its configured CA and explicit peer certificate hostname. Signed read-only proposals target that endpoint directly, without Gateway discovery/failover. FastAPI receives bounded validated observations, never Fabric credentials.

For each required release/lifecycle event, each peer independently supplies its channel height, `ReadAnchor` state, and the actual relevant block. The monitor validates block data hash, computes the Fabric DER header hash, locates the specified transaction, reads its validation code and channel, and extracts the immutable anchor write from the `labchain-anchor` read/write set. It compares that write with the peer's world state. Creator MSP comes from the committed transaction's serialized identity.

The backend reuses frozen canonical event validation. Per-peer checks include report entity UUID and version, PDF digest association via the canonical commitment, event type, anchor UUID, commitment SHA-256, predecessor hash/event, transaction ID, VALID/code 0, expected block number, channel, source node/MSP, creator MSP, peer/MSP identity, observation freshness, and complete required event coverage. The PDF digest/version are committed through the canonical hash; they are not invented as separate chaincode fields. Supersession/revocation evidence follows the existing frozen lifecycle links.

## Aggregation and limits

- Only four complete, fresh, matching peer observations produce `FOUR_PEER_VERIFIED`.
- Any contradictory evidence produces `CONFLICT`; no majority overrides it. Relevant block hash disagreement is a conflict; latest ledger tips are not compared for report authenticity.
- Known invalid transactions or mandatory validation failures produce `FAILED`, even when another query times out. Available committed writes remain checked when world-state retrieval times out.
- Some verified peers plus ordinary missing/offline/timeout/lagging observations produce `PARTIAL`. A peer below the required block is `LAGGING`; a reached block lacking the required transaction is `MISSING`.
- Pending lifecycle receipts cannot yield full verification. All unavailable observations yield `UNAVAILABLE`.
- Four peers query concurrently, at most four lifecycle events and two evidence queries per event. Each gRPC proposal has a 2.5-second deadline; existing socket/request admission and public rate protections remain. No new agreement cache is used.
- Backend observations must be within 30 seconds (five seconds future skew allowed). The UI stops claiming fresh agreement after one minute and offers refresh. A post-query lifecycle reread invalidates evidence if the report changed during verification.

Registration, lifecycle, official stored PDF integrity, presented PDF comparison, issuing-facility snapshot, and blockchain evidence remain separate. QR recognition alone never authenticates surrounding printed text. Exact PDF byte comparison remains unchanged.

## Scanner

Public and personnel scanners keep the existing local ZXing decoder, camera cleanup, image handling, and token/URL validation. Compact peer rows show actual outcomes and observation time; explanatory and protected technical details are expandable. Scan Again resets the result and focuses Start Camera after navigation. Desktop staff view puts the wider official PDF on the left and verification on the right. Mobile puts summary/peers before the PDF, full-PDF link, and Scan Again. Clinical PDF content remains authenticated.

## Tests before deployment

- Monitor/gateway: 59 passed, including distinct peer sessions, peer1 offline, lagging, invalid receipt, state/write conflict, wrong channel, timeout plus invalid/conflicting committed evidence, and bounded request validation.
- Backend selected regression suite: 227 passed, one skipped, one obsolete exact-response assertion failed. After adding the two intentional privacy-safe peer fields to that assertion, the targeted release test passed: all 228 selected tests pass across the run and correction. The skip is the opt-in browser fixture export; it was separately run successfully.
- Frontend full suite: 382 passed. Final scanner/navigation edits: 42 focused tests passed. Production build passed; existing large-bundle advisory remains.
- Real Chromium with isolated SQLite/synthetic Fabric: actual ZXing video and image decoding, manual fallback, permission-denial handling, camera track cleanup, protected PDF exact hash/full link, staff evidence, and 390/1280px layouts passed. Controlled video is not a physical-camera test.
- Six explicit synthetic browser states (four verified, offline partial, lagging partial, conflict, failed, unavailable): correct labels, no full-document claim, Scan Again focus, no mobile overflow, zero scanner WCAG A/AA axe violations.

Scripts: `tests/browser/qr-scanning.mjs`, `tests/browser/four-peer-states.mjs`, and the isolated `serve_qr_fixture.py`. Failure scenarios use doubles; no live peer was taken down or corrupted.

## Preservation and security

No migrations, chaincode deployment, ledger submission, PDF regeneration, signing/release changes, or clinical workflow changes. Public responses expose only peer labels, status/count and observation time in addition to the existing redacted verification fields. Internal hashes/transaction identifiers remain protected by existing explorer/integrity permissions. No tokens, patient values, credentials or PDF contents are included in evidence summaries.

Protected rollback baseline: `/var/backups/rhu-labchain/20261023-four-peer` includes a consistent MySQL dump, source/frontend/PDF archives, database fingerprints, report file hashes and service/config baselines. Post-deployment comparison passed: all historical report files and outbox rows remain unchanged.


## Actual live Fabric acceptance

This is actual ledger evidence from the deployed monitor, separate from synthetic tests. Four historical report versions were checked: two current releases and two superseded versions. The latter required both release and supersession events, including predecessor links. Across these reports, each peer independently provided six valid committed event witnesses. Protected raw identifiers/hashes are retained in the root-only backup, rather than published in this document.

| Peer | TLS identity / organization | Historical versions checked | Relevant event witnesses | Outcome |
|---|---|---:|---:|---|
| peer1 | peer1.org1.labchain.internal / Org1MSP | 4 | 6 | VERIFIED |
| peer2 | peer2.org1.labchain.internal / Org1MSP | 4 | 6 | VERIFIED |
| peer3 | peer3.org2.labchain.internal / Org2MSP | 4 | 6 | VERIFIED |
| peer4 | peer4.org2.labchain.internal / Org2MSP | 4 | 6 | VERIFIED |

Every witness matched the expected canonical commitment, PDF digest/version association, transaction ID/validity, relevant block, issuer MSP and lifecycle predecessor. See [per-report/per-peer observations](screenshots/four-peer-20261023/live-four-peer-acceptance.json). A superseded report's ledger evidence can be valid while its lifecycle remains SUPERSEDED; this never certifies it as current.

[Public HTTPS acceptance](screenshots/four-peer-20261023/public-acceptance.json) verified both current releases: original PDFs MATCH, altered PDFs MISMATCH, all four peers VERIFIED, anonymous private-PDF/staff access denied, historical QR redirects retained, invalid PDF envelopes rejected. One legacy report has no historical issuer snapshot and still honestly reports LEGACY_UNAVAILABLE. No issuer details were backfilled.

The separate network overview showed four peers and the orderer ONLINE, height 12, and seven CONFIRMED outbox events. These health indicators were not used as proof of report authenticity.

## Deployed browser acceptance

[Live browser evidence](screenshots/four-peer-20261023/live-browser-evidence.json) records real Chromium requests against https://labchain.online:

- Camera decoded the actual QR image extracted from an existing historical PDF. Image upload decoded its full rendered page. Manual entry and Scan Again worked.
- Original PDF comparison showed a verified document match. An altered copy retaining the genuine QR showed a document mismatch while all four peers continued to verify the original.
- Authenticated personnel retrieved the exact existing PDF. SHA-256 of the viewer's blob matched the stored artifact; the full-PDF link referenced those same bytes.
- Desktop used a wider PDF viewer on the left; mobile put summary/peers before the viewer/link. Neither viewport overflowed. Scanner axe checks found zero WCAG A/AA violations at 390px and 1280px.
- The live test account lacks explorer permissions: technical identifiers were correctly withheld. Authorized detailed witnesses were demonstrated in isolated browser tests and retrieved independently through the actual protected monitor for live acceptance.

The initial catalog acceptance account had no staff link, and the staff gate correctly denied it. A temporary synthetic staff profile was created using the existing automatic code allocator and linked solely for this check, without role/permission changes. Afterwards the profile/link were removed, original account credentials/status restored, sessions revoked and the credential file removed. One STAFF code remains consumed and is never recycled; the other six code sequences are unchanged. No patient/order/result/report or Fabric transaction was created for acceptance. The initial browser harness also required correction of its launch environment and altered-PDF envelope; final acceptance passed after those harness fixes.

### Screenshots

Live staff screenshots deliberately mask the private PDF region. The viewer and its exact bytes were checked before masking; synthetic screenshots show the complete layout without exposing clinical information.

- [Live public — mobile](screenshots/four-peer-20261023/live-public-mobile.png)
- [Live public — desktop](screenshots/four-peer-20261023/live-public-desktop.png)
- [Live staff — desktop, PDF masked](screenshots/four-peer-20261023/live-staff-desktop-redacted.png)
- [Live staff — mobile, PDF masked](screenshots/four-peer-20261023/live-staff-mobile-redacted.png)
- [Isolated synthetic staff — full PDF and protected evidence](screenshots/four-peer-20261023/synthetic-staff-desktop.png)
- [Simulated offline partial state](screenshots/four-peer-20261023/simulated-partial-mobile.png)
- [Simulated conflicting state](screenshots/four-peer-20261023/simulated-conflict-mobile.png)

## Final preservation and deployment checks

[Integrity results](screenshots/four-peer-20261023/final-integrity.json): 48 database tables remain byte-for-byte equal under ordered row fingerprints, including historical clinical data, staff/link rows, report/hash records and blockchain outbox records. Only audit/session/login/service observation activity, account last-login time and the one intentional STAFF code allocation changed. Stable account fields were compared separately and restored. Historical PDFs and environment configuration are unchanged. Previous frontend assets remain available; served release assets match the tested build.

Only `rhu-labchain-monitor` and `rhu-labchain-node1` were restarted. API readiness, public HTTPS, monitor, worker and nginx passed; worker/nginx process IDs remained unchanged. Fabric peers/orderer were not restarted or reset. No migration, chaincode deployment or ledger submission occurred.

Relevant commands:

```sh
PYTHONPATH=. .venv/bin/pytest tests/test_public_authenticity.py tests/test_qr_scanning.py tests/test_phase9_monitor.py tests/test_phase_5b_release.py tests/test_phase_8b_outbox.py -q
# Exact privacy-contract assertion corrected and rerun successfully:
PYTHONPATH=. .venv/bin/pytest tests/test_phase_5b_release.py::test_release_snapshots_pdf_qr_hash_and_download -q
# From blockchain/gateway-adapter:
npm test
# From frontend:
npm test -- --run
npm test -- --run src/test/verification.test.tsx src/test/qr-scanning.test.tsx
npm run build -- --outDir /tmp/rhu-four-peer-build
```

## Limits

Camera acceptance used real Chromium/ZXing with controlled video input, not a physical phone. Live peer outages/conflicts were not induced; these branches were tested with independent synthetic responses and browser overrides. All four Fabric peers run on the existing single VPS, so four observations do not establish four independent physical fault domains or change endorsement policy. The existing build size advisory remains. Historical issuer evidence that was never stored remains unavailable. Public QR recognition still cannot establish that surrounding printed results are unchanged; use PDF comparison.
