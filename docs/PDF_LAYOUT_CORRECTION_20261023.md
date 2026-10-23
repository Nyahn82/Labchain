# Laboratory PDF spacing correction — 23 October 2026

The existing renderer follows the corrected `pdf/RHU_LabChain_Report_Layout_Fixed.pdf` reference without copying its illustrative data or preview-only wording.

- Removed forced bottom positioning: authorized signatories now follow the report notes with a small, fixed gap.
- Centered a single signatory across the full report width. Multiple signatories retain two columns and can continue across pages.
- Standardized table cell padding, aligned flag/result headings with their values, and widened the flag column so `NORMAL` does not wrap unnecessarily.
- Aligned timeline and specimen columns, with light backgrounds for dates, specimen details and remarks.
- Reduced the footer from a full-width 40-point band to a 22-point strip within the report margins. Adjusted the bottom margin while preserving space between report content and footer.
- Kept short reports and ten-test panels on one A4 page. A 65-test example uses three pages, with repeated result headings and page numbers.

Only the existing PDF renderer changes application behavior. No fields, database schema, business rules, frontend, QR payload, signing identity, report data, release/hash logic, or blockchain integration were changed. Existing stored reports are never regenerated or replaced.

## Visual evidence

The shared synthetic review artifacts are updated to the corrected layout:

- [Short synthetic PDF](screenshots/pdf-layout-20261023/synthetic-short.pdf) and [image](screenshots/pdf-layout-20261023/short.png).
- [Ten-test panel](screenshots/pdf-layout-20261023/panel.png).
- [Multipage continuation](screenshots/pdf-layout-20261023/continuation.png).

These are documentation examples, not released clinical PDFs. Their synthetic verification URL uses `example.test` and does not identify a live report. Short, panel and continuation output was rasterized and visually inspected. The functional QR decoded correctly from generated PDF pixels at two resolutions.

## Verification

The layout regression now checks that a single signatory is centered and follows remarks without a stretched gap. Existing tests also cover long notes without overlap/clipping, captured logos, mixed specimens, large signatory lists, and unchanged historical download/print bytes.

A separate isolated API acceptance generates, signs, approves and releases a report, decodes its final PDF QR, compares the official download bytes, checks the SHA-256 digest and public PDF comparison, and confirms the release outbox contains the PDF hash.

Final focused regression: **198 passed**, one optional browser-fixture export skipped. Additional isolated release/QR/hash acceptance: **1 passed**. The final renderer was visually inspected with short, full ten-test and multipage examples. Deployment acceptance is recorded below after completion. Protected source and existing-PDF backups and read-only integrity baselines are under `/var/backups/rhu-labchain/20261023-pdf-layout-fixed`.
