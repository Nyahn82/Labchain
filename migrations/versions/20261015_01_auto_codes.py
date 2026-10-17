"""Create safely initialized transactional display-code sequences.

Revision ID: 20261015_01
Revises: 20261005_01

Existing identifiers remain unchanged. The sequence for each entity starts
above the highest safely recognized numeric identifier. MySQL column collation
preflight refuses unresolved possible collisions before any DDL. See
docs/AUTO_CODE_MIGRATION.md for prerequisites and recovery constraints.
"""

import os
import re

from alembic import op
import sqlalchemy as sa


revision = "20261015_01"
down_revision = "20261005_01"
branch_labels = None
depends_on = None

MAX_COUNTER = 9223372036854775807

# All table and column names are fixed application-controlled constants.
SEQUENCES = [
    ("PATIENT", "PAT", 6, "patient", "patient_code"),
    ("STAFF", "STF", 6, "staff", "staff_code"),
    ("DEPARTMENT", "DEP", 3, "lab_department", "department_code"),
    ("TEST", "TST", 4, "test_catalog", "test_code"),
    ("PANEL", "PNL", 4, "test_panel", "panel_code"),
    ("REJECTION_REASON", "REJ", 3, "rejection_reason", "reason_code"),
    ("REPORT_TEMPLATE", "TMP", 3, "report_template", "template_code"),
]


# These untailored collations preserve the lexical order of ASCII decimal
# strings. Printable ASCII has no contractions/expansions into our code alphabet;
# only letter case and the declared padding rule can affect ASCII equality.
# Locale-tailored or unreviewed collations require a separate reviewed rehearsal.
SUPPORTED_COLLATIONS = frozenset({
    "utf8mb4_bin", "utf8mb4_0900_bin", "utf8mb4_general_ci",
    "utf8mb4_unicode_ci", "utf8mb4_unicode_520_ci",
    "utf8mb4_0900_ai_ci", "utf8mb4_0900_as_ci", "utf8mb4_0900_as_cs",
})


def column_collation(connection, table_name, column_name):
    """Read the effective COLUMN collation and its pad rule, never the default."""
    row = connection.execute(sa.text(
        "SELECT c.CHARACTER_SET_NAME, c.COLLATION_NAME, "
        "c.CHARACTER_MAXIMUM_LENGTH, k.PAD_ATTRIBUTE "
        "FROM information_schema.COLUMNS AS c "
        "JOIN information_schema.COLLATIONS AS k "
        "ON k.COLLATION_NAME = c.COLLATION_NAME "
        "WHERE c.TABLE_SCHEMA = DATABASE() "
        "AND c.TABLE_NAME = :table_name AND c.COLUMN_NAME = :column_name"
    ), {"table_name": table_name, "column_name": column_name}).one_or_none()
    if (row is None or row[0] != "utf8mb4" or row[1] not in SUPPORTED_COLLATIONS
            or row[3] not in {"PAD SPACE", "NO PAD"}
            or not isinstance(row[2], int) or row[2] < 1):
        raise RuntimeError(
            f"Unsupported identifier collation metadata for {table_name}.{column_name}; "
            "review the column collation on isolated MySQL before migration."
        )
    return row[1], row[2], row[3]


def mysql_comparison(connection, collation, value, *, candidate=None, lower=None, upper=None):
    """Ask MySQL itself about equality/order under the verified column collation."""
    if collation not in SUPPORTED_COLLATIONS:
        raise RuntimeError("Unreviewed identifier collation.")
    # COLLATE identifiers cannot be bound parameters; only allowlisted names
    # enter SQL. Historical values are always parameters and never logged here.
    def operand(name):
        return f"(CAST(:{name} AS CHAR CHARACTER SET utf8mb4) COLLATE {collation})"
    parameters = {"value": value}
    if candidate is not None:
        expression = f"{operand('value')} = {operand('candidate')}"
        parameters["candidate"] = candidate
    else:
        expression = (f"{operand('value')} >= {operand('lower')} AND "
                      f"{operand('value')} <= {operand('upper')}")
        parameters.update(lower=lower, upper=upper)
    result = connection.scalar(sa.text("SELECT " + expression), parameters)
    if result not in (0, 1):
        raise RuntimeError("Identifier collation comparison was inconclusive.")
    return bool(result)


def existing_maximum(connection, table_name, column_name, prefix):
    """Reserve recognized numbers; refuse unresolved potential SQL collisions.

    No normalization or writes occur. SQLite supports the isolated migration
    tests only; it does not certify MySQL collation behavior. See the migration
    runbook for supported collations, the conservative refusal policy and the
    required writer exclusion / isolated MySQL rehearsal.
    """
    if not all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in (table_name, column_name)):
        raise RuntimeError("Invalid historical-code scan target.")
    padding = next((item[2] for item in SEQUENCES if item[1] == prefix), None)
    if padding is None:
        raise RuntimeError("Unknown historical-code prefix.")
    dialect = connection.dialect.name
    if dialect == "mysql":
        collation, length, pad = column_collation(connection, table_name, column_name)
        digits = min(len(str(MAX_COUNTER)), length - len(prefix) - 1)
        if digits < padding:
            raise RuntimeError(f"Identifier column capacity is insufficient: {table_name}.{column_name}.")
        # This deliberately broad interval contains EVERY possible generated
        # identifier under the supported collations, including future widths.
        lower, upper = prefix + "-" + "0" * padding, prefix + "-" + "9" * digits
    elif dialect != "sqlite":
        raise RuntimeError("Historical-code preflight requires MySQL or isolated SQLite tests.")

    pattern = re.compile(rf"{re.escape(prefix)}-([0-9]+)", re.IGNORECASE | re.ASCII)
    maximum = 0
    # Do not use LIKE as a prefilter: LIKE and uniqueness equality need not
    # agree for expansions, ignorable characters or Unicode equivalents.
    values = connection.execute(sa.text(f"SELECT `{column_name}` FROM `{table_name}`")).all()
    for (value,) in values:
        if value is None:
            continue
        if not isinstance(value, str):
            raise RuntimeError(f"Invalid historical-code type in {table_name}.{column_name}.")
        match = pattern.fullmatch(value)
        if match is None and dialect == "mysql":
            # Preserve digit spelling/zero padding. A numeric spelling is
            # accepted ONLY if MySQL confirms the full value is equivalent.
            suffix = re.search(r"-([0-9]+)( *)\Z", value, re.ASCII)
            if suffix and (not suffix[2] or pad == "PAD SPACE"):
                candidate = prefix + "-" + suffix[1]
                if mysql_comparison(connection, collation, value, candidate=candidate):
                    match = suffix
            if match is None:
                printable_ascii = all(" " <= character <= "~" for character in value)
                if not printable_ascii and mysql_comparison(
                    connection, collation, value, lower=lower, upper=upper,
                ):
                    # No Python casefold/transliteration can prove equivalence
                    # for every UCA expansion, contraction or ignorable character.
                    raise RuntimeError(
                        f"Ambiguous historical identifier in {table_name}.{column_name} "
                        f"under {collation}; isolated review required before migration."
                    )
        elif match is None and dialect == "sqlite" and not value.isascii():
            raise RuntimeError(
                f"Historical identifier in {table_name}.{column_name} requires MySQL collation preflight."
            )
        if match is None:
            continue
        number = int(match[1])
        if number > MAX_COUNTER:
            raise RuntimeError(f"Existing {table_name} code exceeds sequence capacity.")
        maximum = max(maximum, number)
    return maximum


def upgrade() -> None:
    connection = op.get_bind()
    if (connection.dialect.name == "mysql"
            and os.environ.get("RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED") != "1"):
        raise RuntimeError(
            "Automatic-code migration requires all application/import writers stopped; "
            "follow the reviewed runbook and explicitly acknowledge writer exclusion."
        )

    # Preflight existing codes BEFORE creating the new table.
    # This avoids zero-based initialization on databases containing
    # identifiers such as PAT-000007 or STF-000123.
    rows = []

    for key, prefix, padding, table_name, column_name in SEQUENCES:
        maximum = existing_maximum(
            connection,
            table_name,
            column_name,
            prefix,
        )

        rows.append({
            "sequence_key": key,
            "prefix": prefix,
            "current_value": maximum,
            "padding": padding,
        })

    op.create_table(
        "code_sequence",
        sa.Column(
            "sequence_key", sa.String(40),
            primary_key=True, nullable=False,
        ),
        sa.Column(
            "prefix", sa.String(10), nullable=False,
        ),
        sa.Column(
            "current_value", sa.BigInteger(), nullable=False,
        ),
        sa.Column(
            "padding", sa.SmallInteger(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=True,
        ),
        sa.CheckConstraint(
            "current_value >= 0",
            name=op.f("ck_code_sequence_nonnegative_value"),
        ),
        sa.CheckConstraint(
            "padding >= 1 AND padding <= 16",
            name=op.f("ck_code_sequence_valid_padding"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    table = sa.table(
        "code_sequence",
        sa.column("sequence_key", sa.String(40)),
        sa.column("prefix", sa.String(10)),
        sa.column("current_value", sa.BigInteger()),
        sa.column("padding", sa.SmallInteger()),
    )

    op.bulk_insert(table, rows)


def downgrade() -> None:
    # Issued codes cannot safely be renumbered or reused.
    # Rollback requires an explicit reviewed database-recovery plan.
    raise RuntimeError(
        "Automatic code sequence downgrade is intentionally blocked "
        "to prevent identifier reuse."
    )
