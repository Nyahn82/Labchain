# Revised defense presentation — presenter notes

18 slides. Allow 45–60 seconds per slide: approximately 13.5–18 minutes, excluding questions. Rehearse actual delivery. All technical and study sources appear below and in the PowerPoint speaker notes.

## 01. Title

Introduce RHU LabChain using the full study title. The setting is the Rural Health Unit of M’lang, North Cotabato. This is an academic laboratory-record and report-verification prototype using synthetic reports. State the main question: after a laboratory report is released, how can another person check its document integrity and current status? Explain that the presentation emphasizes the system process and blockchain, followed by concise technical observations and one survey slide. This deck adapts the guide’s machine-learning sections to a system-development study; there is no predictive model or model-training dataset.

**Source:** papers.pdf, pp. 3–5, 18–21; Defense_PPT-Gudelines.pdf, pp. 1–2.

## 02. Problem statement

The paper identifies the difficulty of retrieving and tracking paper-based laboratory records and the need to protect sensitive findings. Issued reports also need a way to verify integrity and distinguish current versions from withdrawn or replaced versions. These are the motivations for the prototype, not measured findings that every existing RHU system has the same weaknesses. Relate the problem to the research questions: security and integrity, usability and efficiency, and user acceptance and trust. No controlled paper-versus-system time comparison was supplied, so do not claim a numerical efficiency improvement.

**Source:** papers.pdf, pp. 1–5, 42, 49.

## 03. Research gap

Frame the gap as a practical integration need in this study. Digitization can improve record organization, but it does not by itself provide the report-event evidence implemented here. The study brings together controlled laboratory processing, issued PDF versions and later integrity and lifecycle verification. The contribution is this integration for the stated RHU prototype setting. Avoid claiming that no prior blockchain healthcare system exists: the literature review describes several. This is a synthesis of the paper’s motivation and contribution, not a new systematic-literature-review finding.

**Source:** papers.pdf, pp. 2, 5–9, 15–16, 18–21.

## 04. Objectives

The general objective is to design, develop and evaluate the laboratory-record and blockchain verification prototype. The first evaluation objective concerns access controls, change detection and perceived security, privacy and integrity. The second concerns usability, accessibility and workflow efficiency using participant feedback and available task evidence. The third concerns acceptance, trust and willingness to adopt the system. Explain that technical observations and user perceptions answer different parts of these questions. Positive ratings alone do not establish objective security or speed.

**Source:** papers.pdf, pp. 3–4, 24–25, 48–49.

## 05. Conceptual framework

Follow the pipeline from input to verification. Patient information, requests, specimens and findings enter controlled laboratory processing. Staff validate required information and complete verification, signing and approval before the final report is released. The released PDF is fingerprinted; its digest is included in a canonical lifecycle event. The event commitment is delivered to Fabric. Verification later combines document comparison, report lifecycle and peer evidence. The diagram is the system-specific equivalent of Input → Preprocessing → Features → Model → Output; fingerprinting and blockchain rules are not learned features or a trained model. Patients and PDFs remain in private off-chain storage.

**Source:** papers.pdf, pp. 18–21, Figure 2; guide p. 1, pipeline requirement.

## 06. Dataset and participants

Separate the development examples from the user evaluation. The system demonstration uses synthetic laboratory records and sample reports; the paper does not establish a large clinical training dataset. Thirty patient respondents were recruited through convenience sampling. All eleven eligible staff participated, comprising eight laboratory staff and three IT personnel. The two role-specific questionnaires contain thirty statements each, using a five-point agreement scale. The paper provides aggregated frequency tallies, totaling 900 patient item ratings and 330 staff item ratings. Patient and staff datasets are analyzed separately. These are evaluation data, not data for training an ML classifier.

**Source:** papers.pdf, pp. 4, 21–24, 29–30, 42–44.

## 07. Laboratory system process

Explain each linked stage. Registration establishes the patient and laboratory request. Specimen handling associates the sample with the correct order. Personnel record findings, and authorized users verify results. A report snapshot then receives the required signatures and approval. Release produces the official PDF and captures a lifecycle event in the outbox. The worker subsequently delivers its commitment to Fabric. These actions are permission-controlled. Patients access eligible released reports through authenticated ownership checks; public verification returns limited information. Corrections require a new version and approval cycle rather than editing an already issued artifact.

**Source:** papers.pdf, pp. 4, 18–20, 31–36.

## 08. Preprocessing and fingerprints

Preparation validates identifiers, required fields, formats and record associations; missing clinical findings are not statistically invented. D is the SHA-256 digest of the exact released PDF bytes. The canonical event binds D to the report UUID, version, event type, occurrence time, source identity and applicable lifecycle links. Canonical serialization uses fixed formatting, so equivalent event data produce the same bytes. C is the hash of those bytes. The Fabric anchor stores C as content_hash and selected metadata; the PDF digest and report version are bound through C rather than being independent chaincode fields. This is deterministic evidence preparation, not ML feature engineering. Hashing does not encrypt data or prove clinical accuracy. For survey preparation, the paper checks item totals and records the corrected staff S16 tally.

**Source:** papers.pdf, pp. 16, 20–24; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.

## 09. Why Hyperledger Fabric?

Fabric fits the prototype’s need for identified participants, governed transactions and chaincode rules for report anchors. The contract permits authorized organizations, checks allowed event fields and rejects an existing anchor ID; lifecycle changes create additional anchors. Four peers are divided between Org1 and Org2. All four peers and a single Raft orderer share one VPS. This is logical distribution, not four independent physical fault domains or separate institutions. The topology therefore does not demonstrate resilience to complete host failure. MySQL and private PDF storage retain clinical data off-chain. The guide’s model rationale is addressed through this technology-choice explanation; no classifier is trained.

**Source:** papers.pdf, pp. 7, 17, 20–21; blockchain/chaincode/labchain-anchor/lib/anchor-contract.js; blockchain/network/config/configtx.single-vps.yaml.

## 10. Blockchain commitment process

The release transaction captures report state and its durable outbox row together. A worker validates the frozen event, checks for an existing anchor and proposes CreateAnchor through the Node.js Gateway adapter. Required organizations endorse according to the configured policy; the channel configuration requires Org1 and Org2. The orderer sequences the transaction. Peers validate endorsements and concurrency conditions, append the block and apply valid writes. The worker checks committed matching evidence before marking delivery CONFIRMED. Temporary failures receive bounded retries and uncertain acknowledgements are reconciled; conflicts or exhausted attempts remain visible for review. PENDING is not blockchain confirmation. This is configured software execution rather than model training. These implementation details explain the mechanism; they are not additional measured participant results.

**Source:** papers.pdf, pp. 18–21; docs/PHASE_8B_DELIVERY_WORKER.md; blockchain/gateway-adapter/src/adapter.js; blockchain/network/config/configtx.single-vps.yaml.

## 11. Verification and report lifecycle

QR recognition identifies the registered report. The application checks lifecycle and available historical issuer information, verifies the stored artifact and optionally compares the submitted PDF bytes with the released digest. A protected monitor retrieves report-specific evidence from four peers, including the required commitment, transaction validity, relevant block and lifecycle links. Full verification requires complete, fresh and matching evidence from every peer. A majority does not override contradictory evidence. REPORT_REVOKED and REPORT_SUPERSEDED link to the original release event; a replacement also receives its own release event. A historical report may match its original artifact while no longer being current. Four-peer report verification is separate from Fabric endorsement policy.

**Source:** papers.pdf, pp. 16, 19–21, 34, 36–42; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.

## 12. Evaluation and observed results

Describe the evaluation as expected-versus-observed scenarios. The supplied paper shows MATCH for the original PDF, MISMATCH for a changed PDF, four peers VERIFIED and PARTIAL verification with three verified peers while peer4 is offline. These correspond to Figures 4.9, 4.12 and 4.14 and Table 4.2. They are observed interface outputs under the documented conditions, not a measured accuracy rate or repeated reliability benchmark. Complete authorization test logs and controlled timing comparisons are not supplied in the paper. Do not invent accuracy, precision, recall, F1, false-positive rates or a confusion matrix. Such metrics would require a defined evaluation dataset and recorded outcomes; the system is not presented as a predictive classifier.

**Source:** papers.pdf, pp. 25–27, 37–42, Table 4.2 and Figures 4.9, 4.12, 4.14.

## 13. Interpreting verification results

MATCH means the compared bytes match the issued artifact under the checks. MISMATCH establishes different bytes, which can result from editing, resaving or another file change; it does not independently prove malicious forgery. PARTIAL means the required peer evidence is incomplete. CONFLICT means contradictory evidence prevents full verification, even if a majority agrees. The conflict rule describes implementation behavior; the paper does not supply a complete observed contradictory-hash experiment. A genuine QR copied onto altered printed content still refers to the original report and cannot authenticate surrounding printed values. The same separation applies to clinical accuracy: a matching document can faithfully reproduce an originally incorrect result. This slide satisfies interpretation and explainability through transparent verification rules, not ML feature importance.

**Source:** papers.pdf, pp. 20–21, 39–42; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md.

## 14. System output

Show the paper’s actual Figure 4.9, which uses a synthetic laboratory report. Point to the official PDF viewer on the left and the verification status on the right. The screenshot displays a registered and current report, official PDF integrity MATCH, presented-document MATCH and four individually verified peers. Explain that these are distinct checks on one screen. The screenshot is evidence of one observed successful case, not a measure of detection accuracy. In a live demonstration, show the original file first, then compare a changed file carrying the same genuine QR. Use an authorized synthetic demonstration and explain that public responses omit clinical findings. The image retains the source paper’s resolution; the caption summarizes the important result for distant viewers.

**Source:** papers.pdf, p. 37, Figure 4.9; screenshot extracted directly from the supplied paper.

## 15. Overall survey means

Give the survey thirty to forty-five seconds. Patients reported an overall mean of 4.64 out of 5; staff reported 4.62. There were thirty convenience-sampled patients and eleven eligible staff, including eight laboratory and three IT personnel. These are separate role-specific instruments, so do not treat the small difference as a statistical group comparison or combine the scores. The bar tracks run from zero to five. The section means, if asked, are patient/staff: security, privacy and integrity 4.66/4.75; usability, accessibility and efficiency 4.62/4.56; acceptance and trust 4.64/4.53. Staff results use the corrected S16 tally of four Agree and seven Strongly Agree. Favorable perceptions support user acceptance in these groups; there is no timed evidence of efficiency gains. Aggregated tallies do not support respondent-level reliability analysis.

**Source:** papers.pdf, pp. 42–44, Tables 4.3–4.4; overall means also reported on p. 48.

## 16. Study limitations

The infrastructure shares one VPS and one orderer, so it cannot demonstrate independent-host resilience. Hash comparison checks byte identity rather than the accuracy of the original laboratory measurement. The paper supplies screenshots and selected scenarios, not repeated performance or comprehensive security benchmarks. The patient sample is a convenience sample; the eleven staff form the full defined eligible staff population. The questionnaires are different by role, and only aggregate frequencies are available. Consequently, respondent-level reliability statistics and correlations cannot be calculated from these files. The study remains an academic prototype and does not establish nationwide adoption or clinical readiness.

**Source:** papers.pdf, pp. 4, 20–25, 42, 47–50.

## 17. Recommendations

Connect each recommendation to a limitation. Independent hosts and redundant ordering infrastructure would allow meaningful resilience evaluation. Record contradictory-evidence, outage and recovery behavior under defined test conditions. Document authorization denial for wrong roles and patient ownership. Compare matched paper and digital tasks with recorded completion time, errors and assistance. Where permitted, retain anonymized respondent-level responses to support reliability analysis, and evaluate laboratory and IT tasks separately. Before actual clinical use, the paper also recommends institutional authorization, privacy assessment, clinical workflow review and operational-readiness testing. These are future work, not completed evaluation claims.

**Source:** papers.pdf, pp. 49–50.

## 18. Conclusion and contribution

Close with the complete contribution: controlled laboratory processing is connected to preserved report versions and blockchain-backed evidence that another verifier can check. The documented examples show original-file matching, changed-file detection and a partial result when one peer is unavailable. Patient and staff feedback was favorable, within the sample and measurement limits. The system supports tamper-evident report verification; it does not prove clinical accuracy or absolute security. The strongest closing sentence is: RHU LabChain connects laboratory workflow to traceable reports and checkable blockchain evidence. Invite questions after this statement. No reference-only slide follows; full sources are in each slide’s speaker notes and the companion guide.

**Source:** papers.pdf, pp. 48–50; Defense_PPT-Gudelines.pdf, p. 2, contribution statement.

