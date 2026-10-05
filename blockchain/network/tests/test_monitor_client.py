"""Real pinned cryptogen on isolated synthetic hierarchies; no live material."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from unittest import mock

import pytest
import yaml

NETWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NETWORK/'scripts'))
import provision_app_client as app
import provision_monitor_client as monitor
from test_app_client import original, network


@pytest.fixture
def prepared(network):
    app.provision(network)
    return network


def source(network):
    return network/'generated/single-vps/crypto-config'/monitor.PREFIX


def test_real_count_two_extension_preserves_user1_and_all_runtime_bytes(prepared, capsys):
    roots, before, _ = monitor.baseline(prepared)
    config_before = (prepared/'config/crypto-config.single-vps.yaml').read_bytes()
    original_run = monitor.run
    calls = []
    def run(*args):
        calls.append(args)
        if 'extend' in args:
            config = Path(next(str(a).removeprefix('--config=') for a in args if str(a).startswith('--config=')))
            assert [o['Users']['Count'] for o in yaml.safe_load(config.read_text())['PeerOrgs']] == [2, 0]
        return original_run(*args)
    with mock.patch.object(monitor, 'run', side_effect=run):
        cert = monitor.provision(prepared)
    assert sum('extend' in c for c in calls) == 1
    assert not any('generate' in c for c in calls)
    _, after, _ = monitor.baseline(prepared)
    assert all(after['crypto'][p] == v for p, v in before['crypto'].items())
    assert after['runtime'] == before['runtime'] and after['application'] == before['application']
    assert all(p == monitor.PREFIX or p.startswith(monitor.PREFIX + '/') for p in after['crypto'].keys() - before['crypto'].keys())
    assert (prepared/'config/crypto-config.single-vps.yaml').read_bytes() == config_before
    assert cert == source(prepared)/f'msp/signcerts/{monitor.USER}-cert.pem'
    assert stat.S_IMODE((source(prepared)/'msp/keystore/priv_sk').stat().st_mode) == 0o600
    subject = app.run('openssl', 'x509', '-in', cert, '-noout', '-subject', '-nameopt', 'RFC2253').decode()
    assert 'OU=client' in subject and not any(x in subject for x in ['OU=admin', 'OU=peer', 'OU=orderer'])
    org = roots['crypto']/'peerOrganizations/org1.labchain.internal'
    assert monitor.validate_identity(source(prepared), org) == cert  # Chain, subject, key match and distinctness.
    assert app.one(org/f'users/{app.USER}/msp/signcerts').read_bytes() != cert.read_bytes()
    saved = monitor.tree(source(prepared))
    with mock.patch.object(monitor, 'run', wraps=monitor.run) as repeat:
        assert monitor.provision(prepared) == cert
        assert not any('extend' in c.args for c in repeat.call_args_list)
    assert monitor.tree(source(prepared)) == saved
    assert monitor.provision(prepared, check_only=True) == cert
    app.single_vps.validate_runtime(prepared)
    assert 'PRIVATE KEY' not in capsys.readouterr().out


def test_unknown_existing_user2_not_adopted(prepared):
    user1 = source(prepared).parent/app.USER
    shutil.copytree(user1, source(prepared))
    before = monitor.tree(source(prepared))
    with pytest.raises(monitor.Error, match='receipt'):
        monitor.provision(prepared)
    assert monitor.tree(source(prepared)) == before


@pytest.mark.parametrize('defect', ['outside-file', 'inside-file', 'empty-directory', 'user1-change', 'concurrent-crypto', 'concurrent-runtime', 'key-mode', 'wrong-key', 'wrong-cert'])
def test_bad_extension_and_concurrent_changes_fail_closed(prepared, defect):
    original_run = monitor.run
    def run(*args):
        value = original_run(*args)
        if 'extend' in args:
            hierarchy = Path(next(str(a).removeprefix('--input=') for a in args if str(a).startswith('--input=')))
            candidate = hierarchy/monitor.PREFIX
            if defect == 'outside-file': (hierarchy/'unexpected').write_text('synthetic')
            if defect == 'inside-file': (candidate/'unexpected').write_text('synthetic')
            if defect == 'empty-directory': (candidate/'extra').mkdir()
            if defect == 'user1-change': app.one(candidate.parent/app.USER/'msp/signcerts').write_text('synthetic modification')
            if defect == 'concurrent-crypto': (source(prepared).parent/'concurrent').write_text('synthetic modification')
            if defect == 'concurrent-runtime': (prepared/'runtime/single-vps/COMPLETE').write_text('synthetic modification')
            if defect == 'key-mode': (candidate/'msp/keystore/priv_sk').chmod(0o644)
            if defect == 'wrong-key': shutil.copyfile(candidate/'tls/client.key', candidate/'msp/keystore/priv_sk')
            if defect == 'wrong-cert': shutil.copyfile(app.one(candidate.parent/app.USER/'msp/signcerts'), app.one(candidate/'msp/signcerts'))
        return value
    with mock.patch.object(monitor, 'run', side_effect=run), pytest.raises(monitor.Error):
        monitor.provision(prepared)
    assert not source(prepared).exists()
    assert not (prepared/monitor.RECEIPT).exists()


@pytest.mark.parametrize('where', ['crypto', 'runtime', 'app', 'source', 'lock'])
def test_symlinks_rejected(prepared, where):
    choices = {'crypto': prepared/'generated/single-vps/crypto-config',
               'runtime': prepared/'runtime/single-vps',
               'app': prepared/'runtime/app-client-single-vps/org1'}
    if where in choices:
        parent = choices[where]
        (parent/'symlink').symlink_to('/tmp')
    elif where == 'source':
        source(prepared).symlink_to(source(prepared).parent/app.USER, target_is_directory=True)
    else:
        (prepared/'runtime/.app-client-single-vps.lock').symlink_to('/tmp')
    with pytest.raises(monitor.Error): monitor.provision(prepared)


def test_lock_prevents_parallel_publication(prepared):
    lock = prepared/'runtime/.app-client-single-vps.lock'
    with lock.open('w') as stream:
        lock.chmod(0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(monitor.Error, match='holds the lock'):
            monitor.provision(prepared)
    assert not source(prepared).exists()


def test_incomplete_receipt_never_replays_or_adopts(prepared):
    with mock.patch.object(monitor, 'publish', side_effect=monitor.Error('Synthetic publish failure')):
        with pytest.raises(monitor.Error): monitor.provision(prepared)
    assert json.loads((prepared/monitor.RECEIPT).read_text())['state'] == 'PENDING'
    assert not source(prepared).exists()
    with pytest.raises(monitor.Error, match='incomplete'): monitor.provision(prepared)


def test_atomic_publish_does_not_replace_raced_empty_directory(tmp_path):
    candidate, target = tmp_path/'candidate', tmp_path/'target'
    candidate.mkdir(); target.mkdir()
    with pytest.raises(monitor.Error, match='publication refused'):
        monitor.publish(candidate, target)
    assert candidate.is_dir() and target.is_dir()


def test_check_only_never_extends_missing_user(prepared):
    with mock.patch.object(monitor, 'run', wraps=monitor.run) as calls:
        with pytest.raises(monitor.Error, match='not been provisioned'):
            monitor.provision(prepared, check_only=True)
    assert not any('extend' in c.args for c in calls.call_args_list)


def test_private_subprocess_error_not_printed(capsys):
    with mock.patch.object(monitor, 'provision', side_effect=RuntimeError('PRIVATE KEY synthetic secret')):
        assert monitor.main([]) == 1
    captured = capsys.readouterr()
    assert 'PRIVATE KEY' not in captured.out + captured.err


def test_paths_ignored_tls_public_mapping_and_shell():
    for path in [NETWORK/'generated/single-vps/crypto-config'/monitor.PREFIX, NETWORK/monitor.RECEIPT]:
        app.ignored(NETWORK, path)
    paths = monitor.tls_sources(NETWORK)
    assert len(paths) == 5 and all(p.name in {'ca.crt', 'orderer-tls-ca.crt'} for p in paths.values())
    assert not any(p.suffix == '.key' for p in paths.values())
    subprocess.run(['bash', '-n', str(NETWORK/'scripts/provision-monitor-client-single-vps.sh')], check=True)


def test_later_install_staging_contains_only_one_private_key_and_validates_with_adapter(prepared, tmp_path):
    monitor.provision(prepared)
    filename = NETWORK.parents[1]/'deploy/install_monitor_identity.py'
    spec = importlib.util.spec_from_file_location('monitor_installer', filename)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    _, before, _ = monitor.baseline(prepared)
    stage = installer.build_stage(prepared, tmp_path/'install-stage', os.getuid(), os.getgid())
    keys = [p for p in stage.rglob('*') if p.is_file() and b'PRIVATE KEY' in p.read_bytes()]
    assert keys == [stage/'msp/keystore/client.key']
    for p in [stage, *stage.rglob('*')]:
        assert stat.S_IMODE(p.stat().st_mode) == (0o700 if p.is_dir() else 0o600)
        assert p.stat().st_uid == os.getuid()
    for name, public in monitor.tls_sources(prepared).items():
        assert (stage/'tls'/name).read_bytes() == public.read_bytes()
    check = subprocess.run(['/usr/bin/node', str(NETWORK.parent/'gateway-adapter/src/check-credentials.js')],
        capture_output=True, text=True, env={'PATH': '/usr/bin:/bin',
            'BLOCKCHAIN_CLIENT_CERT_PATH': str(stage/'msp/signcerts/client.crt'),
            'BLOCKCHAIN_CLIENT_KEY_PATH': str(stage/'msp/keystore/client.key'),
            'BLOCKCHAIN_GATEWAY_TLS_CA_PATH': str(stage/'tls/peer1-ca.crt')})
    assert check.returncode == 0, 'Offline Node credential validation failed.'
    assert 'PRIVATE KEY' not in check.stdout + check.stderr
    assert monitor.baseline(prepared)[1] == before


def test_receipted_source_tampering_rejected(prepared):
    monitor.provision(prepared)
    (source(prepared)/'msp/keystore/priv_sk').chmod(0o644)
    with pytest.raises(monitor.Error, match='changed since'):
        monitor.provision(prepared)
