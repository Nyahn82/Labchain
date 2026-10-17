"""Offline checks only; every real engine/migration call remains forbidden."""

import ast
from dataclasses import replace
import inspect

from alembic import command
import pytest
import sqlalchemy as sa

from scripts import mysql_migration_verify as verify


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Read-only verifier safety tests attempted an engine or migration')
    monkeypatch.setattr(sa, 'create_engine', forbidden)
    monkeypatch.setattr(command, 'upgrade', forbidden)
    monkeypatch.setattr(command, 'downgrade', forbidden)
    monkeypatch.setattr(command, 'stamp', forbidden)


@pytest.fixture
def environment():
    return dict(RHU_CODE_TEST_HOST='127.0.0.1', RHU_CODE_TEST_PORT='3306',
                RHU_CODE_TEST_DATABASE='rhu_labchain_dev', RHU_CODE_TEST_USER='rhu_dev',
                RHU_CODE_TEST_PASSWORD='offline-sentinel')


@pytest.mark.parametrize('configured', [True, False])
def test_default_never_connects(configured, environment):
    assert verify.main([], environ=environment if configured else {}) == 0


def test_explicit_permission_required(environment):
    assert verify.main(['--verify-read-only'], environ=environment) == 2
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        verify.run_read_only(verify.rehearsal.load_config(environment), authorized=False)


@pytest.mark.parametrize('name,value', [('HOST', 'localhost'), ('DATABASE', 'rhu_labchain'),
                                        ('USER', 'root'), ('PORT', '3307')])
def test_wrong_target_never_connects(name, value, environment):
    environment['RHU_CODE_TEST_' + name] = value
    assert verify.main(['--verify-read-only', '--authorize-existing-synthetic'], environ=environment) == 2


def test_direct_entry_rechecks_database(environment):
    config = replace(verify.rehearsal.load_config(environment), database='rhu_labchain')
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        verify.run_read_only(config, authorized=True)


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1'])
def test_only_select_and_usage_are_accepted(host):
    verify.check_read_only_grants([
        f'GRANT USAGE ON *.* TO `rhu_dev`@`{host}`',
        f'GRANT SELECT ON `rhu_labchain_dev`.* TO `rhu_dev`@`{host}`',
    ], 'NONE')


@pytest.mark.parametrize('grant', [
    'GRANT ALL PRIVILEGES ON `rhu_labchain_dev`.* TO `rhu_dev`@`localhost`',
    'GRANT SELECT, INSERT ON `rhu_labchain_dev`.* TO `rhu_dev`@`localhost`',
    'GRANT SELECT ON *.* TO `rhu_dev`@`localhost`',
    'GRANT SELECT ON `rhu_labchain`.* TO `rhu_dev`@`localhost`',
    'GRANT SELECT ON `rhu_labchain_dev`.* TO `rhu_dev`@`localhost` WITH GRANT OPTION',
    'GRANT SELECT ON `rhu_labchain_dev`.* TO `rhu_dev`@`%`',
    'GRANT `administrator`@`%` TO `rhu_dev`@`localhost`',
    'GRANT SYSTEM_USER ON *.* TO `rhu_dev`@`localhost`',
])
def test_write_broad_or_delegated_privileges_refuse(grant):
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        verify.check_read_only_grants([grant], 'NONE')


@pytest.mark.parametrize('roles', ['`reader`@`%`', 'ALL', None])
def test_roles_fail_closed(roles):
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        verify.check_read_only_grants(['GRANT SELECT ON `rhu_labchain_dev`.* TO `rhu_dev`@`localhost`'], roles)


def test_missing_select_privilege_refuses():
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        verify.check_read_only_grants(['GRANT USAGE ON *.* TO `rhu_dev`@`localhost`'], 'NONE')


@pytest.mark.parametrize('sql', [
    'UPDATE code_sequence SET current_value=0', 'DELETE FROM patient',
    'DROP TABLE code_sequence', 'TRUNCATE patient', 'COMMIT',
    'SET SESSION TRANSACTION READ WRITE', 'SELECT * FROM patient FOR UPDATE',
    "SELECT 'private' INTO OUTFILE '/tmp/private'", 'SELECT DATABASE(); DELETE FROM patient',
])
def test_query_guard_rejects_every_non_allowlisted_operation(sql):
    guard = verify.query_guard(verify.allowed_queries(verify.rehearsal.load_migration()))
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        guard(None, None, sql, None, None, False)


def test_all_verifier_queries_are_fixed_read_operations():
    allowed = verify.allowed_queries(verify.rehearsal.load_migration())
    guard = verify.query_guard(allowed)
    for statement in allowed:
        assert statement.startswith('SELECT ') or statement in (verify.GRANTS, verify.SET_READ_ONLY)
        guard(None, None, statement, None, None, False)
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        guard(None, None, verify.IDENTITY, None, None, True)


def test_reported_seven_counters_match_fixtures():
    migration = verify.rehearsal.load_migration()
    expected = verify.expected_sequences(migration)
    assert {key: value for key, (_, _, value) in expected.items()} == {
        'PATIENT': 31, 'STAFF': 23, 'DEPARTMENT': 31, 'TEST': 23,
        'PANEL': 31, 'REJECTION_REASON': 23, 'REPORT_TEMPLATE': 31,
    }
    rows = [(key, prefix, padding, value, None) for key, (prefix, padding, value) in expected.items()]
    assert verify.check_sequence_state(rows, expected) == 'initial_seed_values'
    allocated = [(key, prefix, padding, value + 1, 'synthetic-time') for key, prefix, padding, value, _ in rows]
    assert verify.check_sequence_state(allocated, expected) == 'first_allocations_committed'
    with pytest.raises(AssertionError):
        verify.check_sequence_state(allocated[:1] + rows[1:], expected)
    with pytest.raises(AssertionError):
        verify.check_sequence_state(rows[:-1], expected)


def test_no_commit_or_migration_or_production_import_paths():
    tree = ast.parse(inspect.getsource(verify))
    calls = [node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert not set(calls) & {'commit', 'upgrade', 'downgrade', 'stamp', 'allocate_code', 'run_mysql', 'create_all'}
    imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module.startswith(('app.database', 'app.config', 'dotenv')) for module in imports)


def test_errors_are_redacted(environment, monkeypatch, capsys):
    def error(*args, **kwargs):
        raise RuntimeError('private-history ' + environment['RHU_CODE_TEST_PASSWORD'])
    monkeypatch.setattr(verify, 'run_read_only', error)
    assert verify.main(['--verify-read-only', '--authorize-existing-synthetic'], environ=environment) == 1
    output = capsys.readouterr().out
    assert 'private-history' not in output
    assert environment['RHU_CODE_TEST_PASSWORD'] not in output


class ScriptedResult:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def all(self):
        return self.rows

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]


class ScriptedConnection:
    def __init__(self, responses):
        self.responses = responses
        self.statements = []
        self.rollbacks = 0
        self.guard = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def execute(self, statement):
        sql = str(statement)
        if self.guard:
            self.guard(self, None, sql, None, None, False)
        self.statements.append(sql)
        assert sql in self.responses, 'Unexpected offline scripted query'
        return ScriptedResult(self.responses[sql])

    def scalars(self, statement):
        return iter(row[0] for row in self.execute(statement))

    def scalar(self, statement):
        return next(self.scalars(statement))

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def scripted_responses():
    from app.models import Base
    migration = verify.rehearsal.load_migration()
    responses = {
        verify.SET_READ_ONLY: [],
        verify.IDENTITY: [('rhu_labchain_dev', 'rhu_dev@localhost', 'rhu_dev@localhost', 3306, '8.0.36')],
        verify.READ_ONLY: [(1,)],
        verify.ROLES: [('NONE',)],
        verify.GRANTS: [('GRANT SELECT ON `rhu_labchain_dev`.* TO `rhu_dev`@`localhost`',)],
        verify.INVENTORY: [(name, 'InnoDB') for name in set(Base.metadata.tables) |
                          {'alembic_version', verify.rehearsal.MARKER}],
        verify.MARKER: [('a' * 32, 'success')],
        verify.VERSION: [(verify.rehearsal.HEAD,)],
        verify.SEQUENCES: [(key, prefix, padding, value, None) for key, (prefix, padding, value)
                           in verify.expected_sequences(migration).items()],
        verify.COLUMNS: [(table, column, 'utf8mb4_0900_ai_ci' if index % 2 else 'utf8mb4_unicode_ci')
                         for index, (_, _, _, table, column) in enumerate(migration.SEQUENCES)],
        verify.INDEXES: [(table, 'unique_code', 0, column, 1) for _, _, _, table, column in migration.SEQUENCES],
        verify.CONSTRAINTS: [
            ('ck_code_sequence_nonnegative_value', 'YES', '(`current_value` >= 0)'),
            ('ck_code_sequence_valid_padding', 'YES', '((`padding` >= 1) and (`padding` <= 16))'),
        ],
    }
    for _, prefix, _, table, column in migration.SEQUENCES:
        responses[f'SELECT HEX(`{column}`) FROM `{table}`'] = [
            (value.encode().hex().upper(),) for value in verify.rehearsal.fixture_values(prefix)]
    return responses


def test_full_read_only_path_uses_no_mutations_or_migrations(environment, scripted_responses, monkeypatch, capsys):
    from types import SimpleNamespace
    connection = ScriptedConnection(scripted_responses)
    disposed = []
    engine = SimpleNamespace(connect=lambda: connection, dispose=lambda: disposed.append(True))
    monkeypatch.setattr(sa, 'create_engine', lambda *a, **k: engine)  # Scripted engine only.
    monkeypatch.setattr(sa.event, 'listen', lambda conn, name, guard: setattr(conn, 'guard', guard))
    monkeypatch.setattr(verify.rehearsal, 'verify_worktree', lambda: None)
    assert verify.run_read_only(verify.rehearsal.load_config(environment), authorized=True) == 0
    assert connection.statements[:5] == [verify.SET_READ_ONLY, verify.IDENTITY, verify.READ_ONLY,
                                        verify.GRANTS, verify.ROLES]
    assert connection.rollbacks == 2
    assert connection.closed and disposed == [True]
    output = capsys.readouterr().out
    assert 'READ_ONLY_STATE_VERIFIED: counters=initial_seed_values' in output
    assert 'marker=initialization_only' in output
    assert 'full rehearsal remains incomplete' in output
    assert environment['RHU_CODE_TEST_PASSWORD'] not in output


@pytest.mark.parametrize('query,rows', [
    (verify.VERSION, [(verify.rehearsal.PARENT,)]),
    (verify.MARKER, [('a' * 32, 'seed-failure')]),
    (verify.CONSTRAINTS, []), (verify.INDEXES, []), (verify.COLUMNS, []),
    (verify.SEQUENCES, []),
    ('SELECT HEX(`patient_code`) FROM `patient`', [('0000',)]),
])
def test_changed_state_fails_without_repair(query, rows, scripted_responses):
    scripted_responses[query] = rows
    connection = ScriptedConnection(scripted_responses)
    with pytest.raises(AssertionError):
        verify.verify_state(connection, verify.rehearsal.load_migration(), verify.rehearsal.Progress())
    assert all(sql.startswith('SELECT ') for sql in connection.statements)


def test_write_privileges_stop_before_reading_fixture_data(environment, scripted_responses, monkeypatch):
    from types import SimpleNamespace
    scripted_responses[verify.GRANTS] = [('GRANT ALL PRIVILEGES ON `rhu_labchain_dev`.* TO `rhu_dev`@`localhost`',)]
    connection = ScriptedConnection(scripted_responses)
    monkeypatch.setattr(sa, 'create_engine', lambda *a, **k: SimpleNamespace(connect=lambda: connection, dispose=lambda: None))
    monkeypatch.setattr(sa.event, 'listen', lambda conn, name, guard: setattr(conn, 'guard', guard))
    monkeypatch.setattr(verify.rehearsal, 'verify_worktree', lambda: None)
    with pytest.raises(verify.rehearsal.SafetyRefusal):
        verify.run_read_only(verify.rehearsal.load_config(environment), authorized=True)
    assert verify.INVENTORY not in connection.statements
    assert verify.SEQUENCES not in connection.statements
    assert connection.closed
