"""Offline harness checks under the unchanged repository network guard."""

import ast
from dataclasses import replace
import inspect
import socket

import pytest
import sqlalchemy

from scripts import mysql_auto_code_probe as probe


@pytest.fixture
def config_env():
    # Synthetic sentinel for offline tests only; never passed to a DB driver.
    return {
        "RHU_CODE_TEST_HOST": "127.0.0.1",
        "RHU_CODE_TEST_DATABASE": "rhu_labchain_dev",
        "RHU_CODE_TEST_USER": "rhu_dev",
        "RHU_CODE_TEST_PASSWORD": "offline-sentinel-%@:/",
    }


@pytest.fixture(autouse=True)
def forbid_engine_and_online_entry(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline validation attempted to create an engine or run MySQL")

    original_runner = probe.run_mysql
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    monkeypatch.setattr(probe, "run_mysql", forbidden)
    return original_runner


@pytest.mark.parametrize("configured", [False, True])
def test_default_skips_even_with_credentials(configured, config_env, capsys):
    assert probe.main([], environ=config_env if configured else {}) == 0
    assert "SKIP" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["--run", "--check"])
@pytest.mark.parametrize("missing", ["HOST", "DATABASE", "USER", "PASSWORD"])
def test_missing_runtime_setting_refuses_before_engine(mode, missing, config_env, capsys):
    config_env.pop("RHU_CODE_TEST_" + missing)
    assert probe.main([mode], environ=config_env) == 2
    assert "REFUSED" in capsys.readouterr().out


@pytest.mark.parametrize("name,value", [
    ("HOST", "localhost"), ("HOST", "::1"), ("HOST", "127.0.0.2"),
    ("HOST", "127.0.0.1 "), ("DATABASE", "rhu_labchain"),
    ("DATABASE", "rhu_labchain_dev.extra"), ("USER", "root"),
    ("USER", "rhu_dev@localhost"), ("PORT", "3307"), ("PORT", "invalid"),
])
def test_wrong_target_refuses_before_prompt_or_engine(name, value, config_env, monkeypatch, capsys):
    config_env["RHU_CODE_TEST_" + name] = value
    config_env.pop("RHU_CODE_TEST_PASSWORD")
    monkeypatch.setattr(probe.getpass, "getpass", lambda *_: pytest.fail("Prompted for an unsafe target"))
    assert probe.main(["--run", "--prompt-password"], environ=config_env) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_check_is_offline_and_password_is_never_displayed(config_env, capsys):
    config = probe.load_config(config_env)
    assert config.password == config_env["RHU_CODE_TEST_PASSWORD"]
    assert config.password not in repr(config)
    assert probe.main(["--check"], environ=config_env) == 0
    output = capsys.readouterr().out
    assert "no connection attempted" in output
    assert config.password not in output


def test_generic_database_environment_is_ignored(capsys):
    assert probe.main(["--run"], environ={
        "DATABASE_URL": "mysql+pymysql://ignored.invalid/ignored",
        "DB_HOST": "127.0.0.1", "DB_NAME": "rhu_labchain_dev", "DB_USER": "rhu_dev",
        "DB_PASSWORD": "offline-sentinel",
    }) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_prompt_requires_a_terminal(config_env, monkeypatch):
    config_env.pop("RHU_CODE_TEST_PASSWORD")
    monkeypatch.setattr(probe.sys.stdin, "isatty", lambda: False)
    assert probe.main(["--check", "--prompt-password"], environ=config_env) == 2


def test_secure_prompt_and_redacted_failure(config_env, monkeypatch, capsys):
    secret = config_env.pop("RHU_CODE_TEST_PASSWORD")
    monkeypatch.setattr(probe.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(probe.getpass, "getpass", lambda _: secret)
    assert probe.main(["--check", "--prompt-password"], environ=config_env) == 0

    def failed_prompt(_):
        raise RuntimeError(secret)

    monkeypatch.setattr(probe.getpass, "getpass", failed_prompt)
    assert probe.main(["--check", "--prompt-password"], environ=config_env) == 1
    assert secret not in capsys.readouterr().out


def test_insecure_getpass_fallback_is_refused(config_env, monkeypatch, capsys):
    config_env.pop("RHU_CODE_TEST_PASSWORD")
    monkeypatch.setattr(probe.sys.stdin, "isatty", lambda: True)

    def insecure_prompt(_):
        probe.warnings.warn("No echo control", probe.getpass.GetPassWarning)
        pytest.fail("An insecure password read was allowed")

    monkeypatch.setattr(probe.getpass, "getpass", insecure_prompt)
    assert probe.main(["--check", "--prompt-password"], environ=config_env) == 1
    assert "GetPassWarning" in capsys.readouterr().out


@pytest.mark.parametrize("name", probe.ALLOWED_TABLES)
def test_existing_reserved_table_refuses_even_among_unrelated_tables(name):
    with pytest.raises(probe.SafetyRefusal, match="already exists"):
        probe.check_available_tables(["unrelated_table", name])


def test_unrelated_tables_are_not_candidates_for_cleanup():
    probe.check_available_tables(["patient", "unrelated_table"])
    with pytest.raises(probe.SafetyRefusal, match="not owned"):
        probe.check_table_owner("patient", ["patient"], ("run-id", "InnoDB"), "run-id")


@pytest.mark.parametrize("owned,row", [
    ([], ("run-id", "InnoDB")), (["code_sequence"], None),
    (["code_sequence"], ("older-run", "InnoDB")),
    (["code_sequence"], ("run-id", "MyISAM")),
])
def test_ownership_and_engine_fail_closed(owned, row):
    with pytest.raises(probe.SafetyRefusal):
        probe.check_table_owner("code_sequence", owned, row, "run-id")


def test_only_current_run_innodb_table_is_owned():
    probe.check_table_owner("code_sequence", ["code_sequence"], ("run-id", "InnoDB"), "run-id")


def test_direct_online_entry_revalidates_target(config_env, forbid_engine_and_online_entry):
    config = replace(probe.load_config(config_env), database="rhu_labchain")
    with pytest.raises(probe.SafetyRefusal):
        forbid_engine_and_online_entry(config)


def test_explicit_run_dispatches_validated_configuration_to_stub(config_env, monkeypatch):
    received = []

    def offline_stub(config):
        config.validate()
        received.append(config)
        return 0

    monkeypatch.setattr(probe, "run_mysql", offline_stub)
    assert probe.main(["--run"], environ=config_env) == 0
    assert received == [probe.load_config(config_env)]


def test_model_ddl_and_migration_import_are_offline():
    database_module_before = probe.sys.modules.get("app.database")
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateTable
    from app.models.code_sequence import CodeSequence

    ddl = str(CreateTable(CodeSequence.__table__).compile(dialect=dialect()))
    assert "ENGINE=InnoDB" in ddl
    assert "PRIMARY KEY (sequence_key)" in ddl
    migration = probe.load_migration()
    assert migration.revision == "20261015_01"
    assert len(migration.SEQUENCES) == 7
    assert probe.sys.modules.get("app.database") is database_module_before


def test_static_import_and_database_operation_boundaries():
    tree = ast.parse(inspect.getsource(probe))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and name.startswith(("app.database", "app.config")) for name in imports)
    calls = [node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert not {"upgrade", "downgrade", "create_all", "drop_all"}.intersection(calls)
    assert probe.ALLOWED_TABLES == ("code_sequence", "auto_code_probe_record", "auto_code_probe_legacy")
    assert probe.WORKERS >= 20
    online = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_mysql")
    engine_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "create_engine"]
    assert len(engine_calls) == 1
    assert online.lineno < engine_calls[0].lineno < online.end_lineno


def test_repository_network_guard_remains_installed():
    # Inspect the existing guards; deliberately do not invoke socket operations.
    for guarded in (socket.socket.connect, socket.socket.connect_ex, socket.create_connection):
        assert guarded.__name__ == "deny_network"
