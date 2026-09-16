# Phase 5B — report release and verification

Released PDFs are immutable. The QR does not contain medical information. The
public verification endpoint does not expose medical information. Blockchain
registration is NOT implemented in Phase 5B.

No database migration, schema alteration, blockchain event, frontend portal, email
delivery or clinical result correction workflow is introduced. The existing
`lab_report`, snapshot, signatory, `report_verification`, `print_log` and
`audit_log` tables are reused.

## Configuration and dependencies

Settings use the existing Pydantic environment configuration. Process environment
overrides `.env`. `.env.example` documents:

```dotenv
REPORT_STORAGE_DIR=/var/lib/rhu-labchain/reports
PUBLIC_BASE_URL=https://labchain.online
# Optional administrator-managed signatures:
# REPORT_SIGNATURE_DIR=/var/lib/rhu-labchain/signatures
```

Storage and the public origin have no implicit production defaults. Existing
application startup remains possible without them, but release fails with a
controlled 503 until configured. Paths must be absolute and outside `frontend/`.
The public URL must be an origin without credentials, path, query or fragment;
production requires HTTPS. Keep this origin stable: existing QR URLs are embedded
in immutable PDFs. Metadata URLs are composed from the current configured origin.

Pinned dependencies are `reportlab==5.0.1`, `qrcode==8.2`, `Pillow==12.3.0`, and
ReportLab's `charset-normalizer==3.5.1`. `pypdf==6.8.0` supports artifact assertions
in the existing combined runtime/test requirements file. No browser renderer is
installed. Upstream: [ReportLab](https://pypi.org/project/reportlab/5.0.1/),
[qrcode](https://pypi.org/project/qrcode/8.2/).

## Artifact storage and filesystem safety

The administrator creates the private storage root, owned by the existing
`rhuadmin` service identity with mode 0700. The service creates private year
subdirectories; PDF paths stored in MySQL are relative, for example
`released/2026/123-<random-32-hex-characters>.pdf`. Filenames use a server-owned
report ID and independent randomness, never patient details or a client path.
The entire directory must stay outside all Nginx aliases/document roots. Neither
FastAPI static mounts nor Nginx configuration is changed by this phase.

Path resolution rejects absolute paths, traversal, backslashes and symlinks.
Reads require a regular file, use `O_NOFOLLOW`, and never fetch a URL. The
configured root and all its parent directories must be controlled by the service
administrator; filesystem access by another administrator is outside the
application authorization boundary. Final files are mode 0400. This prevents
accidental writes but is not a WORM filesystem: an administrator or service owner
can still replace files, which integrity checking detects.

PDFs are generated in memory, written to a private temporary file in the final
directory, flushed and fsynced. An atomic hard link publishes the final filename
on the same local filesystem. Unlike an overwriting rename, this refuses any
existing destination. The temporary link is removed and the directory is fsynced.
Only then are the verification, release, supersession and audit rows committed.
Use a local filesystem supporting hard links and directory fsync.

On ordinary transaction failure the newly published file is removed. Cleanup
failure logs a generic operational error. A lost database COMMIT acknowledgement
has an uncertain outcome: the file is deliberately retained for reconciliation,
because deleting it could break an already committed release. Process crashes
can also leave temporary files or unreferenced final PDFs. Database/filesystem
atomicity cannot be guaranteed across crashes, power loss, independent restores
or hardware failure. No response claims success before database commit.

For reconciliation, pause report writes operationally, compare private files
against all `lab_report.pdf_path` references, and investigate uncertain commits
before removing anything. Never delete a referenced historical PDF. There is no
automatic orphan-deletion job in this phase. Back up MySQL and report storage as a
consistent pair; restore the original released bytes instead of regenerating.

## PDF layout and sources

`report_pdf.py` uses ReportLab Platypus on A4 paper: grayscale facility header,
report/version and UTC generation/release timestamps, patient and requesting
physician snapshots, section headings, aligned TEST/FLAG/RESULT/UNIT/REFERENCE
RANGE columns, assigned signatories, QR, template notes and page-number footer.
Abnormal flags and values use bold type and retain their textual flags. Long
reports paginate with repeated result table headers. The renderer preserves the
query's `sort_order, report_result_item_id` ordering; it does not re-sort tests.

Clinical and patient content comes exclusively from `report_patient_snapshot`
and `report_result_item`. Current live patient/catalog values cannot rewrite an
approved report's snapshot content. Facility identity/contact details and staff
printable names are read at release, then frozen in PDF bytes. Template display
fields and signatory profile display fields retain Phase 5A historical mutation
protection. All five configured template text fields are rendered. Phase 5A's
nullable template remains supported as a generic laboratory report; if a template
is selected it must exist, remain active and match an included panel when scoped.

All caller-controlled text is XML-escaped before passing to ReportLab paragraphs;
markup-like text prints literally. No HTML template engine, executable expression,
remote image, remote font or arbitrary file reference is interpreted. ReportLab's
bundled Bitstream Vera regular/bold TrueType fonts avoid operating-system font
dependencies and support Latin accents. Full CJK/other script coverage is a future
font configuration concern; validate names requiring other scripts before use.

Optional signature images are local PNG/JPEG files under `REPORT_SIGNATURE_DIR`.
`signatory.signature_image_path` must be relative to that root (for example
`technologist.png`); absolute legacy paths, traversal, symlinks, URLs, missing,
invalid and oversized images are omitted. There is no signature upload endpoint.
Signatory name, type and license still print if the image is omitted. Facility
logo paths are not interpreted by this generic renderer.

## Lifecycle, locking and integrity

`GENERATED -> APPROVED -> RELEASED -> REVOKED` remains the lifecycle. Release is
not idempotent: another request after successful release returns 409 and never
renders or overwrites that PDF. Direct GENERATED or REVOKED release is rejected.

Release locks the parent order then all its report versions using current
InnoDB locking reads, coordinating with Phase 5A generation/approval. It checks
approval provenance, absence of existing release/revocation metadata and
verification rows, patient/result snapshots, at least one assigned signatory,
all assignments signed, completed order and current VERIFIED source provenance,
issuing facility, selected template, storage and public URL settings. The source
result IDs must exactly cover the report snapshots. Rendering does not use live
clinical values. Application services permit one active verification per report;
no new uniqueness constraint is added. The existing token UNIQUE constraint is
the final collision guard; a collision rolls back release and cleans its artifact.

Each release calls `secrets.token_urlsafe(32)` (256 random bits, 43 URL-safe
characters, within the existing 120-character column). QR content is exactly:

```text
{PUBLIC_BASE_URL}/api/v1/verify/{opaque_token}
```

No patient name, code, result, hash, report/order ID or authentication credential
is in that payload. QR generation uses qrcode with a four-module quiet zone and
medium error correction. Verification is a possession-of-token lookup, not a
patient-ownership or login mechanism. MySQL's case-insensitive collation is
countered by an exact constant-time token comparison after lookup.

After rendering the final QR-bearing PDF, SHA-256 of those exact bytes is stored
as 64 lowercase hexadecimal characters in `report_verification.report_hash`.
The verification starts AUTHENTIC with the release timestamp and no revocation
time. Release sets only release lifecycle fields; generation/approval provenance
is retained. No `blockchain_event` is populated.

## Routes and permissions

All routes use `/api/v1`. The six staff routes use existing sessions and RBAC;
unsafe POSTs require the existing CSRF header. SYSTEM_ADMIN retains its existing
superuser permission behavior. Bootstrap adds the five new permission codes
idempotently without assigning them to roles or seeding through Alembic.

| Method and route | Permission | Behavior |
| --- | --- | --- |
| POST `/reports/{id}/release` | REPORT_RELEASE | Release approved report; return report detail |
| GET `/reports/{id}/pdf` | REPORT_DOWNLOAD | Stream validated final PDF |
| POST `/reports/{id}/print` | REPORT_PRINT | Log print request and stream PDF |
| GET `/reports/{id}/verification` | REPORT_READ | State, dates, SHA-256 and QR URL |
| POST `/reports/{id}/revoke` | REPORT_REVOKE | Require reason and revoke released report |
| POST `/reports/{id}/revise` | REPORT_REVISE | Create GENERATED successor; return 201 |
| GET `/verify/{token}` | Public | Redacted verification only |

Downloads and printing allow RELEASED and REVOKED historical reports and check
SHA-256 before streaming. They stream the same validated bytes from memory,
avoiding a second filesystem read between checking and delivery. Content-Type is
`application/pdf`, Content-Disposition is an attachment with a server-owned safe
filename, and Cache-Control is `no-store`. Missing, unreadable, unsafe or altered
artifacts return a controlled 409; a privacy-safe integrity audit is committed
before that error is returned. There is no public PDF endpoint.

Print requests accept `{"copies": 1}` with strict integer bounds 1–20. Every
successful request appends its own `print_log` row and REPORT_PRINT audit, even
when repeated. No cumulative counter is changed. This records a print request,
not proof that a physical printer completed it. The client controls its print UI.

## Public verification

No session or CSRF token is required. Every response is `no-store`. A successful
lookup returns only status, issuing facility name, release date, version and a
fixed explanatory message. No report reference/internal ID is exposed.

* VERIFIED: AUTHENTIC released artifact exists and current SHA-256 matches using
  `hmac.compare_digest`.
* REVOKED: report or verification is revoked, even if the file is missing or its
  historical bytes remain on disk.
* ALTERED: the active released artifact mismatches or cannot safely be read.
  Missing storage and missing files intentionally have the same public policy.
* NOT_FOUND: neutral 200 response for invalid, unknown or unavailable tokens,
  without revealing whether a patient, order or internal report exists.

The endpoint checks the stored server artifact, not an arbitrary uploaded PDF
or the content surrounding a QR printed on another document. Copying a valid QR
onto different paper cannot be detected from the QR alone. SHA-256 provides
artifact integrity against the trusted database record; this is not a digital
signature or an independent blockchain attestation. The public route does not
return the artifact hash or PDF. Public checks perform file I/O and hashing;
rate limiting and large-artifact streaming optimizations are not added here.

## Revocation, revisions and supersession

Revocation requires a nonblank reason (maximum 16,000 characters) and RELEASED
state with one active verification. It atomically sets report revocation user,
time/reason and verification status/time. Repeated revocation returns 409. PDFs,
verification rows and snapshots are never deleted or modified by revocation.

Revision accepts a RELEASED or REVOKED source and optional template/remarks.
Omitting template_id retains the source template; explicit null requests the
generic report. Current issuing facility policy is reused. Under the order lock,
current report rows determine `max(version_no) + 1`, protecting against concurrent
duplicate versions even with MySQL REPEATABLE READ and older session snapshots.
The new row points to `supersedes_report_id`, starts GENERATED, and has fresh
patient/result snapshots from the shared Phase 5A builder. It has no inherited
signatures, approval, PDF or verification: signatories must be assigned and sign
again. The old version is unchanged when its successor is generated or approved.

Releasing a successor revokes its specified predecessor if still RELEASED in the
same transaction, with `Superseded by report <new report_code>` as the reason and
the new release time as the old revocation time. A predecessor already REVOKED
retains its original revocation event. V1 QR then says REVOKED while V2 says
VERIFIED; authorized staff retain V1 PDF access. Competing branches may be
GENERATED with distinct versions, but a stale branch cannot release over another
already released successor. Revise the current release for further corrections.

Order report lists include all versions in **version_no descending** order,
with report_id as a tie-breaker; global report lists retain report_id descending.
Responses include existing version/supersedes fields plus verification_status
and is_current_released (highest RELEASED version for the order). Revoked history
is not filtered out unless the caller explicitly supplies a status filter.

**Clinical correction limitation:** verified `lab_result_item` values remain
immutable, with one current result per order item. Report revision handles report
configuration, template/layout, supported administrative metadata and reissuance
of currently verified results. Correcting an already verified laboratory value
requires a future controlled result correction/repeat/amendment workflow. This
phase does not create one or weaken VERIFIED immutability.

## Audit events

REPORT_RELEASE, REPORT_DOWNLOAD, REPORT_PRINT, REPORT_REVOKE, REPORT_REVISE,
REPORT_SUPERSEDE and REPORT_INTEGRITY_MISMATCH use the existing AUDIT_LOG. Integrity
failures have JSON severity HIGH and a fixed failure code. Other audit metadata
contains only lifecycle state, report/version references and print counts.
Reasons remain on lab_report and are not duplicated in audit JSON because they
can contain sensitive free text. PDF bytes, clinical values, patient names,
verification tokens and session credentials are not written into these events.
No audit schema severity column is added.

## Hostinger deployment (operator commands; not executed by development)

Run from the existing deployed checkout as `rhuadmin` after transferring/reviewing
the Phase 5B code. Stop on any error. These steps use the existing service and
ports; do not edit Nginx, Certbot, UFW or the systemd unit.

```bash
cd /opt/rhu-labchain
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
sudo install -d -o rhuadmin -g rhuadmin -m 0700 /var/lib/rhu-labchain/reports
sudo -u rhuadmin test -r /var/lib/rhu-labchain/reports
sudo -u rhuadmin test -w /var/lib/rhu-labchain/reports
```

The operator must set the following two entries in the existing private `.env`
using the server's secure editor, preserving every existing setting. Development
did not edit or commit production `.env`.

```dotenv
REPORT_STORAGE_DIR=/var/lib/rhu-labchain/reports
PUBLIC_BASE_URL=https://labchain.online
```

Optional signature setup, only if images will be used:

```bash
sudo install -d -o rhuadmin -g rhuadmin -m 0700 /var/lib/rhu-labchain/signatures
# Copy approved PNG/JPEG files into this directory with owner rhuadmin and mode 0600.
```

Then set `REPORT_SIGNATURE_DIR=/var/lib/rhu-labchain/signatures` and use relative
image filenames in signatory profiles. Do not publish this directory via Nginx.

Validate code and add permission metadata:

```bash
cd /opt/rhu-labchain
. .venv/bin/activate
python -m pytest -vv -ra --tb=long
python -m alembic heads
python -m app.cli.bootstrap_permissions
```

The expected existing head is `20260915_01`. **No `alembic upgrade` is needed for
Phase 5B**, because no migration exists. Grant the five new permissions to the
appropriate staff roles using the existing authorized administration APIs;
bootstrap intentionally does not make this policy decision.

After tests/configuration succeed, activate the code using the existing unit:

```bash
sudo systemctl restart rhu-labchain-node1.service
systemctl is-active rhu-labchain-node1.service
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/ready
curl --fail --silent --show-error https://labchain.online/api/v1/health
curl --fail --silent --show-error https://labchain.online/api/v1/verify/invalid-synthetic-token
```

The final request must return the neutral NOT_FOUND response. A release smoke test
must use an authorized synthetic report on a staging database, never fabricated
patient results in the live clinical database. Existing production service,
permissions and storage were not mutated during this implementation.

## Synthetic API examples

These examples target a staging origin. `synthetic.cookies` contains a staging
staff session obtained through the existing login flow; `SYNTHETIC_CSRF` is that
session's CSRF cookie value. Never copy production credentials into documentation.
Report 101 is assumed already generated, signed and approved.

```bash
STAGING_ORIGIN=https://staging.example.test
curl --fail-with-body -b synthetic.cookies -H "X-CSRF-Token: $SYNTHETIC_CSRF" \
  -X POST "$STAGING_ORIGIN/api/v1/reports/101/release"
curl --fail-with-body -b synthetic.cookies \
  "$STAGING_ORIGIN/api/v1/reports/101/pdf" -o synthetic-report.pdf
curl --fail-with-body -b synthetic.cookies -H "X-CSRF-Token: $SYNTHETIC_CSRF" \
  -H 'Content-Type: application/json' -d '{"copies":2}' \
  "$STAGING_ORIGIN/api/v1/reports/101/print" -o synthetic-print.pdf
curl --fail-with-body -b synthetic.cookies \
  "$STAGING_ORIGIN/api/v1/reports/101/verification"
curl --fail-with-body "$STAGING_ORIGIN/api/v1/verify/OPAQUE_TOKEN_FROM_STAGING_METADATA"
curl --fail-with-body -b synthetic.cookies -H "X-CSRF-Token: $SYNTHETIC_CSRF" \
  -H 'Content-Type: application/json' \
  -d '{"template_id":2,"remarks":"Administrative corrected version"}' \
  "$STAGING_ORIGIN/api/v1/reports/101/revise"
# Assign/sign/approve the new report using existing Phase 5A routes, then release it.
# To revoke independently instead:
curl --fail-with-body -b synthetic.cookies -H "X-CSRF-Token: $SYNTHETIC_CSRF" \
  -H 'Content-Type: application/json' -d '{"reason":"Administrative revocation"}' \
  "$STAGING_ORIGIN/api/v1/reports/101/revoke"
```

## Validation

Final validation on 2026-09-16: **925 passed, 0 failed, 0 skipped**, with two
existing Starlette/httpx/AnyIO deprecation warnings, in 789.74 seconds. This
includes 70 Phase 5B test cases and all seven new isolated MySQL scenarios.
`pip check` passed; Alembic reports one unchanged head, `20260915_01`. No model
or migration files were changed.

Run the entire suite with `python -m pytest -vv -ra --tb=long`. Synthetic SQLite
API tests cover permission/CSRF behavior, PDFs parsed with pypdf, multipage
headers/order, QR pixels/payload, safe text/signatures, lifecycle, hashing,
revocation, refreshed snapshots, failure rollback and audit privacy. Isolated
MySQL processes use disposable `/tmp` data directories and Unix sockets with
networking disabled. They cover double release, concurrent version generation,
supersession, database-failure rollback, stale reads, token collation and competing
branches. A rendered synthetic PDF was also visually inspected and its QR decoded
with independent temporary inspection tools, matching the database token exactly.
Existing Phase 2–5A, health, readiness, OpenAPI and frozen migration
tests remain in the full suite. Phase 6 is not started.
