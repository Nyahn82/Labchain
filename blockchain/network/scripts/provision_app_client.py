#!/usr/bin/env python3
"""Extend retained prototype crypto; publish only a dedicated Org1 client MSP."""
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import pwd
import grp
import shutil
import stat
import subprocess
import tempfile

import yaml
import single_vps

NETWORK = Path(__file__).resolve().parents[1]
USER = 'User1@org1.labchain.internal'


class ProvisionError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ProvisionError(message)


def run(*args):
    try:
        return subprocess.run([str(a) for a in args], check=True, capture_output=True, timeout=60).stdout
    except (subprocess.SubprocessError, OSError):
        raise ProvisionError('Credential/tool validation failed; inspect trusted configuration locally.') from None


def one(directory, pattern='*'):
    files = list(directory.glob(pattern))
    require(len(files) == 1 and files[0].is_file() and not files[0].is_symlink(), 'Required identity material is absent or ambiguous.')
    return files[0]


def snapshot(root):
    require(root.is_dir() and not root.is_symlink(), 'Original crypto hierarchy is missing.')
    result = {}
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'Symlinks are not allowed in crypto material.')
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def ca_material(org, kind):
    directory = org/kind
    cert, key = one(directory, '*-cert.pem'), one(directory, '*_sk')
    require(run('openssl', 'x509', '-in', cert, '-pubkey', '-noout') ==
            run('openssl', 'pkey', '-in', key, '-pubout'), 'CA certificate and signing key differ.')
    run('openssl', 'verify', '-CAfile', cert, cert)
    run('openssl', 'x509', '-in', cert, '-checkend', '86400', '-noout')
    return cert


def source_material(network):
    crypto = network/'generated/single-vps/crypto-config'
    snapshot(crypto)
    # Require the complete retained hierarchy. Never repair/regenerate missing nodes.
    for name, branch, nodes in [
        ('org1', 'peerOrganizations', ['peer1', 'peer2']),
        ('org2', 'peerOrganizations', ['peer3', 'peer4']),
        ('orderer', 'ordererOrganizations', ['orderer']),
    ]:
        org = crypto/branch/f'{name}.labchain.internal'
        ca = ca_material(org, 'ca')
        tls_ca = ca_material(org, 'tlsca')
        require(one(org/'msp/cacerts').read_bytes() == ca.read_bytes(), 'Original MSP root differs from its CA.')
        public = network/f'runtime/single-vps/public/{name}/msp'
        require(one(public/'cacerts').read_bytes() == ca.read_bytes(), 'Runtime MSP trust root differs from original CA.')
        require(one(public/'tlscacerts').read_bytes() == tls_ca.read_bytes(), 'Runtime TLS trust root differs from original CA.')
        one(org/f'users/Admin@{name}.labchain.internal/msp/signcerts')
        one(org/f'users/Admin@{name}.labchain.internal/msp/keystore')
        for node in nodes:
            category = 'orderers' if name == 'orderer' else 'peers'
            source = org/f'{category}/{node}.{name}.labchain.internal'
            live = network/('runtime/single-vps/orderer' if name == 'orderer' else f'runtime/single-vps/node{node[-1]}/peer')
            for leaf in ['msp/signcerts', 'msp/keystore', 'msp/cacerts', 'msp/tlscacerts']:
                require(one(source/leaf).read_bytes() == one(live/leaf).read_bytes(), 'Retained node identity differs from Phase 8A runtime.')
            for leaf in ['tls/server.crt', 'tls/server.key', 'tls/ca.crt']:
                require((source/leaf).read_bytes() == (live/leaf).read_bytes(), 'Retained node TLS material differs from Phase 8A runtime.')
    org1 = crypto/'peerOrganizations/org1.labchain.internal'
    return crypto, org1, one(org1/'ca', '*-cert.pem')


def validate_client(msp, ca, *, restricted=False):
    require(msp.is_dir() and not msp.is_symlink(), 'Application MSP is missing.')
    snapshot(msp)
    cert, key = one(msp/'signcerts'), one(msp/'keystore')
    require(one(msp/'cacerts').read_bytes() == ca.read_bytes(), 'Application MSP has an unexpected CA.')
    config = yaml.safe_load((msp/'config.yaml').read_text())
    ous = config['NodeOUs']
    require(ous['Enable'] is True and ous['ClientOUIdentifier']['OrganizationalUnitIdentifier'] == 'client', 'MSP does not enable the client role.')
    require(ous['ClientOUIdentifier']['Certificate'] == 'cacerts/' + ca.name, 'Client OU trust certificate is unexpected.')
    subject = run('openssl', 'x509', '-in', cert, '-noout', '-subject', '-nameopt', 'RFC2253').decode()
    fields = subject.strip().removeprefix('subject=').split(',')
    require('OU=client' in fields and not any(x in fields for x in ['OU=admin', 'OU=peer', 'OU=orderer']), 'Application signing identity must have CLIENT role.')
    run('openssl', 'verify', '-CAfile', ca, cert)
    run('openssl', 'x509', '-in', cert, '-checkend', '86400', '-noout')
    require(run('openssl', 'x509', '-in', cert, '-pubkey', '-noout') ==
            run('openssl', 'pkey', '-in', key, '-pubout'), 'Application certificate and private key differ.')
    require(stat.S_IMODE(key.stat().st_mode) == 0o600, 'Application private key must have mode 0600.')
    if restricted:
        uid, gid = pwd.getpwnam('rhuadmin').pw_uid, grp.getgrnam('rhuadmin').gr_gid
        allowed = {'signcerts', 'keystore', 'cacerts', 'tlscacerts', 'config.yaml'}
        require({p.name for p in msp.iterdir()} == allowed, 'Unexpected material in application MSP.')
        one(msp/'tlscacerts')
        for path in [msp.parent, msp, *msp.rglob('*')]:
            info = path.stat()
            require(info.st_uid == uid and info.st_gid == gid, 'Application material must belong to rhuadmin:rhuadmin.')
            require(stat.S_IMODE(info.st_mode) == (0o700 if path.is_dir() else 0o600), 'Application material permissions are not restricted.')
            if path.is_file() and path.parent.name != 'keystore':
                require(b'PRIVATE KEY' not in path.read_bytes(), 'Unexpected private material outside the client keystore.')
    return cert


def ignored(network, path):
    run('git', '-C', network, 'check-ignore', '--quiet', str(path))
    tracked = run('git', '-C', network, 'ls-files', '--', str(path))
    require(not tracked.strip(), 'Application credential path is tracked by Git.')


def validate_operator():
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'Linux x86_64 is required.')
    require(os.getuid() == pwd.getpwnam('rhuadmin').pw_uid and os.getgid() == grp.getgrnam('rhuadmin').gr_gid,
            'Run provisioning as rhuadmin:rhuadmin.')


def provision(network=NETWORK):
    validate_operator()
    binary = network/'tools/bin/cryptogen'
    require(b'Version: v2.5.16' in run(binary, 'version'), 'Pinned cryptogen 2.5.16 is required.')
    single_vps.read_config(network/'.env.single-vps')
    single_vps.validate_runtime(network)
    crypto, org1, ca = source_material(network)
    destination = network/'runtime/app-client-single-vps/org1'
    ignored(network, destination/'msp/keystore/client_sk')
    require(not destination.parent.is_symlink(), 'Client runtime parent cannot be a symlink.')
    source = org1/f'users/{USER}'
    if destination.exists():
        require(not destination.is_symlink() and {p.name for p in destination.iterdir()} == {'msp'}, 'Unexpected application runtime content.')
        require(source.is_dir(), 'Runtime client has no matching retained source identity.')
        validate_client(source/'msp', ca)
        cert = validate_client(destination/'msp', ca, restricted=True)
        for directory in ['signcerts', 'keystore', 'cacerts', 'tlscacerts']:
            require(one(source/'msp'/directory).read_bytes() == one(destination/'msp'/directory).read_bytes(), 'Conflicting runtime client identity.')
        require((source/'msp/config.yaml').read_bytes() == (destination/'msp/config.yaml').read_bytes(), 'Conflicting runtime MSP configuration.')
        ignored(network, destination)
        return cert
    require(not destination.is_symlink(), 'Application destination cannot be a symlink.')
    original = snapshot(crypto)
    if not source.exists():
        config = yaml.safe_load((network/'config/crypto-config.single-vps.yaml').read_text())
        orgs = [o for o in config['PeerOrgs'] if o['Domain'] == 'org1.labchain.internal']
        require(len(orgs) == 1 and orgs[0]['EnableNodeOUs'] is True and orgs[0]['Users']['Count'] == 0,
                'Expected reviewed single-VPS Org1 crypto configuration.')
        orgs[0]['Users']['Count'] = 1
        # Extend a private copy of the EXISTING hierarchy using its original CAs.
        # Verify every existing byte is unchanged before publishing only User1.
        with tempfile.TemporaryDirectory(prefix='.app-client-stage-', dir=crypto.parent) as temporary:
            stage = Path(temporary)
            hierarchy = stage/'crypto-config'
            shutil.copytree(crypto, hierarchy)
            config_path = stage/'extend.yaml'
            config_path.write_text(yaml.safe_dump(config))
            run(binary, 'extend', f'--config={config_path}', f'--input={hierarchy}')
            after = snapshot(hierarchy)
            require(all(after.get(name) == digest for name, digest in original.items()), 'cryptogen changed existing identities; no new identity published.')
            prefix = f'peerOrganizations/org1.labchain.internal/users/{USER}/'
            require(all(name.startswith(prefix) for name in after.keys() - original.keys()), 'cryptogen generated unexpected identities.')
            candidate = hierarchy/f'peerOrganizations/org1.labchain.internal/users/{USER}'
            validate_client(candidate/'msp', ca)
            require(snapshot(crypto) == original, 'Original hierarchy changed concurrently.')
            require(not source.exists(), 'Client source appeared concurrently; validate explicitly.')
            candidate.rename(source)
    validate_client(source/'msp', ca)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(stat.S_IMODE(destination.parent.stat().st_mode) == 0o700, 'Client runtime parent must have mode 0700.')
    with tempfile.TemporaryDirectory(prefix='.org1-stage-', dir=destination.parent) as temporary:
        stage = Path(temporary)/'org1'
        stage.mkdir(mode=0o700)
        msp = stage/'msp'
        msp.mkdir(mode=0o700)
        for directory in ['signcerts', 'keystore', 'cacerts', 'tlscacerts']:
            shutil.copytree(source/'msp'/directory, msp/directory)
        shutil.copyfile(source/'msp/config.yaml', msp/'config.yaml')
        for path in [stage, *stage.rglob('*')]:
            path.chmod(0o700 if path.is_dir() else 0o600)
        validate_client(msp, ca, restricted=True)
        require(not destination.exists(), 'Application destination appeared concurrently.')
        stage.rename(destination)
    ignored(network, destination)
    single_vps.validate_runtime(network)
    return validate_client(destination/'msp', ca, restricted=True)


def main():
    import sys
    if len(sys.argv) != 1:
        raise ProvisionError('This fixed-topology provisioning command accepts no arguments.')
    validate_operator()
    os.umask(0o077)
    # Runtime validation precedes even lock-file creation; lock is outside its manifest.
    single_vps.validate_runtime(NETWORK)
    with (NETWORK/'runtime/.app-client-single-vps.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cert = provision()
    print('Application identity ready: MSP=Org1MSP role=CLIENT')
    print(run('openssl', 'x509', '-in', cert, '-noout', '-subject', '-issuer', '-serial', '-enddate').decode().strip())


if __name__ == '__main__':
    try:
        main()
    except ProvisionError as error:
        import sys
        print('Client provisioning refused: ' + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        import sys
        print('Client provisioning refused: missing, conflicting, or invalid crypto/configuration. Preserve existing material and review locally.', file=sys.stderr)
        raise SystemExit(1) from None
