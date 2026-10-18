# Workstream E: Philippine laboratory starter catalog

Workstream D was committed locally as `42b276b` (laboratory workspace and
versioned PDF presentation). Workstream E is prepared for its authorized local development commit.
No live database import, migration, deployment, or production change was performed.

## Inventory and representation

Version: `ph-rhu-starter-1`, in
`app/data/philippine_laboratory_catalog.json`.

| Category | Count | Contents |
| --- | ---: | --- |
| Departments | 5 | Hematology, Clinical Chemistry, Clinical Microscopy, Serology and Immunology, Microbiology |
| Individual tests | 39 | 15 hematology, 17 chemistry, 3 microscopy, 4 serology |
| Specimen types | 5 | Whole blood, serum, plasma, urine, stool |
| Panels | 5 | CBC, Differential Count, Lipid Profile, Liver Function Tests, Renal Function Tests |
| Proposed test/specimen links | 39 | One conservatively selected specimen per test; none marked default |
| Proposed panel/test links | 32 | Existing numeric test IDs; shared definitions, no duplicated analytes |

Hematology includes hemoglobin, hematocrit, WBC, platelets, RBC, MCV, MCH, MCHC,
RDW, five relative differential components, and ABO/Rh typing. CBC is a panel of
14 components; Differential Count reuses its five differential components.
There is no duplicate single-value CBC result masquerading as a complete panel.
Absolute differential counts would need separate approved definitions.

Chemistry includes fasting/random glucose, HbA1c, four lipid measurements,
creatinine, BUN, uric acid, ALT/SGPT, AST/SGOT, alkaline phosphatase, albumin,
total protein, total and direct bilirubin. LDL is a recorded result; no LDL
calculation is introduced. The renal grouping contains only creatinine and BUN;
it does not imply electrolyte testing or an eGFR calculation. Panel composition
is a starter proposal, not a universal diagnostic panel.

Microscopy includes routine urinalysis, stool examination and urine pregnancy.
Urinalysis and stool examination are **TEXT summary definitions**, using the
existing 100-character result field and separate remarks. They are not structured
multi-analyte reports. Before activation, the facility must approve complete
reporting of required findings or configure component tests and a panel using
existing administration. Required findings must never be squeezed out of a summary.

Serology includes HBsAg, dengue NS1, IgM and IgG as separate qualitative results.
The manifest explicitly flags the limitations of a single IgG result for acute
dengue diagnosis. No diagnostic inference or treatment recommendation is seeded.

Microbiology is an inactive category only: no unsupported microbiology assay is
invented. Plasma is an inactive specimen type available for local configuration;
no starter assay is assigned plasma without confirmation of its method-specific
additive/processing requirements. Whole blood is distinct from anticoagulant,
container, collection volume, handling and stability. Those are not automatically
inferred from the specimen name.

## Clinical provenance and review

Each test references source IDs and has review and reference-applicability notes.
The source registry contains direct primary-source URLs:

- [DOH Don Jose S. Monfort Medical Center laboratory services](https://djsmmc.doh.gov.ph/laboratory-pricelist/)
  provides Philippine service examples. Hospital offerings are not an RHU license
  or proof of this facility's equipment, staff or reagent capability.
- [Mayo CBC specification](https://www.mayocliniclabs.com/test-catalog/overview/9109),
  [HbA1c specification](https://www.mayocliniclabs.com/api/sitecore/testcatalog/TestCatalogSetupPDF?testid=82080),
  [serum chemistry panel](https://www.mayocliniclabs.com/test-catalog/overview/113631),
  [lipid testing](https://news.mayocliniclabs.com/2024/10/23/dr-leslie-donato-discusses-lipid-testing-on-adlms-laborastories-the-podcast/),
  [uric acid](https://www.mayocliniclabs.com/test-catalog/Overview/8440), and
  [Labcorp bilirubin](https://www.labcorp.com/tests/001214/bilirubin-total-and-direct?letter=L)
  support analyte/specimen examples; their numerical ranges and methods are not
  copied into the facility's clinical configuration.
- [Cleveland Clinic ABO/Rh](https://clevelandcliniclabs.com/test/abo-rh-typing/),
  [Mayo urinalysis](https://www.mayoclinic.org/tests-procedures/urinalysis/about/pac-20384907),
  [Mayo HBsAg](https://gi.testcatalog.org/show/HBAG),
  [CDC NS1 testing](https://www.cdc.gov/dengue/hcp/diagnosis-testing/dengue-virus-antigen-detection.html),
  and [CDC dengue serology](https://www.cdc.gov/dengue/hcp/diagnosis-testing/serologic-tests-for-dengue-virus.html)
  support specimen/assay distinctions and review cautions.

Sources reviewed during development on 18 October 2026. They establish examples
of test definitions and specimen suitability, **not validation of a local assay**.
No reference intervals, critical thresholds, qualitative normal values, diagnostic
interpretation rules, stability limits, prices or methodology are imported.
Units also remain NULL until facility review; numeric/qualitative result types
are proposed representations and must match the selected validated assay.
Classification uses the existing department and result-type fields; no unsupported
accreditation, LOINC or clinical classification is invented.

## Preview, approval and import

1. An authorized staff member opens **Laboratory setup → Preview starter catalog**.
   GET `/api/v1/lab/starter-catalog` only reads configuration. It displays the
   inventory, every proposed entry, specimen/panel relationships, source links,
   clinical review notes, existing codes and mapping conflicts.
2. Review local synonyms and existing aggregate tests. Resolve conflicts through
   the normal authorized catalog process without deleting historical records.
   Confirm whether preserved existing configurations are suitable for new panels.
3. A staff member with **all** of LAB_MASTER_READ, LAB_DEPARTMENT_MANAGE,
   SAMPLE_TYPE_MANAGE, TEST_CATALOG_MANAGE and TEST_PANEL_MANAGE acknowledges the
   inactive-review requirement and selects **Import inactive starter entries**.
   Existing SYSTEM_ADMIN permission semantics apply; patient-linked identities
   and PATIENT roles are explicitly excluded even with elevated permissions.
4. POST `/api/v1/lab/starter-catalog` accepts only the preview fingerprint and
   `acknowledge_inactive_review: true`. Authentication and CSRF remain mandatory.
   It does not accept client codes, clinical values, active flags or arbitrary data.
5. The server locks the relevant code-sequence rows in a consistent order,
   performs current locking configuration reads, validates the complete plan,
   and checks the fingerprint before creating anything. DEP/TST/PNL values come
   from `allocate_code()`. New departments, specimens, tests and panels are all
   inactive. Each creation has a minimal STARTER_CATALOG_CREATE audit event.
   All records, associations, audit writes and counters commit together; failure
   rolls back the entire attempt. Existing deadlock retry policy is reused.
6. The response displays actual generated identifiers. The UI discards a failed
   or completed preview; any retry requires a new preview. No startup seed,
   background import, database URL, command-line credential flow or deployment
   hook is introduced. This endpoint is not called during this development task.

### Matching and preservation policy

- Match only names and manifest aliases after case folding, Unicode normalization,
  accent removal and whitespace normalization. These are conservative duplicate
  checks, not universal medical synonym resolution.
- Multiple candidates, a different department/result type, or an individual/panel
  aggregate name collision block the entire import. No guessing by code or ID.
- A single compatible match is preserved in full: identifiers, names, units,
  methods, activity, reference ranges, sample links and panel memberships. The
  preview's proposed composition is **not** applied to an existing panel.
- Repeating an unchanged import creates nothing and consumes no counters or new
  creation audit events. A stale preview is refused.
- Existing creation audit evidence prevents silently duplicating a previously
  imported entry that was renamed, removed or mapped to another record. Such
  cases require manual reconciliation; the audit event is never used to overwrite
  or recreate clinical data. Preserve these audit events with normal audit history.
- Unknown local synonyms cannot be inferred safely: administrators must review
  the preview and maintain aliases through version-controlled review. If old
  import evidence has been archived away, name/alias matching is the remaining
  guard. This is not a bulk reconciliation or deletion tool.

### Clinical enablement procedure

The importer does not approve clinical use. Qualified laboratory personnel must
verify the facility's licensed scope, equipment/reagents/personnel, validated
method and specimen SOP; choose units and result format; review age/sex/date
applicability, numeric/qualitative references and critical thresholds where
applicable; and approve every panel member and required reporting field.
Record this approval in the facility's established quality-management process.
There is no new accreditation or electronic clinical-approval record model.

Use existing administration to activate the approved department and specimen types,
configure test metadata, sample mappings and references, activate reviewed tests,
and finally review/activate panels. Sample and panel editors include inactive
entries for configuration; operational order lookups continue to offer active
entries. The backend still rejects inactive tests/panels when creating orders.
Use the existing Active checkbox to retire unsupported services; existing reports,
results, codes, patient links, audit events and blockchain records are preserved.

## Existing workspace integration

Tests and panels can be filtered by department (including inactive departments),
activity and existing search; test search includes generated code/name. Department
lookups are paginated/searchable through existing endpoints. Detail screens expose
stored specimen guidance and existing reference/interpretation editors, with
clinical-review guidance. Panel editors reuse the same TestCatalog records.

No order, specimen, result, signing, approval, release or PDF implementation is
changed. The synthetic integration test imports inactive entries, verifies order
rejection, explicitly configures/activates selected entries through authorized
APIs, orders a panel and individual tests, collects/receives appropriate specimens,
enters/verifies numeric and qualitative results, generates/signs/approves/releases
PDF v2, and confirms later catalog retirement does not change snapshots or PDF bytes.
Synthetic units/ranges used in tests are deliberately not clinical catalog data.

## Schema and release prerequisites

**No Workstream E migration is required.** This uses the existing laboratory,
association, sequence and audit tables. Workstream D migration `20261018_01`
remains unapplied in development/production MySQL; its separately authorized
migration rehearsal and deployment prerequisite remain. Workstream A's remaining
native migration verification gate also remains. No live MySQL or Fabric probe
was run for E. The bulk import transaction itself should be rehearsed in an
isolated MySQL environment before production use; this task validates it offline
using existing SQLite fixtures and preserves the allocator's MySQL locking path.

## Files

- `app/data/philippine_laboratory_catalog.json`: versioned starter definitions and sources.
- `app/services/starter_catalog_service.py`: manifest validation, preview, matching,
  conflict checks, idempotency and atomic import.
- `app/api/laboratory.py`: private preview/confirmed-import endpoints using existing permissions.
- `frontend/src/components/StarterCatalog.tsx`: preview/review/import states and source detail.
- `frontend/src/pages/Laboratory.tsx`: integration, clinical review and specimen guidance;
  inactive entries available in administrative association editors.
- `frontend/src/pages/ResourcePage.tsx`, `resources.ts`: reusable lookup filters and
  department browsing; existing immutable codes remain excluded from form fields.
- `tests/test_starter_catalog.py`: offline import, preservation, rollback, permissions,
  clinical defaults, history and workflow-to-PDF tests.
- `tests/test_phase_3c_laboratory.py`: exact API inventory includes the two protected
  starter operations; all prior route/security assertions retained.
- `frontend/src/test/starter-catalog.test.tsx`: administration, errors, permissions,
  generated-code display and immutable-code request coverage.
- This document: inventory, clinical boundaries, sources, approval and release procedure.

## Focused validation

```bash
.venv/bin/python -m pytest tests/test_starter_catalog.py tests/test_phase_3c_laboratory.py tests/test_phase_4a_workflow.py tests/test_report_pdf_v2.py tests/test_auto_code_generation.py tests/test_auto_code_master_schemas.py -q -ra --tb=short --maxfail=3
```

Inside `frontend`:

```bash
npm run test -- --run src/test/starter-catalog.test.tsx src/test/workflows.test.tsx src/test/laboratory-workspace.test.tsx
npm run build
```

Node v24.21.0 and npm 11.19.0 use the existing installed, locked dependencies.
No dependency versions or lockfiles changed. No complete backend run was requested.
Completed validation: **364 distinct focused backend tests passed** across the
main run and targeted rerun (including 28 new catalog tests). The main run had
363 passes and one outdated exact API-operation-count assertion; its corrected
34-operation assertion and explicit starter GET/POST inventory passed separately.
No remaining failures or skips are known in this selection.

**65 distinct frontend tests passed** across the focused runs (13 new catalog
cases, 38 existing workflow cases and 14 laboratory workspace cases). The initial
new department-filter test used the wrong existing label; corrected to Activity.
Final TypeScript and Vite builds passed. Python syntax and `git diff --check`
passed. Two existing Starlette/httpx/AnyIO deprecation warnings remain.

No implementation blocker remains. Facility clinical approval and the separately
authorized release/migration rehearsals above remain prerequisites for operational
use. The complete backend/frontend suites and native MySQL/Fabric probes were not
rerun. Production remains unchanged. This validation record predates the final integrated release review.
