# RHU LabChain — presenter notes

Suggested delivery: 12–15 minutes plus questions. Slides 1–17 form the presentation; slide 18 is a reference appendix. Survey findings are limited to slide 15.

## 01. Laboratory records. Verifiable reports.

Introduce RHU LabChain, the Block-Chain Powered Laboratory Records and Verification System. The study focuses on laboratory workflows at the RHU of M’lang, North Cotabato. Explain that the presentation follows one report from laboratory request through release, blockchain commitment, and later verification. Suggested duration: 12–15 minutes, with most time on slides 6–13. The system is an academic prototype using synthetic laboratory records.

**Sources:** Based on papers.pdf, Chapters III–VI; local RHU LabChain implementation.

## 02. The system adds evidence to a laboratory report

The project addresses laboratory record handling and the need to check whether a released report has changed. Structured workflows manage the work; the blockchain adds a reference for report integrity and lifecycle verification. Keep this distinction clear: favorable usability is not automatically a blockchain benefit. This is a laboratory information and report verification system, not a full electronic health record or a diagnostic engine.

**Sources:** Paper: pp. 3–5, 18–21.

## 03. Three access paths support different tasks

Authorized staff handle registration, laboratory processing, verification, signing, approval and release according to permissions. Patients use authenticated accounts to access eligible reports belonging to them. A public verifier can look up limited report information without receiving patient names or laboratory findings. Scanning a QR does not grant access to private clinical content.

**Sources:** Paper: pp. 4–5, 18–20, 31–37.

## 04. From laboratory request to released report

Walk through the eight steps in reading order. Registration associates the patient and request. Specimen records connect the sample to the order. Staff enter findings and authorized personnel verify them. The report snapshot then goes through signing and approval before release. At release the system generates the final PDF and captures the blockchain event. Later corrections use another report version and approval cycle rather than silently changing the released report.

**Sources:** Paper: pp. 4, 18–20, 31–36.

## 05. Clinical records and blockchain evidence work together

The React interface sends requests to FastAPI. MySQL stores operational records and lifecycle information, while private storage retains released PDFs. A background worker and Node.js adapter deliver commitments to Hyperledger Fabric. A separate protected monitor reads report-specific evidence from peers during verification. The database remains the operational source of truth. IPFS is not part of the implemented system.

**Sources:** Paper: pp. 18–21; architecture diagram redrawn for this presentation.

## 06. Release captures the report and queues its evidence

On release, the application generates the final PDF, stores it privately and computes the digest of those exact bytes. It constructs the canonical lifecycle event and saves the release state and outbox row in one MySQL transaction. The outbox is a durable delivery queue. The worker later submits the commitment to Fabric. Release and blockchain confirmation therefore occur separately. PENDING means captured for delivery, not confirmed on-chain.

**Sources:** Paper: pp. 18–20; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.

## 07. Two hashes bind the PDF to its blockchain anchor

There are two different hashes. D is the SHA-256 digest of the exact released PDF bytes. The canonical event includes D plus the report UUID, report version, event type, occurrence time, source identity and relevant lifecycle links. Canonical means a fixed serialization: the same event produces the same bytes. C is the SHA-256 hash of those canonical bytes. The chaincode anchor stores C as content_hash, plus selected metadata. The PDF digest and report version are bound through C, not stored as separate PDF fields in the anchor. Hashing is not encryption and cannot establish that the original laboratory findings were clinically correct.

**Sources:** Paper: pp. 16, 20–21; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.

## 08. How an event becomes a committed Fabric transaction

The worker validates the frozen event and uses an identified Fabric client through the Gateway. A CreateAnchor proposal is endorsed under the configured policy; the repository channel configuration requires endorsement from Org1 and Org2. Endorsement simulates the chaincode operation. The orderer orders the endorsed transaction into a block. Peers then validate endorsements and concurrency conditions and commit the block; only valid writes update world state. The adapter checks commit status and the worker reconciles the anchor before confirmation. The smart contract checks allowed identities and event fields and rejects an existing anchor ID. These transaction rules differ from the later application requirement to query all four peers.

**Sources:** Paper: p. 20; gateway-adapter/src/adapter.js; network/config/configtx.single-vps.yaml.

## 09. Four peers, two organizations, one shared host

Draw attention to the outer boundary: every node runs on the same VPS. Org1 contains peer1 and peer2; Org2 contains peer3 and peer4. A single Raft orderer orders transactions for the channel. Separate identities and ledger copies demonstrate logical distribution. They do not establish independent institutions or physical fault tolerance. One host failure affects the entire network, and one orderer is also an availability dependency. Blockchain replication does not back up the private PDF and clinical database.

**Sources:** Paper: pp. 17, 20–21; blockchain/network/config/configtx.single-vps.yaml.

## 10. Verification joins document, lifecycle and ledger evidence

A QR, code or supported report URL identifies a report. The application looks up registration, lifecycle and available issuer information; checks the stored official artifact; and retrieves report-specific evidence from four peers. If the verifier submits a PDF, its digest is compared with the issued artifact. These checks produce distinct outcomes. A copied genuine QR can still identify the original report even when surrounding printed values were altered. Verification of the exact document requires byte comparison of the PDF.

**Sources:** Paper: pp. 19–21, 36–42.

## 11. Four-peer verification has explicit outcomes

All four peers must supply complete, fresh and matching evidence for all required lifecycle events. An offline or lagging peer with other verified observations produces PARTIAL. Contradictory evidence produces CONFLICT; three matching peers do not override it. Invalid transactions or mandatory validation failures produce FAILED. Pending receipts and unavailable evidence cannot support full verification. Equal ledger height or an online indicator is only a network health observation. The checks concern the specific report commitment, transaction validity, relevant block and lifecycle links.

**Sources:** Paper: pp. 20–21, 25, 39–42; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md.

## 12. A report’s history survives correction or withdrawal

REPORT_RELEASED records an issued version. A correction goes through a new draft, signing, approval and release cycle. The new version receives a release event, and the predecessor receives REPORT_SUPERSEDED evidence referring to the replacement. Explicit withdrawal creates REPORT_REVOKED. Revocation and supersession link to that report’s original release commitment. Old artifacts and anchors are retained. A historical PDF can therefore match its original bytes and have valid ledger evidence while being marked superseded or revoked; integrity does not imply current clinical use.

**Sources:** Paper: pp. 16, 20, 34; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.

## 13. The queue separates clinical work from ledger delivery

Clinical release captures an outbox event without requiring a synchronous Fabric call. If delivery is temporarily unavailable, the worker uses bounded retries. Before submission and after uncertain outcomes it checks for an existing anchor; matching evidence can reconcile a lost acknowledgement. A conflicting existing anchor is not overwritten. Events become CONFIRMED only with matching committed evidence. Permanent failures or exhausted retries require investigation. This improves delivery handling while the application and database are available; it does not remove the single-host failure boundary. The slide is an implementation explanation, not a measured availability claim.

**Sources:** Paper: pp. 18–20; docs/PHASE_8B_DELIVERY_WORKER.md.

## 14. The paper shows successful and incomplete verification

Use these original paper figures as visual evidence. Figure 4.9 shows a presented PDF MATCH and four peers verified. Figure 4.12 shows a mismatch warning for a changed file. Figure 4.14 shows partial verification with three peers verified and peer4 offline; the presented file is NOT COMPARED in that case. Each screenshot documents a displayed scenario. These are not repeated benchmarks, measured detection rates or proof of broad production readiness. Demonstration suggestion: explain the original PDF first, then a changed copy carrying a genuine QR, and finally the partial peer state.

**Sources:** Paper: Fig. 4.9 (p. 37), Fig. 4.12 (p. 40), Fig. 4.14 (p. 41); synthetic report examples.

## 15. Survey feedback was favorable in both groups

Keep this slide brief. The patient group contains 30 convenience-sampled respondents. The staff group is the census of 11 eligible individuals: eight laboratory personnel and three IT personnel. Each instrument has 30 statements on a five-point agreement scale. Overall means are 4.64 for patients and 4.62 for staff. The table retains the three research-question sections separately because the questionnaires cover role-specific tasks. These ratings represent perceptions, not measured technical security or faster processing. Do not combine the two groups into one score or interpret item-rating percentages as respondent percentages.

**Sources:** Paper: Tables 4.3–4.4, pp. 42–44; corrected staff tally.

## 16. The prototype’s boundaries guide the next evaluation

Pair each limit with a practical next step. All peers share one VPS, so separate-host deployment and recovery testing are needed. A digest match proves byte correspondence, not the clinical correctness of the original result; clinical workflow review and authorization remain necessary. The paper contains screenshots rather than comprehensive repeated logs, so document conflicting evidence, outage recovery and permission denial cases. Aggregated survey tallies and absent timed comparisons limit conclusions about reliability and objective efficiency; collect anonymized respondent-level data and repeatable task measurements. Keep the conclusion at academic prototype level.

**Sources:** Paper: pp. 20–25, 42, 47–50.

## 17. From a released report to evidence that can be checked

Close by following the chain once more: the laboratory workflow creates an approved release; the PDF is fingerprinted; its identity, version and digest are bound in an event; that event commitment is recorded in Fabric; later verification combines report lifecycle, document comparison and peer evidence. The contribution is integrated workflow plus tamper-evident report verification under the stated prototype conditions. Survey feedback is positive, while broader operational and clinical evaluation remains future work. Invite questions.

**Sources:** Paper: Chapters III, IV and VI.

## 18. Sources and presenter reference

This reference slide is optional during delivery. All survey values and study conclusions come from the supplied papers.pdf. Detailed transaction and delivery descriptions are cross-checked against the local source and project documentation. Where documentation describes separate implementation tests, those have not been presented as participant results or added to the paper’s empirical findings. Original screenshots retain the resolution of the supplied paper. The PowerPoint diagrams, labels and survey table are editable native shapes and text.

**Sources:** Source material supplied by the user and local project files; no external claims added.

