"""Offline rehearsal guards; network protection remains enabled by conftest."""

import ast
from dataclasses import replace
import inspect
from pathlib import Path
import socket
import sys

from alembic import command
import pytest
import sqlalchemy as sa

from scripts import mysql_migration_rehearsal as rehearsal


@pytest.fixture
def environment():
    return {
        'RHU_CODE_TEST_HOST': '127.0.0.1',
        'RHU_CODE_TEST_DATABASE': 'rhu_labchain_dev',
        'RHU_CODE_TEST_USER': 'rhu_dev',
        'RHU_CODE_TEST_PASSWORD': 'offline-only-sentinel',
    }


@pytest.fixture(autouse=True)
def prohibit_connections_and_migrations(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Offline preparation must not create engines or execute migrations')
    monkeypatch.setattr(sa, 'create_engine', forbidden)
    monkeypatch.setattr(command, 'upgrade', forbidden)
    monkeypatch.setattr(command, 'downgrade', forbidden)


@pytest.mark.parametrize('configured', [False, True])
def test_default_is_offline(configured, environment, capsys):
    assert rehearsal.main([], environ=environment if configured else {}) == 0
    assert 'SKIP' in capsys.readouterr().out


def test_check_validates_without_execution(environment, capsys):
    assert rehearsal.main(['--check'], environ=environment) == 0
    output = capsys.readouterr().out
    assert 'no connection attempted' in output
    assert environment['RHU_CODE_TEST_PASSWORD'] not in output


@pytest.mark.parametrize('missing', ['HOST', 'DATABASE', 'USER', 'PASSWORD'])
def test_missing_configuration_refuses(missing, environment):
    environment.pop('RHU_CODE_TEST_' + missing)
    assert rehearsal.main(['--check'], environ=environment) == 2


@pytest.mark.parametrize('name,value', [
    ('HOST', 'localhost'), ('HOST', '::1'), ('HOST', 'remote.invalid'),
    ('DATABASE', 'rhu_labchain'), ('DATABASE', 'rhu_labchain_dev_extra'),
    ('USER', 'root'), ('PORT', '3307'), ('PORT', 'bad'),
])
def test_wrong_target_refuses(name, value, environment):
    environment['RHU_CODE_TEST_' + name] = value
    assert rehearsal.main(['--check'], environ=environment) == 2


@pytest.mark.parametrize('flags', [[], ['--authorize-empty-database'], ['--writers-stopped']])
def test_partial_authorization_refuses(flags, environment):
    assert rehearsal.main(['--run', *flags], environ=environment) == 2


def test_direct_entry_rechecks_target(environment):
    config = replace(rehearsal.load_config(environment), database='rhu_labchain')
    with pytest.raises(rehearsal.SafetyRefusal):
        rehearsal.run_mysql(config, authorized=True, writers_stopped=True, scenario='success')


@pytest.mark.parametrize('authorized,stopped,scenario', [
    (False, True, 'success'), (True, False, 'success'), (True, True, 'unknown'),
])
def test_direct_entry_rechecks_authorization(authorized, stopped, scenario, environment):
    with pytest.raises(rehearsal.SafetyRefusal):
        rehearsal.run_mysql(rehearsal.load_config(environment), authorized=authorized,
                            writers_stopped=stopped, scenario=scenario)


def test_flag_required_before_engine(environment, monkeypatch):
    monkeypatch.delenv(rehearsal.FLAG, raising=False)
    with pytest.raises(rehearsal.SafetyRefusal, match='acknowledgement'):
        rehearsal.run_mysql(rehearsal.load_config(environment), authorized=True,
                            writers_stopped=True, scenario='success')


@pytest.mark.parametrize('change', ['root', 'env', 'branch'])
def test_worktree_guards(environment, monkeypatch, tmp_path, change):
    monkeypatch.setenv(rehearsal.FLAG, '1')
    monkeypatch.setattr(rehearsal, 'ROOT', tmp_path)
    if change != 'root':
        monkeypatch.setattr(rehearsal, 'EXPECTED_ROOT', tmp_path)
    if change == 'env':
        (tmp_path / '.env').touch()
    monkeypatch.setattr(rehearsal.subprocess, 'check_output', lambda *a, **k: 'main\n')
    with pytest.raises(rehearsal.SafetyRefusal):
        rehearsal.verify_authorization(rehearsal.load_config(environment), authorized=True,
                                       writers_stopped=True, scenario='success')


@pytest.mark.parametrize('field,value', [
    (0, 'rhu_labchain'), (1, 'root@localhost'), (1, 'rhu_dev@%'),
    (2, 'rhu_dev@remote'), (2, 'other@localhost'), (3, 3307),
    (4, '8.0.15'), (4, '10.11.0-MariaDB'), (4, 'unknown'),
])
def test_actual_server_identity_refuses(field, value):
    row = ['rhu_labchain_dev', 'rhu_dev@localhost', 'rhu_dev@127.0.0.1', 3306, '8.0.36']
    row[field] = value
    with pytest.raises(rehearsal.SafetyRefusal):
        rehearsal.verify_identity(row)


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1'])
def test_loopback_identity_accepted(host):
    rehearsal.verify_identity(('rhu_labchain_dev', 'rhu_dev@' + host,
                               'rhu_dev@' + host, 3306, '8.0.36'))


@pytest.mark.parametrize('objects,revision', [
    (['patient'], ()), (['unrelated'], ()), (['alembic_version'], (rehearsal.PARENT,)),
    (['code_sequence'], (rehearsal.HEAD,)), ([rehearsal.MARKER], ()), (1, ()),
    ([], (rehearsal.PARENT,)),
])
def test_existing_state_never_reused(objects, revision):
    with pytest.raises(rehearsal.SafetyRefusal):
        rehearsal.require_empty(objects, revision)


def test_empty_schema_accepted():
    rehearsal.require_empty([], ())


def test_exact_migrations_and_isolated_env_without_execution():
    before = sys.modules.get('app.database')
    sentinel_connection = object()
    with rehearsal.isolated_config(sentinel_connection) as config:
        folder = Path(config.get_main_option('script_location'))
        assert config.config_file_name is None
        assert config.get_main_option('sqlalchemy.url') is None
        assert config.attributes['verified_connection'] is sentinel_connection
        assert (folder / 'env.py').read_text() == rehearsal.ENVIRONMENT
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        source_config = Config()
        source_config.set_main_option('script_location', str(rehearsal.ROOT / 'migrations'))
        source = ScriptDirectory.from_config(source_config)
        selected = [source.get_revision(revision) for revision in rehearsal.REVISIONS]
        assert {path.name for path in (folder / 'versions').glob('*.py')} == {
            Path(item.path).name for item in selected
        }
        for item in selected:
            original = Path(item.path)
            assert (folder / 'versions' / original.name).read_bytes() == original.read_bytes()
        assert ScriptDirectory.from_config(config).get_heads() == [rehearsal.HEAD]
        # The later PDF revision stays in the repository, outside this A-only run.
        assert source.get_revision('20261018_01').down_revision == rehearsal.HEAD
        assert not (folder / 'versions' / Path(source.get_revision('20261018_01').path).name).exists()
    assert not folder.exists()
    assert sys.modules.get('app.database') is before


def test_pinned_ancestor_inventory_mismatch_refuses(monkeypatch):
    monkeypatch.setattr(rehearsal, 'REVISIONS', rehearsal.REVISIONS[:-1])
    with pytest.raises(AssertionError, match='Unexpected revision chain'):
        with rehearsal.isolated_config(object()):
            pytest.fail('A changed historical chain must not be accepted')


def test_explicit_dispatch_only_to_offline_stub(environment, monkeypatch):
    received = []
    monkeypatch.setattr(rehearsal, 'run_mysql', lambda config, **kw: received.append((config, kw)) or 0)
    assert rehearsal.main(['--run', '--authorize-empty-database', '--writers-stopped',
                           '--scenario', 'seed-failure'], environ=environment) == 0
    progress = received[0][1].pop('progress')
    assert isinstance(progress, rehearsal.Progress)
    assert received[0][1] == dict(authorized=True, writers_stopped=True, scenario='seed-failure')


def test_errors_do_not_print_credentials_or_sql(environment, monkeypatch, capsys):
    def failed(*args, **kwargs):
        raise RuntimeError(environment['RHU_CODE_TEST_PASSWORD'] + ' SELECT private_history')
    monkeypatch.setattr(rehearsal, 'run_mysql', failed)
    assert rehearsal.main(['--run', '--authorize-empty-database', '--writers-stopped'],
                          environ=environment) == 1
    output = capsys.readouterr().out
    assert 'RuntimeError' in output
    assert 'private_history' not in output
    assert environment['RHU_CODE_TEST_PASSWORD'] not in output


def test_static_configuration_and_cleanup_boundaries():
    source = inspect.getsource(rehearsal)
    for code in (source, rehearsal.ENVIRONMENT):
        imports = [node.module or '' for node in ast.walk(ast.parse(code)) if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith(('app.database', 'app.config', 'dotenv')) for name in imports)
    # Harness never resets a database or calls downgrade/stamp; historical upgrade
    # files are copied unchanged, and only command.upgrade is used.
    assert not any(word in source.upper() for word in ('DROP TABLE', 'TRUNCATE TABLE', 'DROP DATABASE'))
    assert 'command.stamp(' not in source
    assert 'command.downgrade(' not in source
    assert 'hide_parameters=True' in source
    assert "query={'charset': 'utf8mb4'}" in source


def test_repository_network_guard_remains_active():
    with pytest.raises(AssertionError, match='network'):
        socket.create_connection(('127.0.0.1', 3306))


@pytest.fixture
def native_check_error():
    import pymysql.err
    packet = b'\xff' + (3819).to_bytes(2, 'little') + b'#HY000Synthetic CHECK violation'
    with pytest.raises(pymysql.err.OperationalError) as raised:
        pymysql.err.raise_mysql_exception(packet)
    wrapped = sa.exc.DBAPIError.instance('private SQL', {'private': 'private-value'},
                                        raised.value, pymysql.err.Error, hide_parameters=True)
    assert isinstance(wrapped, sa.exc.OperationalError)
    return wrapped


def test_native_driver_check_classification(native_check_error):
    assert rehearsal.error_codes(native_check_error) == (3819, 'HY000')


class CheckConnection:
    def __init__(self, error):
        self.error = error
        self.actions = []

    def transaction(self, name):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            self.actions.append(name + ':enter')
            try:
                yield
            except Exception:
                self.actions.append(name + ':rollback')
                raise
            else:
                self.actions.append(name + ':release')
        return scope()

    def begin(self):
        return self.transaction('outer')

    def begin_nested(self):
        return self.transaction('savepoint')

    def execute(self, statement):
        self.actions.append(str(statement))
        if self.error is not None:
            raise self.error


def test_check_violation_accepts_native_operational_error_and_rolls_back_savepoints(native_check_error):
    connection = CheckConnection(native_check_error)
    rehearsal.validate_checks(connection, rehearsal.Progress(stage='success'))
    updates = [action for action in connection.actions if action.startswith('UPDATE')]
    assert len(updates) == 3
    assert 'current_value=-1' in updates[0]
    assert 'padding=0' in updates[1]
    assert 'padding=17' in updates[2]
    assert connection.actions.count('savepoint:rollback') == 3
    assert connection.actions.count('outer:release') == 3


@pytest.mark.parametrize('number', [1044, 1142, 1213, 2006, 2013, 1062])
def test_other_database_errors_are_not_suppressed(number):
    import pymysql.err
    error = sa.exc.OperationalError('private SQL', {}, pymysql.err.OperationalError(number, 'private'))
    connection = CheckConnection(error)
    with pytest.raises(sa.exc.OperationalError) as raised:
        rehearsal.validate_checks(connection, rehearsal.Progress(stage='success'))
    assert raised.value is error
    assert connection.actions[-2:] == ['savepoint:rollback', 'outer:rollback']


def test_unenforced_check_still_fails():
    with pytest.raises(AssertionError, match='not enforced'):
        rehearsal.validate_checks(CheckConnection(None), rehearsal.Progress(stage='success'))


def test_structured_diagnostics_redact_query_and_identifiers(native_check_error, capsys):
    progress = rehearsal.Progress('success', 'check_negative_counter', 'head_observed_after_upgrade')
    rehearsal.report_failure(native_check_error, progress)
    output = capsys.readouterr().out
    for expected in ('stage=success', 'substage=check_negative_counter', 'category=OperationalError',
                     'mysql_errno=3819', 'sqlstate=HY000', 'revision_state=head_observed_after_upgrade'):
        assert expected in output
    assert 'private' not in output
    assert 'Synthetic CHECK' not in output


@pytest.mark.parametrize('number,state', [('password', 'secret-long-value'), (True, 'abcde'), (999999, None)])
def test_invalid_structured_fields_never_echo_payloads(number, state):
    error = RuntimeError(number, 'sensitive message')
    error.sqlstate = state
    assert rehearsal.error_codes(error) == (None, None)


def test_unknown_revision_is_not_reported_as_a_success(native_check_error, capsys):
    rehearsal.report_failure(native_check_error, rehearsal.Progress('success', 'alembic_upgrade',
                                                                  'unknown_during_upgrade'))
    assert 'revision_state=unknown_during_upgrade' in capsys.readouterr().out


def test_failure_substage_retains_observed_head(monkeypatch):
    from types import SimpleNamespace
    import pymysql.err
    progress = rehearsal.Progress(stage='success')
    migration = rehearsal.load_migration()
    expected = {'PATIENT': ('PAT', 6, 31)}
    error = sa.exc.OperationalError('private SQL', {}, pymysql.err.OperationalError(1142, 'private'))

    class Connection:
        def rollback(self):
            pass

        def execute(self, statement):
            if str(statement).startswith('SELECT sequence_key'):
                return [('PATIENT', 'PAT', 6, 31)]
            raise error

    monkeypatch.setattr(rehearsal, 'historical_snapshot', lambda *a: {})
    monkeypatch.setattr(rehearsal, 'index_snapshot', lambda *a: {})
    monkeypatch.setattr(rehearsal, 'revision', lambda *a: (rehearsal.HEAD,))
    monkeypatch.setattr(sa, 'inspect', lambda *a: SimpleNamespace(has_table=lambda *a: True))
    # Explicit stub only: the actual Alembic environment is never invoked.
    monkeypatch.setattr(command, 'upgrade', lambda *a: None)
    with pytest.raises(sa.exc.OperationalError):
        rehearsal.upgrade_and_verify(Connection(), None, migration, expected, 'success', progress)
    assert progress.substage == 'constraint_names'
    assert progress.revision_state == 'head_observed_after_upgrade'
