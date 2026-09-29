"""Deployment preparation uses a temporary repo and simulated OS administration.

No test creates a production account, changes group membership, installs a real
unit, reads production credentials or invokes a live worker/Gateway/database.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('worker_preparation_under_test', ROOT/'deploy/prepare_blockchain_worker.py')
prep = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prep
SPEC.loader.exec_module(prep)


def run(*args, cwd=None, env=None):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


class FakeHost(prep.Host):
    """Only filesystem changes under tmp_path; account/service actions are records."""
    def __init__(self):
        self.events = []
        self.owners = {}
        self.created = False
        self.root = True

    def is_root(self):
        return self.root

    def stopped(self):
        self.events.append('check_stopped_disabled')

    def account(self, paths):
        if not self.created:
            self.events.append('create_system_account')
            self.created = True
        return os.getuid(), os.getgid()

    def owner(self, path):
        return self.owners.get(Path(path), (0, 0))

    def secure(self, path, uid, gid, mode):
        assert str(path).startswith('/tmp/')
        self.owners[Path(path)] = (uid, gid)
        Path(path).chmod(mode)

    def validate_unit(self, source):
        self.events.append('verify_unit')
        assert 'User=rhu-labchain-worker' in source.read_text()

    def validate_worker(self, paths):
        self.events.append('verify_worker')
        # Actual offline cryptographic verification of the COPIED synthetic client.
        msp = paths.runtime / 'fabric-client/org1/msp'
        env = {'PATH': '/usr/bin:/bin',
            'BLOCKCHAIN_GATEWAY_TLS_CA_PATH': str(paths.runtime / 'tls/peer1-ca.crt'),
            'BLOCKCHAIN_CLIENT_CERT_PATH': str(msp / 'signcerts/client-cert.pem'),
            'BLOCKCHAIN_CLIENT_KEY_PATH': str(msp / 'keystore/client-key.pem')}
        assert json.loads(run('/usr/bin/node', ROOT/'blockchain/gateway-adapter/src/check-credentials.js', env=env)) == {'ok': True}

    def reload(self):
        self.events.append('daemon_reload')


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    paths = prep.Paths(repo, tmp_path/'var/lib/rhu-labchain', tmp_path/'etc/rhu-labchain', tmp_path/'etc/systemd/system')
    paths.state_parent.parent.mkdir(parents=True)
    paths.etc.parent.mkdir(parents=True)
    paths.units.mkdir(parents=True)
    paths.units.chmod(0o755)
    (repo/'deploy').mkdir()
    shutil.copyfile(ROOT/'deploy'/prep.UNIT, repo/'deploy'/prep.UNIT)
    shutil.copyfile(ROOT/'.gitignore', repo/'.gitignore')
    run('git', 'init', '-q', repo)
    for directory in [paths.source/'signcerts', paths.source/'keystore', paths.source/'cacerts', paths.source/'ca',
                      paths.public/'org1/msp/cacerts']:
        directory.mkdir(parents=True, mode=0o700)
        directory.chmod(0o700)
    ca = paths.source/'cacerts/org1-ca.pem'
    ca_key = tmp_path/'synthetic-ca-signing.key'
    run('openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
        '-nodes', '-keyout', ca_key, '-out', ca, '-days', '1', '-subj', '/CN=ca.org1.labchain.internal')
    key = paths.source/'keystore/client_sk'
    csr = tmp_path/'client.csr'
    run('openssl', 'req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
        '-nodes', '-keyout', key, '-out', csr, '-subj', '/OU=client/CN=SyntheticWorker')
    extensions = tmp_path/'leaf.ext'
    extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n')
    run('openssl', 'x509', '-req', '-in', csr, '-CA', ca, '-CAkey', ca_key, '-set_serial', '2',
        '-days', '1', '-extfile', extensions, '-out', paths.source/'signcerts/client.pem')
    key.chmod(0o600)
    shutil.copyfile(ca, paths.public/'org1/msp/cacerts/org1-ca.pem')
    shutil.copyfile(ca, paths.public/'org1-tls-ca.crt')
    # An extra CA signing key must never be copied by a recursive MSP copy.
    shutil.copyfile(ca_key, paths.source/'ca/never-copy-ca-signing.key')
    return paths, FakeHost()


def snapshot(path):
    return {str(p.relative_to(path)): (hashlib.sha256(p.read_bytes()).hexdigest(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
            for p in path.rglob('*') if p.is_file()}


def test_preparation_idempotent_client_only_and_no_secret_file(sandbox, capsys):
    paths, host = sandbox
    original = snapshot(paths.source)
    prep.prepare(paths, host)
    first = snapshot(paths.runtime)
    prep.prepare(paths, host)
    assert snapshot(paths.runtime) == first
    assert snapshot(paths.source) == original
    assert not paths.env.exists()
    assert host.events.count('create_system_account') == 1
    assert host.events.count('daemon_reload') == 2  # safe recovery after an interrupted reload
    assert set(first) == {'fabric-client/org1/msp/signcerts/client-cert.pem',
        'fabric-client/org1/msp/keystore/client-key.pem', 'fabric-client/org1/msp/cacerts/org1-ca.pem', 'tls/peer1-ca.crt'}
    for path in [paths.runtime, *paths.runtime.rglob('*')]:
        assert host.owner(path) == (os.getuid(), os.getgid())
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    assert host.owner(paths.etc) == (0, os.getgid()) and stat.S_IMODE(paths.etc.stat().st_mode) == 0o750
    assert host.owner(paths.units/prep.UNIT) == (0, 0)
    assert stat.S_IMODE((paths.units/prep.UNIT).stat().st_mode) == 0o644
    message = capsys.readouterr().out
    assert '/etc/rhu-labchain/blockchain-worker.env' in message and 'stopped' in message
    assert 'PRIVATE KEY' not in message
    assert not {'start', 'enable', 'restart', 'stop', 'disable'}.intersection(host.events)


def test_existing_env_is_never_read_or_changed(sandbox, monkeypatch):
    paths, host = sandbox
    prep.prepare(paths, host)
    paths.env.write_text('DB_PASSWORD=SYNTHETIC_SECRET\n')
    host.secure(paths.env, 0, os.getgid(), 0o640)
    original = Path.read_bytes
    def protected(path):
        assert path != paths.env, 'preparation must not read the password file'
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', protected)
    prep.prepare(paths, host)
    assert paths.env.read_text() == 'DB_PASSWORD=SYNTHETIC_SECRET\n'


@pytest.mark.parametrize('defect', ['key_mode', 'mismatched_key', 'tracked_key', 'symlink_source', 'different_trust_root'])
def test_bad_source_fails_before_account_operations(sandbox, defect):
    paths, host = sandbox
    key = paths.source/'keystore/client_sk'
    if defect == 'key_mode':
        key.chmod(0o644)
    elif defect == 'mismatched_key':
        key.write_bytes((paths.source/'ca/never-copy-ca-signing.key').read_bytes())
    elif defect == 'tracked_key':
        run('git', '-C', paths.repo, 'add', '-f', key)
    elif defect == 'symlink_source':
        key.unlink()
        key.symlink_to(paths.source/'ca/never-copy-ca-signing.key')
    else:
        (paths.public/'org1/msp/cacerts/org1-ca.pem').write_text('DIFFERENT_SYNTHETIC_ROOT')
    with pytest.raises((prep.PreparationError, OSError)):
        prep.prepare(paths, host)
    assert not host.created and not paths.runtime.exists()


@pytest.mark.parametrize('defect', ['different_identity', 'unexpected_ca_key', 'symlink_destination', 'bad_env_mode'])
def test_unsafe_rerun_refuses_without_overwriting_identity(sandbox, defect):
    paths, host = sandbox
    prep.prepare(paths, host)
    key = paths.runtime/'fabric-client/org1/msp/keystore/client-key.pem'
    if defect == 'different_identity':
        key.write_text('DIFFERENT_SYNTHETIC_KEY')
    elif defect == 'unexpected_ca_key':
        (paths.runtime/'ca-signing.key').write_text('SYNTHETIC_CA_PRIVATE')
    elif defect == 'symlink_destination':
        key.unlink()
        key.symlink_to(paths.source/'keystore/client_sk')
    else:
        paths.env.write_text('DB_PASSWORD=SYNTHETIC_SECRET')
        host.secure(paths.env, 0, os.getgid(), 0o644)
    original = key.read_bytes()
    with pytest.raises(prep.PreparationError):
        prep.prepare(paths, host)
    assert key.read_bytes() == original


def test_non_root_refused_before_mutation(sandbox):
    paths, host = sandbox
    host.root = False
    with pytest.raises(prep.PreparationError, match='requires root'):
        prep.prepare(paths, host)
    assert not host.events and not paths.runtime.exists()
    if os.geteuid() == 0:
        pytest.skip('shell non-root guard requires an unprivileged test runner')
    result = subprocess.run(['bash', str(ROOT/'deploy/prepare-blockchain-worker.sh')], capture_output=True, text=True)
    assert result.returncode == 1 and 'No changes made' in result.stderr


def unit_properties():
    # Duplicate InaccessiblePaths directives are deliberately additive in systemd.
    values = {}
    for line in (ROOT/'deploy'/prep.UNIT).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values.setdefault(key, []).append(value)
    return values


def test_dedicated_account_unit_and_inherited_subprocess_sandbox():
    unit = unit_properties()
    assert unit['User'] == unit['Group'] == ['rhu-labchain-worker']
    assert 'SupplementaryGroups' not in unit
    assert unit['EnvironmentFile'] == ['/etc/rhu-labchain/blockchain-worker.env']
    assert unit['WorkingDirectory'] == ['/opt/rhu-labchain']
    assert unit['ExecStart'] == ['/opt/rhu-labchain/.venv/bin/python -m app.cli.blockchain_worker']
    for name in ['NoNewPrivileges', 'PrivateTmp', 'ProtectHome', 'ProtectKernelTunables',
                 'ProtectKernelModules', 'ProtectControlGroups', 'RestrictSUIDSGID', 'LockPersonality']:
        assert unit[name] == ['true']
    assert unit['ProtectSystem'] == ['strict']
    assert unit['CapabilityBoundingSet'] == unit['AmbientCapabilities'] == ['']
    assert 'MemoryDenyWriteExecute' not in unit
    assert 'ReadWritePaths' not in unit
    assert 'PYTHONDONTWRITEBYTECODE=1' in unit['Environment']
    inaccessible = ' '.join(unit['InaccessiblePaths'])
    for path in ['/run/docker.sock', '/var/run/docker.sock', '/opt/rhu-labchain/.env',
                 '/opt/rhu-labchain/blockchain/network/runtime', '/opt/rhu-labchain/blockchain/network/generated']:
        assert path in inaccessible


def test_example_is_external_disabled_and_contains_only_placeholders():
    example = (ROOT/'deploy/blockchain-worker.env.example').read_text()
    assert 'BLOCKCHAIN_DELIVERY_ENABLED=false' in example
    assert 'DB_PASSWORD=REPLACE_WITH_REAL_DB_PASSWORD_OUTSIDE_GIT' in example
    assert 'DB_USER=REPLACE_WITH_APPROVED_DB_USER' in example
    assert 'BEGIN PRIVATE KEY' not in example and 'BEGIN CERTIFICATE' not in example
    assert 'MFA_SECRET_ENCRYPTION_KEY=' not in example
    assert '/var/lib/rhu-labchain/blockchain-worker/' in example
    from dotenv import dotenv_values
    from app.worker_config import WorkerSettings
    values = {key.lower(): value for key, value in dotenv_values(ROOT/'deploy/blockchain-worker.env.example').items()}
    values['blockchain_adapter_command'] = json.loads(values['blockchain_adapter_command'])
    settings = WorkerSettings(**values)
    assert settings.db_password.get_secret_value().startswith('REPLACE_')
    assert settings.blockchain_client_key_path.is_absolute()
    assert settings.blockchain_adapter_command[0] == '/usr/bin/node'


def test_worker_imports_and_disabled_cli_never_open_web_env_or_write_code(tmp_path):
    program = '''import os, sys
from pathlib import Path
root = Path.cwd()
def guard(event, args):
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            assert Path(os.fsdecode(path)) != root / '.env', 'web dotenv access'
        assert not (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)), 'unexpected write'
    assert event != 'socket.connect', 'unexpected network connection'
sys.addaudithook(guard)
from app.cli.blockchain_worker import main
assert 'app.config' not in sys.modules and 'app.database' not in sys.modules
assert main(['--once']) == 0
'''
    env = {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1', 'BLOCKCHAIN_DELIVERY_ENABLED': 'false',
        'DB_HOST': 'database.invalid', 'DB_NAME': 'synthetic', 'DB_USER': 'synthetic', 'DB_PASSWORD': 'synthetic'}
    run(ROOT/'.venv/bin/python', '-B', '-c', program, cwd=ROOT, env=env)
    run('/usr/bin/node', '--check', ROOT/'blockchain/gateway-adapter/src/cli.js', cwd=tmp_path, env={'PATH': '/usr/bin:/bin'})
    assert list(tmp_path.iterdir()) == []


def test_production_runtime_not_in_git_and_secret_copy_ignored():
    tracked = run('git', '-C', ROOT, 'ls-files', '--', '.env', 'blockchain-worker.env',
        'deploy/blockchain-worker.env', 'blockchain/network/runtime', 'blockchain/network/generated')
    assert not tracked.strip()
    run('git', '-C', ROOT, 'check-ignore', '--quiet', 'deploy/blockchain-worker.env')
    result = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--quiet', 'deploy/blockchain-worker.env.example'])
    assert result.returncode == 1


def test_real_host_never_mutates_services_other_than_reload(monkeypatch):
    calls = []
    def fake(argv, **kwargs):
        calls.append([str(x) for x in argv])
        return SimpleNamespace(returncode=3, stdout=b'', stderr=b'')
    monkeypatch.setattr(prep, 'run', fake)
    host = prep.Host()
    host.stopped()
    host.reload()
    assert calls == [['systemctl', 'is-active', '--quiet', prep.UNIT],
        ['systemctl', 'is-enabled', '--quiet', prep.UNIT], ['systemctl', 'daemon-reload']]


def account_mocks(monkeypatch, paths, *, groups=None, uid=987, shell='/usr/sbin/nologin', sudo_allowed=False, running=False):
    group = SimpleNamespace(gr_gid=987)
    user = SimpleNamespace(pw_uid=uid, pw_gid=987, pw_shell=shell, pw_dir=str(paths.runtime))
    monkeypatch.setattr(prep.grp, 'getgrnam', lambda _: group)
    monkeypatch.setattr(prep.pwd, 'getpwnam', lambda _: user)
    monkeypatch.setattr(prep.os, 'getgrouplist', lambda *a: groups if groups is not None else [987])
    commands = []
    def command(argv, **kwargs):
        commands.append([str(x) for x in argv])
        if argv[0] == 'passwd':
            return SimpleNamespace(returncode=0, stdout=b'rhu-labchain-worker L date 0 99999 7 -1', stderr=b'')
        if argv[0] == 'pgrep':
            return SimpleNamespace(returncode=0 if running else 1, stdout=b'', stderr=b'')
        if argv[0] == 'sudo':
            return SimpleNamespace(returncode=0 if sudo_allowed else 1, stdout=b'' if sudo_allowed else b'User is not allowed to run sudo', stderr=b'')
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    monkeypatch.setattr(prep, 'run', command)
    return commands, group, user


@pytest.mark.parametrize('bad', ['root', 'interactive', 'supplementary_docker', 'sudo', 'running_process'])
def test_account_refuses_existing_privileges_without_removing_groups(sandbox, monkeypatch, bad):
    paths, _ = sandbox
    kwargs = {'uid': 0} if bad == 'root' else {'shell': '/bin/bash'} if bad == 'interactive' else {'groups': [987, 999]} if bad == 'supplementary_docker' else {'running': True} if bad == 'running_process' else {'sudo_allowed': True}
    commands, _, _ = account_mocks(monkeypatch, paths, **kwargs)
    with pytest.raises(prep.PreparationError):
        prep.Host().account(paths)
    assert all(cmd[0] not in {'usermod', 'gpasswd', 'userdel', 'groupdel'} for cmd in commands)


def test_account_creation_commands_system_locked_nologin(sandbox, monkeypatch):
    paths, _ = sandbox
    commands, group, user = account_mocks(monkeypatch, paths)
    seen = {'group': False, 'user': False}
    def lookup(kind, value):
        if not seen[kind]:
            seen[kind] = True
            raise KeyError()
        return value
    monkeypatch.setattr(prep.grp, 'getgrnam', lambda _: lookup('group', group))
    monkeypatch.setattr(prep.pwd, 'getpwnam', lambda _: lookup('user', user))
    assert prep.Host().account(paths) == (987, 987)
    assert commands[0] == ['groupadd', '--system', prep.ACCOUNT]
    assert commands[1] == ['useradd', '--system', '--gid', prep.ACCOUNT, '--home-dir', str(paths.runtime),
        '--no-create-home', '--shell', '/usr/sbin/nologin', prep.ACCOUNT]
    assert all('rhuadmin' not in cmd and 'docker' not in cmd for cmd in commands)


def test_actual_claim_and_confirmation_do_not_import_web_settings():
    program = '''import hashlib, sys
from datetime import datetime
from uuid import uuid4
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from app.models import Base, BlockchainNode, BlockchainEvent
from app.services.blockchain_event_validation import canonicalize
from app.services.blockchain_delivery_service import DeliveryWorker
engine = create_engine('sqlite:///:memory:')
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, autoflush=False)
now = datetime(2026, 9, 29, 12)
reference = str(uuid4())
payload = canonicalize(event_type='REPORT_RELEASED', entity_reference=reference,
    report_version=1, artifact_sha256='a'*64, occurred_at=now, source_node='node1', source_msp='Org1MSP')
with factory.begin() as db:
    db.execute(insert(BlockchainNode.__table__).values(node_id=1, node_code='node1', port=7051, is_active=True))
    db.execute(insert(BlockchainEvent.__table__).values(event_id=1, event_uuid=str(uuid4()), origin_node_id=1,
        entity_type='REPORT', entity_id=1, entity_reference=reference, event_type='REPORT_RELEASED',
        canonical_payload=payload, record_hash=hashlib.sha256(payload.encode()).hexdigest(),
        event_status='PENDING', deduplication_key='REPORT_RELEASED:1', occurred_at=now,
        attempt_count=0, next_attempt_at=now, updated_at=now))
class Adapter:
    def call(self, request, timeout):
        if request['action'] == 'anchor_exists':
            return True
        assert request['action'] == 'read_anchor'
        return dict(claim.expected_anchor(), created_at='2026-09-29T12:00:01.000Z', transaction_id='b'*64)
worker = DeliveryWorker(factory, Adapter(), now=lambda: now)
claim = worker.claim()
assert worker.deliver(claim)
with factory() as db:
    assert db.scalar(select(BlockchainEvent.event_status)) == 'CONFIRMED'
assert 'app.config' not in sys.modules and 'app.database' not in sys.modules
'''
    run(ROOT/'.venv/bin/python', '-B', '-c', program, cwd=ROOT,
        env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
