# Four-peer QR verification — 23 October 2026

Deployment acceptance is in progress. This document will be completed with live evidence after the application and monitor update.

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

Protected rollback baseline: `/var/backups/rhu-labchain/20261023-four-peer` includes a consistent MySQL dump, source/frontend/PDF archives, database fingerprints, report file hashes and service/config baselines. Historical files and outbox integrity will be compared after live acceptance.
