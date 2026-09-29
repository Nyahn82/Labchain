"""CLI execution uses injected workers; never connect to application DB or Fabric."""
from unittest.mock import MagicMock
import signal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError
from app.cli import blockchain_worker as cli
from app.services.blockchain_adapter_service import DeliveryError


def prepare(monkeypatch, enabled=True):
    config = cli.WorkerSettings(blockchain_delivery_enabled=enabled)
    monkeypatch.setattr(cli, 'WorkerSettings', lambda: config)
    sessions = SimpleNamespace(kw={'bind': MagicMock()})
    monkeypatch.setattr(cli, 'worker_sessions', lambda _: sessions)
    monkeypatch.setattr(cli, 'reject_docker_privileges', lambda: None)
    monkeypatch.setattr(cli, 'GatewayAdapter', lambda _: object())


def test_disabled_never_opens_worker_or_requires_credentials(monkeypatch):
    prepare(monkeypatch, False)
    monkeypatch.setattr(cli, 'DeliveryWorker', lambda *a: pytest.fail('disabled worker must not instantiate'))
    assert cli.main(['--once']) == 0


def test_once_single_cycle(monkeypatch):
    prepare(monkeypatch)
    calls = []
    monkeypatch.setattr(cli, 'DeliveryWorker', lambda *a: SimpleNamespace(cycle=lambda stop: calls.append(stop.is_set())))
    assert cli.main(['--once']) == 0 and calls == [False]


def test_continuous_sigterm_finishes_cycle_and_stops(monkeypatch):
    prepare(monkeypatch)
    calls = []
    previous = signal.getsignal(signal.SIGTERM)
    def cycle(stop):
        calls.append('inflight')
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert stop.is_set()
        calls.append('finished')
    monkeypatch.setattr(cli, 'DeliveryWorker', lambda *a: SimpleNamespace(cycle=cycle))
    assert cli.main([]) == 0 and calls == ['inflight', 'finished']
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.parametrize('error,code', [(SQLAlchemyError('SYNTHETIC_PRIVATE SQL password'), 'DATABASE_UNAVAILABLE'),
    (DeliveryError('CONFIG_INVALID'), 'CONFIG_INVALID'), (RuntimeError('SYNTHETIC_PRIVATE'), 'INTERNAL_ERROR')])
def test_cli_safe_errors(monkeypatch, caplog, error, code):
    prepare(monkeypatch)
    def fail(*args):
        raise error
    monkeypatch.setattr(cli, 'DeliveryWorker', fail)
    assert cli.main(['--once']) == 1
    assert code in caplog.text and 'SYNTHETIC_PRIVATE' not in caplog.text


def test_no_docker_group_or_root_privileges(monkeypatch):
    monkeypatch.setattr(cli.os, 'access', lambda *args: False)
    monkeypatch.delenv('DOCKER_HOST', raising=False)
    monkeypatch.setattr(cli.grp, 'getgrnam', lambda _: SimpleNamespace(gr_gid=999))
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(cli.os, 'getegid', lambda: 1000)
    monkeypatch.setattr(cli.os, 'getgroups', lambda: [1000, 999])
    with pytest.raises(DeliveryError):
        cli.reject_docker_privileges()
    monkeypatch.setattr(cli.os, 'getgroups', lambda: [1000])
    cli.reject_docker_privileges()
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 0)
    with pytest.raises(DeliveryError):
        cli.reject_docker_privileges()


@pytest.mark.parametrize('socket_path', ['/run/docker.sock', '/var/run/docker.sock', '/run/user/1234/docker.sock', '/synthetic-runtime/docker.sock'])
@pytest.mark.parametrize('permission', [cli.os.R_OK, cli.os.W_OK])
def test_docker_socket_access_rejected_even_without_group(monkeypatch, socket_path, permission):
    def absent(_):
        raise KeyError()
    monkeypatch.setattr(cli.grp, 'getgrnam', absent)
    monkeypatch.setattr(cli.os, 'getuid', lambda: 1234)
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 1234)
    monkeypatch.setattr(cli.os, 'getgroups', lambda: [])
    monkeypatch.setattr(cli.os, 'access', lambda path, mode: str(path) == socket_path and mode == permission)
    monkeypatch.setenv('XDG_RUNTIME_DIR', '/synthetic-runtime')
    monkeypatch.delenv('DOCKER_HOST', raising=False)
    with pytest.raises(DeliveryError):
        cli.reject_docker_privileges()


def test_alternate_docker_endpoint_refused(monkeypatch):
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 1234)
    monkeypatch.setattr(cli.os, 'getuid', lambda: 1234)
    monkeypatch.setattr(cli.os, 'getgroups', lambda: [])
    monkeypatch.setenv('DOCKER_HOST', 'tcp://localhost:2375')
    with pytest.raises(DeliveryError):
        cli.reject_docker_privileges()


def test_bad_credentials_rejected_before_db_session_factory(monkeypatch):
    prepare(monkeypatch)
    def invalid(_):
        raise DeliveryError('CREDENTIAL_INVALID')
    monkeypatch.setattr(cli, 'GatewayAdapter', invalid)
    monkeypatch.setattr(cli, 'worker_sessions', lambda _: pytest.fail('credentials must precede DB claims'))
    assert cli.main(['--once']) == 1
