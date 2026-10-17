"""Explicitly authorized, empty-database-only native migration rehearsal.

Import/default/check modes are offline. See docs/MYSQL_MIGRATION_REHEARSAL.md.
"""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from uuid import uuid4

from scripts.mysql_auto_code_probe import SafetyRefusal, check, load_config, load_migration

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROOT = Path('/home/rhuadmin/rhu-labchain-dev')
PARENT = '20261005_01'
HEAD = '20261015_01'
REVISIONS = (
    '20260914_01', '20260914_02', '20260914_03', '20260914_04',
    '20260915_01', '20260916_01', '20260920_01', '20260924_01', PARENT, HEAD,
)
LOCK = 'rhu_labchain_dev.migration_rehearsal'
MARKER = 'auto_code_rehearsal_run'
SCENARIOS = ('success', 'seed-failure', 'revision-failure')
FLAG = 'RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED'
# No application settings, engine, URL, logging configuration or .env imports.
ENVIRONMENT = '''from alembic import context
from app.models import Base
config = context.config
connection = config.attributes.get("verified_connection")
if connection is None or context.is_offline_mode():
    raise RuntimeError("Only the verified rehearsal connection is permitted")
context.configure(connection=connection, target_metadata=Base.metadata,
                  compare_type=True, compare_server_default=True)
with context.begin_transaction():
    context.run_migrations()
'''


@dataclass
class Progress:
    stage: str = 'authorization'
    substage: str = 'entry'
    revision_state: str = 'not_observed'

    def enter(self, substage, *, stage=None):
        if stage is not None:
            self.stage = stage
        self.substage = substage
        print(f'SUBSTAGE {self.stage}.{self.substage}')


def error_codes(exc):
    """Read only structured DBAPI fields; never parse error messages or SQL."""
    original = getattr(exc, 'orig', exc)
    arguments = getattr(original, 'args', ())
    number = arguments[0] if arguments else None
    if type(number) is not int or not 1 <= number <= 65535:
        number = None
    state = getattr(original, 'sqlstate', None)
    if not isinstance(state, str) or not re.fullmatch(r'[A-Z0-9]{5}', state):
        state = None
    return number, state


def report_failure(exc, progress, *, secondary=False):
    number, state = error_codes(exc)
    label = 'CLEANUP_FAILED' if secondary else 'REHEARSAL_FAILED'
    print(f'{label}: stage={progress.stage} substage={progress.substage} '
          f'category={type(exc).__name__} mysql_errno={number or "unavailable"} '
          f'sqlstate={state or "unavailable"} revision_state={progress.revision_state}; '
          'exception details suppressed; preserve database for reviewed verification')


def verify_worktree():
    if ROOT != EXPECTED_ROOT or (ROOT / '.env').exists():
        raise SafetyRefusal('Use only the development worktree without a .env file.')
    branch = subprocess.check_output(
        ['git', 'branch', '--show-current'], cwd=ROOT, text=True,
    ).strip()
    if branch != 'major-update-v1':
        raise SafetyRefusal('The development branch is required.')


def verify_authorization(config, *, authorized, writers_stopped, scenario):
    config.validate()
    if not authorized or not writers_stopped or scenario not in SCENARIOS:
        raise SafetyRefusal('Explicit empty-database authorization and writer exclusion are required.')
    if os.environ.get(FLAG) != '1':
        raise SafetyRefusal('The migration writer-exclusion acknowledgement must equal 1.')
    verify_worktree()


def verify_identity(row):
    database, authenticated, login, port, version = row
    allowed = {'rhu_dev@localhost', 'rhu_dev@127.0.0.1'}
    if database != 'rhu_labchain_dev' or authenticated not in allowed or login not in allowed or port != 3306:
        raise SafetyRefusal('The server database, authenticated account or client host is not permitted.')
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
    if 'mariadb' in version.lower() or not match or tuple(map(int, match.groups())) < (8, 0, 16):
        raise SafetyRefusal('Native MySQL 8.0.16 or newer is required.')


def require_empty(objects, revision):
    if objects or revision:
        raise SafetyRefusal('Database is not empty; existing objects/revision will not be reused or removed.')


@contextmanager
def isolated_config(connection):
    """Copy exact revision bytes; never execute the application's migrations/env.py."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    with tempfile.TemporaryDirectory(prefix='.migration-rehearsal-', dir=ROOT) as directory:
        folder = Path(directory)
        (folder / 'env.py').write_text(ENVIRONMENT)
        shutil.copytree(ROOT / 'migrations/versions', folder / 'versions',
                        ignore=shutil.ignore_patterns('__pycache__'))
        config = Config()
        config.set_main_option('script_location', str(folder))
        config.attributes['verified_connection'] = connection
        script = ScriptDirectory.from_config(config)
        revisions = list(reversed(list(script.walk_revisions())))
        check(tuple(item.revision for item in revisions) == REVISIONS, 'Unexpected revision chain.')
        check(script.get_heads() == [HEAD], 'Unexpected migration head.')
        for index, item in enumerate(revisions):
            check(item.down_revision == (REVISIONS[index - 1] if index else None), 'Nonlinear chain.')
        digest = hashlib.sha256()
        for path in sorted((folder / 'versions').glob('*.py')):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        print('MIGRATION_SOURCE_SHA256=' + digest.hexdigest())
        yield config


def revision(connection):
    import sqlalchemy as sa
    return tuple(connection.scalars(sa.text('SELECT version_num FROM alembic_version')))


def historical_snapshot(connection, migration):
    import sqlalchemy as sa
    # HEX avoids collation equality masking a changed spelling or trailing spaces.
    return {
        table: tuple(sorted(connection.scalars(sa.text(f'SELECT HEX(`{column}`) FROM `{table}`'))))
        for _, _, _, table, column in migration.SEQUENCES
    }


def index_snapshot(connection, migration):
    import sqlalchemy as sa
    inspector = sa.inspect(connection)
    return {
        table: tuple(sorted((index['name'], tuple(index['column_names']), bool(index['unique']))
                            for index in inspector.get_indexes(table)))
        for _, _, _, table, _ in migration.SEQUENCES
    }


def insert_code(connection, table, column, value):
    import sqlalchemy as sa
    from app.models import Base
    extras = {
        'patient': {'first_name': 'Synthetic', 'last_name': 'Rehearsal'},
        'staff': {'first_name': 'Synthetic', 'last_name': 'Rehearsal'},
        'lab_department': {'department_name': 'Synthetic'},
        'test_catalog': {'test_name': 'Synthetic', 'result_type': 'TEXT'},
        'test_panel': {'panel_name': 'Synthetic'},
        'rejection_reason': {'reason_name': 'Synthetic'},
        'report_template': {'template_name': 'Synthetic'},
    }
    check(table in extras and column in Base.metadata.tables[table].c, 'Invalid fixture target.')
    if table == 'test_catalog':
        extras[table]['department_id'] = connection.scalar(
            sa.select(Base.metadata.tables['lab_department'].c.department_id)
            .order_by(Base.metadata.tables['lab_department'].c.department_id).limit(1))
    connection.execute(sa.insert(Base.metadata.tables[table]), {column: value, **extras[table]})


def fixture_values(prefix):
    accented = prefix.replace('A', 'Á').replace('E', 'É').replace('T', 'Ť')
    return [f'{prefix}-000007', f'{prefix.lower()}-000011', f'{prefix}-17',
            'CUSTOM-ARCHIVE', f'{accented}-000023', f'{prefix}-000031 ']


def prepare_history(connection, migration):
    import sqlalchemy as sa
    from app.models import Base
    # Effective column overrides: two real MySQL padding regimes in the same DB.
    for index, (_, _, _, table, column) in enumerate(migration.SEQUENCES):
        collation = 'utf8mb4_0900_ai_ci' if index % 2 else 'utf8mb4_unicode_ci'
        length = Base.metadata.tables[table].c[column].type.length
        connection.execute(sa.text(
            f'ALTER TABLE `{table}` MODIFY `{column}` VARCHAR({length}) '
            f'CHARACTER SET utf8mb4 COLLATE {collation} NOT NULL'
        ))
    connection.commit()
    expected = {}
    # Department first because the real test_catalog FK is preserved.
    ordered = sorted(migration.SEQUENCES, key=lambda item: item[0] != 'DEPARTMENT')
    for key, prefix, padding, table, column in ordered:
        values = fixture_values(prefix)
        for value in values:
            insert_code(connection, table, column, value)
        collation, _, pad = migration.column_collation(connection, table, column)
        check(migration.mysql_comparison(connection, collation, values[1], candidate=f'{prefix}-000011'),
              'Native case equivalence failed.')
        check(migration.mysql_comparison(connection, collation, values[4], candidate=f'{prefix}-000023'),
              'Native accent equivalence failed.')
        check(migration.mysql_comparison(connection, collation, values[5], candidate=f'{prefix}-000031')
              == (pad == 'PAD SPACE'), 'Native padding comparison failed.')
        expected[key] = (prefix, padding, 31 if pad == 'PAD SPACE' else 23)
    connection.commit()
    return expected


def refusal_scenario(connection, config, migration, *, value, table, column, expected_error):
    from alembic import command
    import sqlalchemy as sa

    before = historical_snapshot(connection, migration)
    connection.rollback()
    transaction = connection.begin()
    insert_code(connection, table, column, value)

    def no_writes(conn, cursor, statement, parameters, context, executemany):
        check(statement.lstrip().upper().startswith(('SELECT', 'SHOW', 'DESCRIBE')),
              'Refused migration attempted a write or DDL.')

    sa.event.listen(connection, 'before_cursor_execute', no_writes)
    try:
        try:
            command.upgrade(config, HEAD)
        except RuntimeError as exc:
            check(expected_error in str(exc), 'Unexpected preflight refusal.')
        else:
            raise AssertionError('Unsafe history did not refuse migration.')
    finally:
        sa.event.remove(connection, 'before_cursor_execute', no_writes)
        transaction.rollback()
    check(revision(connection) == (PARENT,), 'Refusal changed revision.')
    check(not sa.inspect(connection).has_table('code_sequence'), 'Refusal left sequence DDL.')
    check(historical_snapshot(connection, migration) == before, 'Refusal changed historical data.')
    connection.rollback()


class InjectedFailure(Exception):
    """Synthetic failure: never contains SQL parameters or credentials."""


def validate_checks(connection, progress):
    import sqlalchemy as sa
    from sqlalchemy.exc import DBAPIError

    for name, assignment in (
        ('negative_counter', 'current_value=-1'),
        ('padding_zero', 'padding=0'), ('padding_seventeen', 'padding=17'),
    ):
        progress.enter('check_' + name)
        with connection.begin():
            try:
                with connection.begin_nested():
                    connection.execute(sa.text(
                        f"UPDATE code_sequence SET {assignment} WHERE sequence_key='PATIENT'"))
            except DBAPIError as exc:
                # PyMySQL maps 3819 to OperationalError, not IntegrityError.
                # Only the precise native CHECK error is an expected result.
                if error_codes(exc)[0] != 3819:
                    raise
            else:
                raise AssertionError('CHECK was not enforced.')


def upgrade_and_verify(connection, config, migration, expected, scenario, progress=None):
    from alembic import command
    import sqlalchemy as sa
    from sqlalchemy.orm import Session
    from app.services.code_generation_service import allocate_code

    progress = progress or Progress(stage=scenario)
    progress.enter('historical_snapshot_before_upgrade')
    before = historical_snapshot(connection, migration)
    progress.enter('index_snapshot_before_upgrade')
    indexes = index_snapshot(connection, migration)
    progress.enter('rollback_pre_upgrade_reads')
    connection.rollback()
    injected = []

    def inject(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.strip().lower().replace('`', '')
        target = ('insert into code_sequence' if scenario == 'seed-failure'
                  else 'update alembic_version')
        if normalized.startswith(target):
            injected.append(True)
            raise InjectedFailure()

    if scenario != 'success':
        sa.event.listen(connection, 'before_cursor_execute', inject)
    try:
        try:
            progress.enter('alembic_upgrade')
            progress.revision_state = 'unknown_during_upgrade'
            command.upgrade(config, HEAD)
            progress.revision_state = 'upgrade_returned_revision_not_observed'
        except InjectedFailure:
            check(scenario != 'success', 'Unexpected injected failure.')
        else:
            check(scenario == 'success', 'Failure injection was not reached.')
    finally:
        if scenario != 'success':
            sa.event.remove(connection, 'before_cursor_execute', inject)
    progress.enter('rollback_post_upgrade_reads')
    connection.rollback()
    progress.enter('observe_revision_after_upgrade')
    observed_revision = revision(connection)
    progress.revision_state = ('head_observed_after_upgrade' if observed_revision == (HEAD,)
                               else 'parent_observed_after_upgrade' if observed_revision == (PARENT,)
                               else 'unexpected_revision_observed')
    progress.enter('historical_snapshot_after_upgrade')
    check(historical_snapshot(connection, migration) == before, 'Historical identifiers changed.')
    progress.enter('sequence_table_presence')
    check(sa.inspect(connection).has_table('code_sequence'), 'Expected sequence DDL missing.')
    progress.enter('index_snapshot_after_upgrade')
    check(index_snapshot(connection, migration) == indexes, 'Historical indexes changed.')
    if scenario != 'success':
        check(bool(injected), 'Injection not exercised.')
        check(revision(connection) == (PARENT,), 'Failed upgrade advanced revision.')
        check(connection.scalar(sa.text('SELECT COUNT(*) FROM code_sequence')) == 0,
              'Failed upgrade left committed seed rows; preserve evidence and review.')
        print('PASS intentional_post_ddl_failure; table retained, revision remains parent')
        return

    progress.enter('sequence_values')
    check(observed_revision == (HEAD,), 'Successful upgrade did not advance revision.')
    actual = {key: (prefix, padding, value) for key, prefix, padding, value in connection.execute(
        sa.text('SELECT sequence_key, prefix, padding, current_value FROM code_sequence'))}
    check(actual == expected, 'Sequence initialization differs from expected seven counters.')
    progress.enter('constraint_names')
    names = {row[0] for row in connection.execute(sa.text(
        "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='code_sequence' AND CONSTRAINT_TYPE='CHECK'"))}
    check(names == {'ck_code_sequence_nonnegative_value', 'ck_code_sequence_valid_padding'},
          'CHECK constraint names differ.')
    progress.enter('rollback_verification_reads')
    connection.rollback()
    validate_checks(connection, progress)
    progress.enter('first_allocations')
    with Session(connection, autoflush=False) as session:
        for key, (prefix, padding, value) in expected.items():
            check(allocate_code(session, key) == f'{prefix}-{value + 1:0{padding}d}',
                  'First allocation differs from initialized counter.')
        progress.enter('commit_first_allocations')
        session.commit()
    progress.enter('snapshot_allocated_counters')
    saved = tuple(connection.execute(sa.text('SELECT * FROM code_sequence ORDER BY sequence_key')))
    progress.enter('rollback_pre_repeat_reads')
    connection.rollback()
    progress.enter('repeat_upgrade')
    command.upgrade(config, HEAD)
    progress.enter('verify_repeat_upgrade')
    check(tuple(connection.execute(sa.text('SELECT * FROM code_sequence ORDER BY sequence_key'))) == saved,
          'Normal repeated upgrade reset counters.')
    check(historical_snapshot(connection, migration) == before, 'Repeated upgrade changed history.')
    check(revision(connection) == (HEAD,), 'Repeated upgrade changed revision.')
    print('PASS seven_counters historical_preservation checks first_allocations repeatability')


def run_mysql(config, *, authorized, writers_stopped, scenario, progress=None):
    """Only online entry point; revalidates every authorization before engine creation."""
    progress = progress or Progress()
    verify_authorization(config, authorized=authorized, writers_stopped=writers_stopped, scenario=scenario)
    import sqlalchemy as sa
    from alembic import command
    from sqlalchemy.pool import NullPool

    progress.enter('engine_creation')
    engine = sa.create_engine(sa.URL.create(
        'mysql+pymysql', username=config.user, password=config.password,
        host=config.host, port=config.port, database=config.database,
        query={'charset': 'utf8mb4'},
    ), echo=False, hide_parameters=True, poolclass=NullPool,
        connect_args={'connect_timeout': 5, 'read_timeout': 60, 'write_timeout': 60})
    try:
        progress.enter('connect_and_verify_identity')
        with engine.connect() as connection:
            verify_identity(connection.execute(sa.text(
                'SELECT DATABASE(), CURRENT_USER(), USER(), @@port, VERSION()')).one())
            progress.enter('empty_database_and_sessions')
            check(connection.scalar(sa.text('SELECT GET_LOCK(:name, 0)'), {'name': LOCK}) == 1,
                  'Another rehearsal owns the lock.')
            objects = list(connection.scalars(sa.text(
                'SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')))
            old_revision = revision(connection) if 'alembic_version' in objects else ()
            extra_objects = connection.scalar(sa.text(
                'SELECT (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()) '
                '+ (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE())'))
            require_empty(objects or extra_objects, old_revision)
            check(connection.scalar(sa.text(
                'SELECT COUNT(*) FROM information_schema.PROCESSLIST '
                'WHERE ID <> CONNECTION_ID() AND (DB=DATABASE() OR USER=:user)'),
                {'user': 'rhu_dev'}) == 0, 'Another visible development session exists.')
            connection.commit()
            progress.enter('isolated_alembic_environment')
            with isolated_config(connection) as alembic_config:
                progress.enter('initialization_marker')
                run_id = uuid4().hex
                connection.execute(sa.text(
                    f'CREATE TABLE {MARKER} (run_id CHAR(32) PRIMARY KEY, scenario VARCHAR(32) NOT NULL) '
                    'ENGINE=InnoDB'))
                connection.execute(sa.text(f'INSERT INTO {MARKER} VALUES (:run, :scenario)'),
                                   {'run': run_id, 'scenario': scenario})
                connection.commit()
                print('SYNTHETIC_RUN_ID=' + run_id)
                progress.enter('build_parent_schema', stage='setup')
                print('STAGE build_synthetic_parent_schema')
                command.upgrade(alembic_config, PARENT)
                progress.enter('verify_parent_schema')
                check(revision(connection) == (PARENT,), 'Synthetic baseline revision incorrect.')
                progress.revision_state = 'parent_observed_before_upgrade'
                from app.models import Base
                inventory = {name for (name,) in connection.execute(sa.text(
                    'SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()'))}
                check(inventory == (set(Base.metadata.tables) - {'code_sequence'}) | {'alembic_version', MARKER},
                      'Synthetic baseline table inventory differs.')
                check(connection.scalar(sa.text(
                    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() "
                    "AND ENGINE <> 'InnoDB'")) == 0, 'Synthetic tables must use InnoDB.')
                migration = load_migration()
                progress.enter('seed_history')
                print('STAGE seed_synthetic_history_and_compare_native_collations')
                expected = prepare_history(connection, migration)
                print('PASS native_case_accent_padding_unpadded_and_custom_fixtures')
                progress.enter('preflight_refusal')
                refusal_scenario(connection, alembic_config, migration,
                                 value='PAT-０００９９９', table='patient', column='patient_code',
                                 expected_error='Ambiguous historical identifier')
                print('PASS ambiguity_before_ddl')
                progress.enter('preflight_refusal')
                refusal_scenario(connection, alembic_config, migration,
                                 value='REJ-9223372036854775808', table='rejection_reason', column='reason_code',
                                 expected_error='exceeds sequence capacity')
                print('PASS overflow_before_ddl')
                print('STAGE ' + scenario)
                progress.enter('entry', stage=scenario)
                upgrade_and_verify(connection, alembic_config, migration, expected, scenario, progress)
                progress.enter('final_rollback')
                connection.rollback()
                progress.enter('temporary_environment_cleanup', stage='cleanup')
            progress.enter('connection_close')
    finally:
        # Preserve the original failure's stage if disposal also fails.
        import sys
        original_error = sys.exc_info()[1]
        if original_error is None:
            progress.enter('engine_dispose', stage='cleanup')
        try:
            engine.dispose()  # Never drops tables.
        except Exception as exc:
            if original_error is None:
                raise
            report_failure(exc, Progress('cleanup', 'engine_dispose', progress.revision_state), secondary=True)
    print('REHEARSAL_PASS; synthetic database retained; no cleanup performed')
    return 0


def main(argv=None, *, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--run', action='store_true')
    modes.add_argument('--check', action='store_true', help='Offline credentials/target validation only')
    parser.add_argument('--prompt-password', action='store_true')
    parser.add_argument('--authorize-empty-database', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true')
    parser.add_argument('--scenario', choices=SCENARIOS, default='success')
    args = parser.parse_args(argv)
    if not args.run and not args.check:
        print('SKIP: explicit --run authorization is required; no connection attempted')
        return 0
    progress = Progress()
    try:
        if args.run and not (args.authorize_empty_database and args.writers_stopped):
            raise SafetyRefusal('Supply explicit empty-database authorization and writer exclusion.')
        config = load_config(os.environ if environ is None else environ, prompt=args.prompt_password)
        if args.check:
            print('CONFIGURATION_PASS: no connection attempted; server state is unverified')
            return 0
        return run_mysql(config, authorized=args.authorize_empty_database,
                         writers_stopped=args.writers_stopped, scenario=args.scenario, progress=progress)
    except SafetyRefusal as exc:
        print('REFUSED: ' + str(exc))
        return 2
    except Exception as exc:
        # Driver exceptions may contain SQL/parameters even with hide_parameters.
        report_failure(exc, progress)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
