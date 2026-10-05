#!/usr/bin/env python3
"""Later deployment only: install verified User2, never create accounts or start services.

Default is a read-only prerequisite check. --execute requires root and an already
created rhu-labchain-monitor user/group. The target is fixed and must not exist.
"""
import argparse
import grp
import os
from pathlib import Path
import pwd
import shutil
import sys
import tempfile

NETWORK = Path(__file__).resolve().parents[1]/'blockchain/network'
sys.path.insert(0, str(NETWORK/'scripts'))
import provision_monitor_client as monitor

TARGET = Path('/etc/rhu-labchain/monitor-identity')


def verified_source(network):
    roots, inventory, stamps = monitor.baseline(network)
    monitor.check_receipt(network, inventory)
    source = roots['crypto']/monitor.PREFIX
    monitor.validate_identity(source, roots['crypto']/'peerOrganizations/org1.labchain.internal')
    return source, roots, inventory, stamps


def build_stage(network, stage, uid, gid):
    """Fixed allowlist: one signing key, client MSP and public TLS CAs only."""
    source, roots, before, stamps = verified_source(network)
    paths = {
        'msp/signcerts/client.crt': source/f'msp/signcerts/{monitor.USER}-cert.pem',
        'msp/keystore/client.key': source/'msp/keystore/priv_sk',
        'msp/config.yaml': source/'msp/config.yaml',
        'msp/cacerts/ca.org1.labchain.internal-cert.pem': source/'msp/cacerts/ca.org1.labchain.internal-cert.pem',
        'msp/tlscacerts/tlsca.org1.labchain.internal-cert.pem': source/'msp/tlscacerts/tlsca.org1.labchain.internal-cert.pem',
        **{f'tls/{name}': path for name, path in monitor.tls_sources(network).items()},
    }
    monitor.require(not stage.exists(), 'Install staging destination already exists.')
    stage.mkdir(mode=0o700)
    for relative, original in paths.items():
        target = stage/relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Sources have already passed strict no-link inventory and receipt validation.
        with original.open('rb') as source_file, target.open('xb') as target_file:
            shutil.copyfileobj(source_file, target_file)
            target_file.flush(); os.fsync(target_file.fileno())
        target.chmod(0o600)
        monitor.require(original.read_bytes() == target.read_bytes(), 'Staged identity differs from source.')
        if relative != 'msp/keystore/client.key':
            monitor.require(b'PRIVATE KEY' not in target.read_bytes(), 'Unexpected key outside client keystore.')
    monitor.app.validate_client(stage/'msp', stage/'msp/cacerts/ca.org1.labchain.internal-cert.pem')
    monitor.require({name: monitor.tree(path) for name, path in roots.items()} == before
                    and {name: monitor.stamp(path) for name, path in roots.items()} == stamps,
                    'Source changed during install staging.')
    for path in [stage, *stage.rglob('*')]:
        os.chown(path, uid, gid)
        path.chmod(0o700 if path.is_dir() else 0o600)
    return stage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        monitor.require(os.geteuid() == 0, 'Run the later installer as root.')
        account = pwd.getpwnam('rhu-labchain-monitor')
        group = grp.getgrnam('rhu-labchain-monitor')
        operator_uid = pwd.getpwnam('rhuadmin').pw_uid
        monitor.require(account.pw_gid == group.gr_gid and account.pw_uid not in {0, operator_uid},
                        'Monitor account/group must be distinct from root and the FastAPI operator.')
        monitor.no_links(TARGET)
        monitor.require(not TARGET.exists(), 'Install target already exists; reconcile instead of overwriting.')
        monitor.require(TARGET.parent.is_dir(), 'Parent /etc/rhu-labchain must already exist.')
        # Provisioning must have completed as rhuadmin; root never creates a new lock.
        lock = NETWORK/'runtime/.app-client-single-vps.lock'
        monitor.require(lock.is_file(), 'Provisioning lock is absent; provision User2 first.')
        with monitor.locked(NETWORK, owner=operator_uid):
            verified_source(NETWORK)
            if not args.execute:
                print('Install prerequisites verified. No files copied; use --execute only in an authorized deployment.')
                return 0
            os.umask(0o077)
            with tempfile.TemporaryDirectory(prefix='.monitor-identity-stage-', dir=TARGET.parent) as temporary:
                stage = build_stage(NETWORK, Path(temporary)/'identity', account.pw_uid, group.gr_gid)
                monitor.publish(stage, TARGET)
        print('Monitor identity installed with private owner-only access. No services started.')
        return 0
    except monitor.Error as exc:
        print('Monitor install refused: ' + str(exc), file=sys.stderr)
    except Exception:
        print('Monitor install refused: missing account or invalid material; details withheld.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
