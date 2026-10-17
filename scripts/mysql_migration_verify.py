"""Separately authorized SELECT-only verification of an existing synthetic rehearsal.

Default invocation is offline. No migrations, allocations, repair or cleanup.
The fixed rhu_dev account must have only USAGE and schema-scoped SELECT grants.
"""

import argparse
import os
import re

from scripts import mysql_migration_rehearsal as rehearsal

# Exact driver-level query allowlist; no caller-supplied SQL or identifiers.
IDENTITY = 'SELECT DATABASE(), CURRENT_USER(), USER(), @@port, VERSION()'
GRANTS = 'SHOW GRANTS FOR CURRENT_USER'
ROLES = 'SELECT CURRENT_ROLE()'
READ_ONLY = 'SELECT @@session.transaction_read_only'
INVENTORY = ('SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES '
             'WHERE TABLE_SCHEMA=DATABASE()')
CONSTRAINTS = (
    'SELECT t.CONSTRAINT_NAME, t.ENFORCED, c.CHECK_CLAUSE '
    'FROM information_schema.TABLE_CONSTRAINTS t '
    'JOIN information_schema.CHECK_CONSTRAINTS c '
    'ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME '
    "WHERE t.TABLE_SCHEMA=DATABASE() AND t.TABLE_NAME='code_sequence' AND t.CONSTRAINT_TYPE='CHECK'"
)
COLUMNS = (
    'SELECT TABLE_NAME, COLUMN_NAME, COLLATION_NAME FROM information_schema.COLUMNS '
    'WHERE TABLE_SCHEMA=DATABASE()'
)
INDEXES = (
    'SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX '
    'FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()'
)
SEQUENCES = 'SELECT sequence_key, prefix, padding, current_value, updated_at FROM code_sequence'
VERSION = 'SELECT version_num FROM alembic_version'
MARKER = 'SELECT run_id, scenario FROM auto_code_rehearsal_run'
SET_READ_ONLY = 'SET SESSION TRANSACTION READ ONLY'


def check_read_only_grants(grants, roles):
    """Fail closed for broader scopes, roles, write/admin/proxy or grant options."""
    allowed = re.compile(
        r'GRANT (USAGE ON \*\.\*|SELECT ON `rhu_labchain_dev`\.\*) '
        r'TO `rhu_dev`@`(?:localhost|127\.0\.0\.1)`\Z'
    )
    if (roles != 'NONE' or not grants or any(not allowed.fullmatch(grant) for grant in grants)
            or not any(grant.startswith('GRANT SELECT ON ') for grant in grants)):
        raise rehearsal.SafetyRefusal(
            'Verification requires only USAGE and development-schema SELECT grants, with no active roles. '
            'Do not change privileges without separate authorization.')


def allowed_queries(migration):
    return {IDENTITY, GRANTS, ROLES, READ_ONLY, INVENTORY, CONSTRAINTS, COLUMNS,
            INDEXES, SEQUENCES, VERSION, MARKER, SET_READ_ONLY} | {
                f'SELECT HEX(`{column}`) FROM `{table}`'
                for _, _, _, table, column in migration.SEQUENCES
            }


def query_guard(allowed):
    def guard(conn, cursor, statement, parameters, context, executemany):
        if statement not in allowed or executemany:
            raise rehearsal.SafetyRefusal('Non-allowlisted SQL refused by read-only verifier.')
    return guard


def expected_sequences(migration):
    return {key: (prefix, padding, 23 if index % 2 else 31)
            for index, (key, prefix, padding, _, _) in enumerate(migration.SEQUENCES)}


def check_sequence_state(rows, expected):
    actual = {key: (prefix, padding, value) for key, prefix, padding, value, _ in rows}
    rehearsal.check(len(rows) == 7 and len(actual) == 7, 'Unexpected sequence inventory.')
    if actual == expected and all(updated is None for *_, updated in rows):
        return 'initial_seed_values'
    incremented = {key: (prefix, padding, value + 1) for key, (prefix, padding, value) in expected.items()}
    if actual == incremented and all(updated is not None for *_, updated in rows):
        return 'first_allocations_committed'
    raise AssertionError('Counters differ from either known synthetic state; no repair performed.')


def verify_state(connection, migration, progress):
    import sqlalchemy as sa
    from app.models import Base

    progress.enter('inventory', stage='read_only')
    inventory = dict(connection.execute(sa.text(INVENTORY)).all())
    rehearsal.check(set(inventory) == set(Base.metadata.tables) | {'alembic_version', rehearsal.MARKER},
                    'Unexpected synthetic table inventory.')
    rehearsal.check(all(engine == 'InnoDB' for engine in inventory.values()), 'Non-InnoDB table found.')
    progress.enter('initialization_marker')
    markers = list(connection.execute(sa.text(MARKER)))
    rehearsal.check(len(markers) == 1 and re.fullmatch(r'[a-f0-9]{32}', markers[0][0])
                    and markers[0][1] == 'success', 'Unexpected rehearsal initialization marker.')
    progress.enter('revision')
    observed = tuple(connection.scalars(sa.text(VERSION)))
    progress.revision_state = ('head_observed_read_only' if observed == (rehearsal.HEAD,)
                               else 'parent_observed_read_only' if observed == (rehearsal.PARENT,)
                               else 'unexpected_revision_observed')
    rehearsal.check(observed == (rehearsal.HEAD,), 'Current revision is not the expected head.')
    progress.enter('seed_values')
    state = check_sequence_state(list(connection.execute(sa.text(SEQUENCES))), expected_sequences(migration))
    progress.enter('historical_fixture_spellings')
    for _, prefix, _, table, column in migration.SEQUENCES:
        actual = sorted(connection.scalars(sa.text(f'SELECT HEX(`{column}`) FROM `{table}`')))
        expected = sorted(value.encode('utf-8').hex().upper() for value in rehearsal.fixture_values(prefix))
        rehearsal.check(actual == expected, 'Historical fixture spellings differ; no repair performed.')
    progress.enter('effective_collations_and_unique_indexes')
    columns = {(table, column): collation for table, column, collation in connection.execute(sa.text(COLUMNS))}
    indexes = list(connection.execute(sa.text(INDEXES)))
    for index, (_, _, _, table, column) in enumerate(migration.SEQUENCES):
        expected_collation = 'utf8mb4_0900_ai_ci' if index % 2 else 'utf8mb4_unicode_ci'
        rehearsal.check(columns.get((table, column)) == expected_collation, 'Fixture collation differs.')
        groups = {}
        for name, index_name, non_unique, col, position in indexes:
            if name == table and not non_unique:
                groups.setdefault(index_name, []).append((position, col))
        rehearsal.check(any(sorted(cols) == [(1, column)] for cols in groups.values()),
                        'Historical identifier unique index missing.')
    progress.enter('constraint_metadata')
    constraints = {name: (enforced, re.sub(r'[\s`()]+', '', clause).lower())
                   for name, enforced, clause in connection.execute(sa.text(CONSTRAINTS))}
    rehearsal.check(constraints == {
        'ck_code_sequence_nonnegative_value': ('YES', 'current_value>=0'),
        'ck_code_sequence_valid_padding': ('YES', 'padding>=1andpadding<=16'),
    }, 'Constraint metadata differs.')
    print('READ_ONLY_STATE_VERIFIED: counters=' + state + '; marker=initialization_only')
    print('NOT_EXECUTED: CHECK violation tests, allocations, repeat upgrade; full rehearsal remains incomplete')


def run_read_only(config, *, authorized, progress=None):
    config.validate()
    if not authorized:
        raise rehearsal.SafetyRefusal('Explicit authorization to inspect the existing synthetic database is required.')
    rehearsal.verify_worktree()
    progress = progress or rehearsal.Progress(stage='read_only')
    import sqlalchemy as sa
    from sqlalchemy.pool import NullPool

    migration = rehearsal.load_migration()  # Definitions only; no upgrade call.
    guard = query_guard(allowed_queries(migration))
    progress.enter('engine_creation')
    engine = sa.create_engine(sa.URL.create(
        'mysql+pymysql', username=config.user, password=config.password,
        host=config.host, port=config.port, database=config.database,
        query={'charset': 'utf8mb4'},
    ), echo=False, hide_parameters=True, poolclass=NullPool,
        connect_args={'connect_timeout': 5, 'read_timeout': 60, 'write_timeout': 60})
    try:
        progress.enter('connect')
        with engine.connect() as connection:
            sa.event.listen(connection, 'before_cursor_execute', guard)
            progress.enter('server_read_only_session')
            connection.execute(sa.text(SET_READ_ONLY))
            connection.rollback()
            # Applies to every later transaction, including after reconnect refusal.
            progress.enter('actual_database_identity')
            rehearsal.verify_identity(connection.execute(sa.text(IDENTITY)).one())
            rehearsal.check(connection.scalar(sa.text(READ_ONLY)) == 1, 'Server read-only session not enabled.')
            progress.enter('select_only_privileges')
            check_read_only_grants(list(connection.scalars(sa.text(GRANTS))), connection.scalar(sa.text(ROLES)))
            verify_state(connection, migration, progress)
            progress.enter('read_only_rollback')
            connection.rollback()
            progress.enter('connection_close')
    finally:
        # No reconnect/retry, commit, advisory lock, temp tables, or migration calls.
        import sys
        original_error = sys.exc_info()[1]
        if original_error is None:
            progress.enter('engine_dispose')
        try:
            engine.dispose()
        except Exception as exc:
            if original_error is None:
                raise
            rehearsal.report_failure(exc, rehearsal.Progress('read_only', 'engine_dispose',
                                                               progress.revision_state), secondary=True)
    return 0


def main(argv=None, *, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-read-only', action='store_true')
    parser.add_argument('--authorize-existing-synthetic', action='store_true')
    parser.add_argument('--prompt-password', action='store_true')
    args = parser.parse_args(argv)
    if not args.verify_read_only:
        print('SKIP: explicit read-only authorization required; no connection attempted')
        return 0
    progress = rehearsal.Progress(stage='read_only')
    try:
        if not args.authorize_existing_synthetic:
            raise rehearsal.SafetyRefusal('Explicit authorization to inspect the existing synthetic database is required.')
        config = rehearsal.load_config(os.environ if environ is None else environ, prompt=args.prompt_password)
        return run_read_only(config, authorized=True, progress=progress)
    except rehearsal.SafetyRefusal as exc:
        print('REFUSED: ' + str(exc))
        return 2
    except Exception as exc:
        rehearsal.report_failure(exc, progress)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
