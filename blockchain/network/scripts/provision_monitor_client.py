#!/usr/bin/env python3
"""Fail-closed, offline User2 source provisioning; never publish into /etc."""
import argparse
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import tempfile

import yaml
import provision_app_client as app

NETWORK = Path(__file__).resolve().parents[1]
USER = 'User2@org1.labchain.internal'
PREFIX = f'peerOrganizations/org1.labchain.internal/users/{USER}'
RECEIPT = 'generated/single-vps/monitor-client-receipt.json'
ARCHIVE_SHA256 = '18c91e7f2f11b601e6622cc70454d568af897707ee9adf111e9fa91a233881bf'
Error = app.ProvisionError
require = app.require
run = app.run


def no_links(path):
    for part in [path, *path.parents]:
        require(not part.is_symlink(), 'Symlink path rejected.')


def tree(root):
    """File bytes and all directory/file modes; reject links and special files."""
    no_links(root)
    require(root.is_dir(), 'Required identity hierarchy is missing.')
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        info = path.lstat()
        kind = 'dir' if stat.S_ISDIR(info.st_mode) else 'file'
        require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'Symlink or special file rejected.')
        require(info.st_nlink == 1 if kind == 'file' else True, 'Hard-linked identity file rejected.')
        value = {'kind': kind, 'mode': stat.S_IMODE(info.st_mode)}
        if kind == 'file':
            require(info.st_size <= 32 * 1024 * 1024, 'Oversized identity file rejected.')
            value['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(root))] = value
    return result


def stamp(root):
    """Also detect same-byte replacements, mode changes and rename races."""
    return {str(p.relative_to(root)): (s.st_dev, s.st_ino, s.st_mtime_ns, s.st_ctime_ns)
            for p in [root, *sorted(root.rglob('*'))] for s in [p.lstat()]}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def pinned(network):
    binary = network/'tools/bin/cryptogen'
    archive = network/'tools/fabric-2.5.16.tar.gz'
    require(binary.is_file() and not binary.is_symlink() and archive.is_file() and not archive.is_symlink(),
            'Pinned cryptogen and its reviewed archive are required.')
    with archive.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == ARCHIVE_SHA256, 'Pinned tool archive checksum mismatch.')
    with tarfile.open(archive, 'r:gz') as bundle:
        entries = [m for m in bundle.getmembers() if m.name in {'bin/cryptogen', './bin/cryptogen'}]
        require(len(entries) == 1 and entries[0].isfile(), 'Pinned cryptogen archive member is ambiguous.')
        with bundle.extractfile(entries[0]) as stream:
            expected = hashlib.file_digest(stream, 'sha256').hexdigest()
    with binary.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == expected, 'Cryptogen differs from the pinned archive.')
    require(b'Version: v2.5.16' in run(binary, 'version'), 'Pinned cryptogen 2.5.16 is required.')
    return binary


def expected_files():
    return {'msp/config.yaml', f'msp/signcerts/{USER}-cert.pem', 'msp/keystore/priv_sk',
            'msp/cacerts/ca.org1.labchain.internal-cert.pem',
            'msp/tlscacerts/tlsca.org1.labchain.internal-cert.pem',
            'tls/client.crt', 'tls/client.key', 'tls/ca.crt'}


def validate_identity(source, org1):
    inventory = tree(source)
    require({p for p, v in inventory.items() if v['kind'] == 'file'} == expected_files(),
            'Unexpected or ambiguous User2 files.')
    # cryptogen emits an EMPTY admincerts directory even for NodeOU client MSPs.
    # No admin certificate is permitted by the exact file allowlist above.
    directories = {'.', 'msp', 'msp/signcerts', 'msp/keystore', 'msp/cacerts', 'msp/admincerts', 'msp/tlscacerts', 'tls'}
    require({p for p, v in inventory.items() if v['kind'] == 'dir'} == directories, 'Unexpected User2 directories.')
    require(all(v['mode'] == (0o700 if v['kind'] == 'dir' else 0o600) for v in inventory.values()),
            'User2 permissions must be directories 0700 and files 0600.')
    ca = app.one(org1/'ca', '*-cert.pem')
    cert = app.validate_client(source/'msp', ca)
    subject = run('openssl', 'x509', '-in', cert, '-noout', '-subject', '-nameopt', 'RFC2253').decode()
    require(f'CN={USER}' in subject.strip().removeprefix('subject=').split(','), 'Unexpected User2 certificate subject.')
    require(b'CA:FALSE' in run('openssl', 'x509', '-in', cert, '-noout', '-ext', 'basicConstraints'), 'Client must not be a CA.')
    user1 = org1/f'users/{app.USER}'
    first = app.one(user1/'msp/signcerts')
    require(cert.read_bytes() != first.read_bytes(), 'User2 certificate is not distinct from User1.')
    require(run('openssl', 'x509', '-in', cert, '-pubkey', '-noout') !=
            run('openssl', 'x509', '-in', first, '-pubkey', '-noout'), 'User2 signing key is not distinct from User1.')
    tls_ca = app.one(org1/'tlsca', '*-cert.pem')
    require((source/'tls/ca.crt').read_bytes() == tls_ca.read_bytes(), 'Unexpected User2 TLS CA.')
    require(app.one(source/'msp/tlscacerts').read_bytes() == tls_ca.read_bytes(), 'Unexpected User2 MSP TLS CA.')
    run('openssl', 'verify', '-purpose', 'sslclient', '-CAfile', tls_ca, source/'tls/client.crt')
    require(run('openssl', 'x509', '-in', source/'tls/client.crt', '-pubkey', '-noout') ==
            run('openssl', 'pkey', '-in', source/'tls/client.key', '-pubout'), 'User2 TLS certificate/key mismatch.')
    for name in expected_files() - {'msp/keystore/priv_sk', 'tls/client.key'}:
        require(b'PRIVATE KEY' not in (source/name).read_bytes(), 'Private material outside expected key files.')
    return cert


def tls_sources(network):
    runtime = network/'runtime/single-vps'
    return {**{f'peer{i}-ca.crt': runtime/f'node{i}/peer/tls/ca.crt' for i in range(1, 5)},
            'orderer-ca.crt': runtime/'public/orderer-tls-ca.crt'}


def baseline(network):
    roots = {'crypto': network/'generated/single-vps/crypto-config',
             'runtime': network/'runtime/single-vps', 'application': network/'runtime/app-client-single-vps/org1'}
    inventories = {name: tree(path) for name, path in roots.items()}
    app.single_vps.read_config(network/'.env.single-vps')
    app.single_vps.validate_runtime(network)
    crypto, org1, ca = app.source_material(network)
    app.validate_client(org1/f'users/{app.USER}/msp', ca)
    app.validate_client(roots['application']/'msp', ca, restricted=True)
    # Validate the existing application source/runtime pair without invoking its provisioner.
    for directory in ['signcerts', 'keystore', 'cacerts', 'tlscacerts']:
        require(app.one(org1/f'users/{app.USER}/msp'/directory).read_bytes() ==
                app.one(roots['application']/'msp'/directory).read_bytes(), 'Existing User1 runtime differs from source.')
    require((org1/f'users/{app.USER}/msp/config.yaml').read_bytes() ==
            (roots['application']/'msp/config.yaml').read_bytes(), 'Existing User1 MSP configuration differs.')
    for name, path in tls_sources(network).items():
        require(b'PRIVATE KEY' not in path.read_bytes(), 'TLS source is not public material.')
    require({name: tree(path) for name, path in roots.items()} == inventories, 'Material changed during validation.')
    return roots, inventories, {name: stamp(path) for name, path in roots.items()}


@contextmanager
def locked(network, *, owner=None):
    # Same lock as the original app provisioner's CLI; no change to User1 code.
    path = network/'runtime/.app-client-single-vps.lock'
    no_links(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == (os.getuid() if owner is None else owner)
                and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe provisioning lock.')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another identity provisioning operation holds the lock.') from None
        yield
    finally:
        os.close(fd)


def publish(candidate, source):
    """Linux atomic no-replace rename; never overwrite even an empty raced directory."""
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.renameat2(-100, os.fsencode(candidate), -100, os.fsencode(source), 1)
    if result != 0:
        raise Error('Source publication refused; destination appeared or atomic rename failed.')
    fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_receipt(path, data, *, create=False):
    if create:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.flush(); os.fsync(stream.fileno())
    else:
        fd, temporary = tempfile.mkstemp(prefix='.monitor-receipt-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, sort_keys=True, indent=2)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_receipt(network, inventories):
    path = network/RECEIPT
    no_links(path)
    require(path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_size <= 1024 * 1024,
            'User2 has no safe provisioning receipt; reconcile, do not adopt it.')
    receipt = json.loads(path.read_text())
    require(receipt.get('version') == 1 and receipt.get('state') == 'VERIFIED' and receipt.get('user') == USER,
            'Incomplete or unexpected User2 receipt; reconcile before proceeding.')
    require(receipt.get('after') == inventories, 'Identity material changed since User2 provisioning.')
    require(receipt.get('before') and all(inventories['crypto'].get(k) == v for k, v in receipt['before']['crypto'].items()),
            'Existing crypto preservation proof is invalid.')
    old = receipt['before']
    require(receipt.get('before_digest') == digest(old) and receipt.get('after_digest') == digest(inventories),
            'Receipt digest is inconsistent.')
    require(old['runtime'] == inventories['runtime'] and old['application'] == inventories['application'],
            'Existing runtime preservation proof is invalid.')
    new = inventories['crypto'].keys() - old['crypto'].keys()
    require(new and all(k == PREFIX or k.startswith(PREFIX + '/') for k in new), 'Unexpected identity additions in receipt.')
    return receipt


def provision(network=NETWORK, *, check_only=False):
    app.validate_operator()
    previous_umask = os.umask(0o077)
    try:
        # Read-only checks precede lock creation; no repair of retained material.
        baseline(network)
        with locked(network):
            binary = pinned(network)
            roots, before, stamps = baseline(network)
            crypto = roots['crypto']; org1 = crypto/'peerOrganizations/org1.labchain.internal'
            source = crypto/PREFIX; receipt_path = network/RECEIPT
            app.ignored(network, source)
            app.ignored(network, receipt_path)
            no_links(receipt_path)
            if source.exists():
                check_receipt(network, before)
                return validate_identity(source, org1)
            require(not receipt_path.exists(), 'Previous User2 attempt is incomplete; reconcile its receipt.')
            require(not check_only, 'User2 has not been provisioned.')
            config_path = network/'config/crypto-config.single-vps.yaml'
            no_links(config_path)
            config_bytes = config_path.read_bytes()
            config = yaml.safe_load(config_bytes)
            orgs = config.get('PeerOrgs', [])
            require(len(orgs) == 2 and orgs[0]['Domain'] == 'org1.labchain.internal'
                    and orgs[1]['Domain'] == 'org2.labchain.internal'
                    and all(o['Users']['Count'] == 0 and o['EnableNodeOUs'] is True for o in orgs),
                    'Expected reviewed single-VPS configuration with Users Count 0.')
            orgs[0]['Users']['Count'] = 2
            with tempfile.TemporaryDirectory(prefix='.monitor-client-stage-', dir=crypto.parent) as temporary:
                stage = Path(temporary); hierarchy = stage/'crypto-config'
                shutil.copytree(crypto, hierarchy)
                extension = stage/'extend.yaml'; extension.write_text(yaml.safe_dump(config))
                require(tree(hierarchy) == before['crypto'], 'Private copy differs from retained hierarchy.')
                run(binary, 'extend', f'--config={extension}', f'--input={hierarchy}')
                after = tree(hierarchy)
                require(all(after.get(k) == v for k, v in before['crypto'].items()), 'cryptogen changed existing material.')
                new = after.keys() - before['crypto'].keys()
                require(new and all(k == PREFIX or k.startswith(PREFIX + '/') for k in new), 'Unexpected generated files or identities.')
                candidate = hierarchy/PREFIX
                validate_identity(candidate, hierarchy/'peerOrganizations/org1.labchain.internal')
                require(config_path.read_bytes() == config_bytes, 'Reviewed configuration changed concurrently.')
                require({name: tree(path) for name, path in roots.items()} == before
                        and {name: stamp(path) for name, path in roots.items()} == stamps,
                        'Retained identity material changed concurrently; nothing published.')
                record = {'version': 1, 'state': 'PENDING', 'user': USER, 'before': before,
                          'before_digest': digest(before), 'candidate': tree(candidate)}
                write_receipt(receipt_path, record, create=True)
                # Durable receipt precedes publication. A crash never permits silent adoption.
                publish(candidate, source)
                roots, final, _ = baseline(network)
                expected = {**before, 'crypto': after}
                require(final == expected, 'Concurrent or unexpected change after publication; reconcile receipt.')
                cert = validate_identity(source, org1)
                record.update(state='VERIFIED', after=final, after_digest=digest(final))
                write_receipt(receipt_path, record)
                app.ignored(network, source)
                return cert
    finally:
        os.umask(previous_umask)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify an existing receipted identity only; do not extend')
    args = parser.parse_args(argv)
    try:
        cert = provision(check_only=args.check)
        print('Monitor source verified: User2; Org1MSP; OU=client; distinct from User1.')
        print('Existing retained and runtime identities preserved; no deployment performed.')
        print('Certificate SHA-256: ' + hashlib.sha256(cert.read_bytes()).hexdigest())
        return 0
    except Error as exc:
        print('Monitor provisioning refused: ' + str(exc), file=sys.stderr)
    except Exception:
        print('Monitor provisioning refused: invalid or concurrent state. Preserve material and reconcile locally.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
