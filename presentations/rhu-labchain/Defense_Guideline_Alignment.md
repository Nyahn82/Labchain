# Revised defense presentation — guideline alignment

Deliverable: `RHU_LabChain_Defense_Revised.pptx`, with a matching PDF companion and speaker notes. The original presentation is preserved.

## Format and delivery

- 18 slides, within the recommended 12–18 and maximum 20.
- Main title: 42 pt. Slide titles: 36 pt. Title-slide brand heading: 30 pt.
- Body and diagram labels: 24–26 pt. Survey metric labels: 22 pt.
- Maximum six authored text lines per slide, including the title; maximum eight words per line. Short diagram labels can contain fewer than six words.
- Citations and detailed explanations are in speaker notes instead of small footnotes.
- Original interface screenshot on slide 14 retains the paper’s embedded UI text and source resolution; the font/line checks apply to authored slide text, not text inside this source image.
- Native editable process diagrams, a topology diagram, a zero-baseline survey bar chart, and an original system screenshot are included. The survey bar tracks represent 0–5.
- At 45–60 seconds per slide, allow approximately 13.5–18 minutes, plus questions. Actual timing requires rehearsal.
- The closing slide states the contribution. References are available in speaker notes rather than following the conclusion.

## Required content mapping

| Guide section | Revised slide(s) | Treatment |
|---|---|---|
| Title | 1 | Official study title and setting |
| Problem statement | 2 | Record handling, integrity, privacy and report versions |
| Research gap | 3 | Practical integration need, without an unsupported novelty claim |
| Objectives | 4 | Development and the paper’s three evaluation areas |
| Conceptual framework | 5 | Input → validation → fingerprinting → anchoring → verification |
| Dataset | 6 | Synthetic examples, patient sample, staff census and instruments |
| Preprocessing | 8 | Record validation and deterministic canonical event preparation |
| Feature engineering | 8 | System-specific equivalent: PDF digest and event commitment |
| Model and rationale | 9 | Hyperledger Fabric choice and permissioned architecture |
| Training | 10 and notes | System-specific equivalent: configured execution and transaction flow; no ML training is claimed |
| Evaluation metrics | 12, 15 and notes | Expected/observed verification scenarios and descriptive survey means |
| Results | 12, 14–15 | Documented technical outcomes and concise survey chart |
| Explainability | 13 | Interpretation of verification statuses and their limits |
| System output | 14 | Figure 4.9 from the supplied paper |
| Conclusion | 18 | Controlled workflows, traceable versions and checkable evidence |
| Recommendations | 17 | Infrastructure, testing and evaluation improvements |

Slide 7 retains the end-to-end laboratory process; slide 11 explains report verification and lifecycle; slide 16 states study limitations.

## Scope of the adaptation

The supplied guide is written for machine-learning projects. This study is a blockchain system-development project. HOG/GLCM/LBP features, classifier training, feature-importance plots, accuracy/precision/recall/F1 and a confusion matrix would require methods and evaluation data that the paper does not supply. They have not been invented. The revised deck uses the applicable system equivalents above; adviser acceptance of this adaptation remains an academic decision, not something the presentation can guarantee.

The paper’s observed results are kept separate from implementation explanations. In particular, conflict handling is explained as a verification rule, not claimed as an observed conflict experiment in the paper. No timing gains, clinical correctness or independent-host resilience are claimed.

## Sources

- `/opt/rhu-labchain/pdf/Defense_PPT-Gudelines.pdf`
- `/opt/rhu-labchain/pdf/papers.pdf`
- Local source and project documentation named in each slide’s notes, used to clarify transaction delivery and verification rules.

## Validation

The builder checks authored line counts, words per line, font sizes and text-box boundaries. `Defense_Revised_Layout_Checks.json` records the per-slide results. The PPTX package and embedded notes are checked after generation; the companion PDF is rendered for visual review. These checks are not a live Microsoft PowerPoint rendering test.
