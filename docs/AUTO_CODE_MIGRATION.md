# Automatic-code migration safety and rehearsal

Revision `20261015_01` follows `20261005_01` and is not yet deployed. It creates
`code_sequence` and initializes Patient, Staff, Department, Test, Panel, Rejection
Reason and Report Template counters. It never updates existing identifiers,
records, report snapshots, relationships or uniqueness constraints. Allocation
formats and the allocator's transaction behavior are unchanged.

## Operational prerequisites and fail-closed behavior

Use MySQL 8.0.16+ with enforced CHECK constraints and accessible column/collation
metadata. Before an actual upgrade, stop or fence **all** application, CLI,
import and independent writers to the seven source tables and keep them fenced
until the complete migration and validation finish. The preflight scans are not
locks protecting against concurrent historical inserts. An old writer must not
insert a new code between scanning and enabling the new application.

The MySQL upgrade refuses before any scan or DDL unless
`RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED=1` is supplied explicitly for that
migration process. This is an operator acknowledgement, not a mechanism that
stops writers or proves they are fenced. Do not set it globally or use it to
bypass the prerequisite. SQLite fixtures do not require this operational flag.
A later authorized command can prefix the normal Alembic invocation with this
variable only after writer exclusion has been verified. This document is not
authorization to connect to a database, migrate or stop services.

Readiness also requires the separately authorized isolated MySQL rehearsal below.
Do not deploy this revision solely on the basis of SQLite or scripted-server tests.

## Effective column collation policy

For each of the seven identifier columns, the MySQL preflight reads
`information_schema.COLUMNS` joined to `information_schema.COLLATIONS` using the
selected database, exact table and exact column. It reads CHARACTER_SET_NAME,
COLLATION_NAME, CHARACTER_MAXIMUM_LENGTH and PAD_ATTRIBUTE. It does not substitute
the database default for a column override.

Supported untailored utf8mb4 collations are:

- `utf8mb4_general_ci`, `utf8mb4_unicode_ci`, `utf8mb4_unicode_520_ci`
- `utf8mb4_bin`, `utf8mb4_0900_bin`
- `utf8mb4_0900_ai_ci`, `utf8mb4_0900_as_ci`, `utf8mb4_0900_as_cs`

These collations preserve ASCII decimal lexical order. Printable ASCII cannot
expand/contract into a different generated-code spelling beyond letter case and
the declared trailing-space rule. The preflight uses that restricted property;
it does not claim to model arbitrary Unicode weights in Python. Unsupported,
missing, locale-tailored or inconclusive metadata fails before CREATE TABLE.
Supporting another collation requires review and isolated tests; do not change an
existing column's collation merely to bypass this guard.

Every historical value is scanned, without a SQL LIKE prefilter. Equality under
MySQL uniqueness rules can differ from LIKE for Unicode expansions or ignorable
characters. The policy is:

1. ASCII prefixes with ASCII numeric suffixes, including lowercase prefixes,
   leading zeros and unpadded suffixes, reserve the numeric value. For example,
   `PAT-000007`, `pat-000009` and `PAT-1` produce a maximum of 9. Reserving a
   lowercase spelling is conservative even for case-sensitive columns.
2. For other spellings ending in an ASCII hyphen and decimal digits, optionally
   followed by spaces, construct a candidate with the configured prefix and the
   **same digit spelling**. MySQL compares the complete historical value to this
   candidate with the effective column COLLATE on both operands. If equality is
   confirmed, reserve the number without modifying the stored identifier.
   Thus `PÁT-000009` reserves 9 under an accent-insensitive collation when MySQL
   confirms equivalence. No Python accent stripping or Unicode normalization is
   used. Unpadded equivalent forms are reserved conservatively too.
3. Trailing ASCII spaces are eligible for that equivalence check only with
   `PAD SPACE`. With `NO PAD`, `PAT-000009 ` is a distinct historical identifier
   and does not reserve 9. It is retained exactly. PAD SPACE comparisons still
   require a positive MySQL equality result; Python does not trim stored values.
4. Remaining printable ASCII custom identifiers such as `001`, `P9-LEGACY` and
   `PAT-000010-ARCHIVE` remain unchanged and do not reserve a number.
5. For unresolved Unicode/control-character spellings, use MySQL ordering under
   the column collation against a conservative generated-code interval. Bounds
   are prefix-hyphen plus padding-width zeros, through prefix-hyphen plus all
   nines up to the smaller of the column's suffix capacity and 19 BIGINT digits.
   All possible generated identifiers lie inside this interval for the supported
   collations. A historical value outside it cannot equal a generated value and
   is retained. A value inside it is refused for manual isolated review, even
   when it might ultimately prove harmless. For example, fullwidth digits or
   invisible characters near a generated spelling must not silently be ignored.

The broad interval intentionally favors refusal over guessing at equivalence.
It can flag a noncolliding Unicode custom code; that is a documented review case,
not permission to normalize, delete or overwrite historical data. Empty or
unrelated custom formats are not rejected merely for being noncanonical.

All seven maxima are computed before DDL. Numeric suffixes above signed BIGINT
maximum are refused. A maximum already at allocator capacity is retained, but
subsequent allocation will report exhaustion; this must be identified during
rehearsal. Patient/Staff capacity is 9,999,999,999,999,999; the other five counters
can reach 9,223,372,036,854,775,807. Counter padding is a minimum, not a ceiling.

Refusals identify only the table/column and, when relevant, collation. They do not
print raw historical values, patient identities or record IDs. Values are SQL
parameters. Keep SQL parameter logging disabled; the application engine already
uses `hide_parameters=True`.

## Schema, re-entry and recovery

The table remains InnoDB/utf8mb4 with its existing five columns. CHECK names are
`ck_code_sequence_nonnegative_value` and `ck_code_sequence_valid_padding`.
`op.f()` marks the names finalized so the metadata convention cannot prefix them
a second time. Neither CHECK expression is weakened.

A successful upgrade seeds exactly seven rows and advances Alembic's revision.
A normal rerun at head is a no-op and must not reset counters. An unexpected
pre-existing `code_sequence` table is not silently reused, reset or dropped.

MySQL DDL is not fully transactional. If CREATE succeeds but seeding or version
recording fails, the table can remain. Errors propagate; the command must not be
treated as success. Keep writers fenced, preserve evidence, inspect revision and
all seven rows in the authorized environment, and use a separately reviewed
recovery plan. Never stamp head, reset counters, drop an existing sequence table,
or blindly retry around an error. Include interruption and partial-failure cases
in the rehearsal before deciding any recovery procedure.

Downgrade is intentionally refused before changes to prevent reuse of issued
identifiers. Application rollback must not assume an Alembic downgrade is
available; recovery requires a reviewed backup/forward-repair plan.

## Focused offline validation

`tests/test_auto_code_migration.py` retains SQLite migration assertions for
legacy preservation, all seven seed rows, numeric limits and preflight failure.
Scripted MySQL answers exercise metadata selection, parameterized collation
queries, PAD/NO PAD branches, ambiguity refusal and failure before DDL. They are
**not MySQL emulation** and do not prove live collation equivalence. MySQL DDL
is compiled with the repository naming convention without connecting to a server.

## Required later isolated MySQL rehearsal

Authorize and provision it separately. Use synthetic data and the real historical
schema; do not use the allocator probe's successful run as a migration rehearsal.
The probe calls the scanner but does not execute the complete upgrade.

- Verify each supported collation used by the deployment, with explicit per-column
  overrides different from the database default and both PAD SPACE/NO PAD rules.
- Check uppercase/lowercase, unpadded and leading-zero numbers, accented prefixes,
  trailing spaces, fullwidth digits, Unicode/invisible characters, ordinary custom
  ASCII codes, unrelated Unicode codes, and multiple records in all seven tables.
- Verify MySQL equality and ordering results used by the interval policy and the
  printable-ASCII assumptions, including case-sensitive and binary columns.
- Confirm ambiguity/unsupported metadata/overflow refuses before any sequence
  table exists and leaves historical values byte-for-byte unchanged.
- Verify all seven initial counters, first allocations, maximum/exhausted values,
  actual CHECK names and enforcement, and unchanged unique indexes.
- Verify repeated successful upgrade preserves issued counters. Inject seed and
  version-recording failures, inspect remaining DDL/revision state and review
  recovery. Verify downgrade refusal leaves data and revision unchanged.
- Validate writer fencing, timing, and post-upgrade checks before enabling the
  application. Never run old manual-code writers alongside the cutover.

## Separate dependency remediation

The Step 29A read-only audit reported `source-map-js` 1.2.1, high-severity
[GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), an event-loop
denial of service from malicious indexed source maps. It is a development-tooling
dependency through Vite/PostCSS and jsdom/css-tree, not a declared frontend runtime
dependency. The production-only npm audit reported zero vulnerabilities.

Plan a separate reviewed lockfile update to 1.2.2 or a later patched compatible
version, then rerun npm audit and relevant frontend checks. No npm packages,
versions or lockfiles are modified by the migration correction. Dependency
remediation does not substitute for migration correctness or rehearsal.

## Workstream A completion and production-release gate

Workstream A is complete for local development. Backend/frontend regressions,
TypeScript/build validation and the ten native MySQL allocation checks have been
reported passing. This does not authorize production rollout.

**Production release prerequisite: complete and record the remaining native
migration-rehearsal verification.** The isolated run reached `20261015_01` with
all seven expected seed counters; the subsequent harness OperationalError most
likely came from PyMySQL classifying CHECK error 3819 as OperationalError. The
harness now handles that precise error, but its correction has only been tested
offline. The initialization marker is not completion evidence.

Before release, preserve and verify the existing synthetic database, then obtain
separate approval for the remaining native CHECK-enforcement, first-allocation,
repeat-upgrade and post-DDL-failure/recovery scenarios. Record actual outcomes and
confirm the deployment's effective collations and writer-exclusion plan. Do not
rerun the empty-database success harness against the populated database, silently
reset counters, stamp revisions, or treat read-only metadata inspection as proof
of complete rehearsal. See [the diagnosis and verification runbook](MYSQL_MIGRATION_REHEARSAL.md).
No production database connection, migration or deployment is part of this commit.
