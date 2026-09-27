"""Synthetic provisioning only: no live credentials or ledger calls in tests."""
import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

import pytest

NETWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NETWORK/'scripts'))
import provision_app_client as provision


@pytest.fixture(scope='module')
def original(tmp_path_factory):
    root = tmp_path_factory.mktemp('app-client-synthetic')/'network'
    root.mkdir(mode=0o700)
    for directory in ['scripts', 'config']:
        shutil.copytree(NETWORK/directory, root/directory)
    shutil.copyfile(NETWORK/'.env.single-vps.example', root/'.env.single-vps')
    (root/'tools').symlink_to(NETWORK/'tools', target_is_directory=True)
    # Existing fixture pattern creates a completely separate synthetic network.
    env = {**os.environ, 'PATH': str(NETWORK/'tools/bin') + os.pathsep + os.environ['PATH'],
           'FABRIC_CFG_PATH': str(NETWORK/'tools/config')}
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
        provision.single_vps.prepare(root)
    return root


@pytest.fixture
def network(original, tmp_path):
    root = tmp_path/'network'
    shutil.copytree(original, root, symlinks=True)
    subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    (root/'.gitignore').write_text('runtime/\ngenerated/\ntools/\n')
    return root


def test_pinned_extend_and_runtime_unchanged_idempotent(network):
    before = provision.snapshot(network/'runtime/single-vps')
    crypto = network/'generated/single-vps/crypto-config'
    original_crypto = provision.snapshot(crypto)
    with mock.patch.object(provision, 'run', wraps=provision.run) as calls:
        cert = provision.provision(network)
        extended = [call.args for call in calls.call_args_list if 'extend' in call.args]
        assert len(extended) == 1 and extended[0][0] == network/'tools/bin/cryptogen'
        assert not any('generate' in call.args for call in calls.call_args_list)
    after = provision.snapshot(crypto)
    assert all(after[path] == digest for path, digest in original_crypto.items())
    assert provision.snapshot(network/'runtime/single-vps') == before
    destination = network/'runtime/app-client-single-vps/org1'
    snapshot = provision.snapshot(destination)
    assert cert.parent == destination/'msp/signcerts'
    assert b'OU = client' in provision.run('openssl', 'x509', '-in', cert, '-noout', '-subject')
    assert len(list(destination.rglob('*_sk'))) == 1
    for path in destination.rglob('*'):
        assert (path.stat().st_mode & 0o777) == (0o700 if path.is_dir() else 0o600)
        if path.is_file() and path.parent.name != 'keystore': assert b'PRIVATE KEY' not in path.read_bytes()
    assert provision.provision(network) == cert
    assert provision.snapshot(destination) == snapshot
    assert provision.snapshot(network/'runtime/single-vps') == before
    assert subprocess.check_output(['git','-C',str(network),'ls-files','--others','--exclude-standard','runtime/']) == b''


@pytest.mark.parametrize('defect', ['ca_key', 'ca_cert', 'peer_key', 'runtime_root', 'runtime_manifest'])
def test_incomplete_or_untrusted_source_refused(network, defect):
    org = network/'generated/single-vps/crypto-config/peerOrganizations/org1.labchain.internal'
    if defect == 'ca_key': provision.one(org/'ca', '*_sk').unlink()
    if defect == 'ca_cert': provision.one(org/'ca', '*-cert.pem').unlink()
    if defect == 'peer_key': provision.one(org/'peers/peer1.org1.labchain.internal/msp/keystore').unlink()
    if defect == 'runtime_root': provision.one(org/'msp/cacerts').write_text('Synthetic invalid root')
    if defect == 'runtime_manifest': (network/'runtime/single-vps/COMPLETE').write_text('invalid')
    with pytest.raises((provision.ProvisionError, ValueError)):
        provision.provision(network)
    assert not (network/'runtime/app-client-single-vps/org1').exists()


@pytest.mark.parametrize('identity', ['users/Admin@org1.labchain.internal', 'peers/peer1.org1.labchain.internal'])
def test_admin_and_peer_cannot_be_application_identity(network, identity):
    org = network/'generated/single-vps/crypto-config/peerOrganizations/org1.labchain.internal'
    shutil.copytree(org/identity, org/f'users/{provision.USER}')
    with pytest.raises(provision.ProvisionError, match='CLIENT'):
        provision.provision(network)


@pytest.mark.parametrize('defect', ['key_mode', 'conflicting_cert', 'extra_material'])
def test_conflicting_runtime_refused(network, defect):
    provision.provision(network)
    destination = network/'runtime/app-client-single-vps/org1'
    if defect == 'key_mode': provision.one(destination/'msp/keystore').chmod(0o640)
    if defect == 'conflicting_cert': provision.one(destination/'msp/signcerts').write_text('invalid certificate')
    if defect == 'extra_material': (destination/'unexpected').write_text('not allowed')
    with pytest.raises(provision.ProvisionError): provision.provision(network)


def test_real_paths_ignored_and_shell_guard():
    for path in ['runtime/app-client-single-vps/org1/msp/keystore/client_sk',
                 'runtime/app-client-single-vps/org1/msp/signcerts/client.pem',
                 'generated/single-vps/crypto-config/peerOrganizations/org1.labchain.internal/users/User1@org1.labchain.internal/msp/keystore/key']:
        subprocess.run(['git','-C',str(NETWORK),'check-ignore','--quiet',str(NETWORK/path)], check=True)
    script = NETWORK/'scripts/provision-app-client-single-vps.sh'
    subprocess.run(['bash','-n',str(script)], check=True)
    assert 'set -euo pipefail' in script.read_text()
    assert '$NETWORK_DIR/tools/bin/cryptogen' in script.read_text()
    assert '2.5.16' in script.read_text()
