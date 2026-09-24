#!/usr/bin/env python3
"""Offline single-VPS configuration, prototype bootstrap and deployment guards."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

NETWORK = Path(__file__).resolve().parents[1]
EXPECTED = {'DEPLOYMENT_MODE': 'single-vps', 'FABRIC_VERSION': '2.5.16'}
PEER_CFG_PATH = '/etc/hyperledger/fabric'
CCAAS_BUILDERS = [{'name': 'ccaas_builder', 'path': '/opt/hyperledger/ccaas_builder',
                   'propagateEnvironment': ['CHAINCODE_AS_A_SERVICE_BUILDER_CONFIG']}]


def read_config(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or key not in EXPECTED or key in values or value != EXPECTED[key]:
            raise ValueError('Use only the reviewed single-VPS mode and Fabric version; plain KEY=value.')
        values[key] = value
    if values != EXPECTED:
        raise ValueError('Missing shared single-VPS configuration.')
    return values


def fingerprint():
    data = Path('/etc/machine-id').read_bytes()
    if not data.strip():
        raise ValueError('A non-empty host machine-id is required.')
    return hashlib.sha256(data).hexdigest()


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, **kwargs)


def load_packaging():
    spec = importlib.util.spec_from_file_location('ccaas_package', NETWORK/'scripts/package-chaincode.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_runtime(network=NETWORK):
    root = network/'runtime/single-vps'
    if (root/'host-fingerprint').read_text().strip() != fingerprint():
        raise ValueError('Prepared deployment belongs to another host; explicit fenced recovery is required.')
    if (root/'COMPLETE').read_text().strip() != 'single-vps-v1':
        raise ValueError('Incomplete single-VPS preparation; preserve and investigate.')
    manifest = json.loads((root/'manifest.json').read_text())
    actual = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*') if p.is_file()
              and p.name not in ('manifest.json', 'host-fingerprint', 'COMPLETE')}
    if actual != manifest:
        raise ValueError('Prepared identity/artifact manifest changed; review recovery or certificate renewal explicitly.')
    keys = []
    for i in range(1, 5):
        peer = root/f'node{i}/peer'
        keys += [next((peer/'msp/keystore').glob('*')).read_bytes(), (peer/'tls/server.key').read_bytes(),
                 (root/f'node{i}/chaincode/tls/server.key').read_bytes()]
        for cert, hostname in [(peer/'tls/server.crt', f'peer{i}'),
                               (root/f'node{i}/chaincode/tls/server.crt', f'anchor{i}')]:
            run('openssl', 'verify', '-purpose', 'sslserver', '-verify_hostname', hostname,
                '-CAfile', peer/'tls/ca.crt', cert)
            run('openssl', 'x509', '-in', cert, '-checkend', '86400', '-noout')
    if len(set(keys)) != 12:
        raise ValueError('Peer signing, peer TLS and chaincode keys must all be distinct.')
    run('openssl', 'verify', '-purpose', 'sslserver', '-verify_hostname', 'orderer',
        '-CAfile', root/'public/orderer-tls-ca.crt', root/'orderer/tls/server.crt')
    run('openssl', 'x509', '-in', root/'orderer/tls/server.crt', '-checkend', '86400', '-noout')
    run('openssl', 'verify', '-purpose', 'sslclient', '-CAfile', root/'public/orderer-tls-ca.crt',
        root/'orderer-admin/tls/client.crt')


def prepare(network=NETWORK):
    root = network/'runtime/single-vps'
    generated = network/'generated/single-vps'
    if root.exists():
        validate_runtime(network)
        print('Existing single-VPS identities and channel retained; no services started.')
        return
    if generated.exists():
        raise ValueError('Bootstrap exists without runtime. Restore it; do not generate replacement identities.')
    os.umask(0o077)
    generated.mkdir(parents=True, mode=0o700)
    root.mkdir(parents=True, mode=0o700)
    shutil.copyfile(network/'config/configtx.single-vps.yaml', generated/'configtx.yaml')
    run('cryptogen', 'generate', f'--config={network / "config/crypto-config.single-vps.yaml"}',
        f'--output={generated / "crypto-config"}')
    run('configtxgen', '-profile', 'LabchainChannel', '-channelID', 'labchain-channel',
        '-outputBlock', generated/'labchain-channel.block',
        env={**os.environ, 'FABRIC_CFG_PATH': str(generated)})
    crypto = generated/'crypto-config'
    public = root/'public'
    public.mkdir(mode=0o700)
    orgpaths = {f'org{i}': crypto/f'peerOrganizations/org{i}.labchain.internal' for i in (1, 2)}
    orgpaths['orderer'] = crypto/'ordererOrganizations/orderer.labchain.internal'
    for name, path in orgpaths.items():
        shutil.copytree(path/'msp', public/name/'msp')
        shutil.copyfile(next((path/'tlsca').glob('*-cert.pem')), public/f'{name}-tls-ca.crt')
    shutil.copyfile(generated/'labchain-channel.block', public/'labchain-channel.block')
    data = load_packaging().package(public, '{{.address}}:9999')
    (public/'labchain-anchor.tgz').write_bytes(data)
    package_id = 'labchain-anchor_1.0:' + hashlib.sha256(data).hexdigest()
    (public/'package-id.txt').write_text(package_id+'\n')
    for i in range(1, 5):
        org = 1 if i <= 2 else 2
        path = orgpaths[f'org{org}']
        node = root/f'node{i}'
        node.mkdir(mode=0o700)
        shutil.copytree(path/f'peers/peer{i}.org{org}.labchain.internal', node/'peer')
        tls = node/'chaincode/tls'
        tls.mkdir(parents=True, mode=0o700)
        request = generated/f'anchor{i}.csr'
        extension = generated/f'anchor{i}.ext'
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n'
                             f'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:anchor{i}\n')
        ca = path/'tlsca'
        run('openssl', 'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', tls/'server.key')
        run('openssl', 'req', '-new', '-key', tls/'server.key', '-subj', f'/CN=anchor{i}', '-out', request)
        run('openssl', 'x509', '-req', '-in', request, '-CA', next(ca.glob('*-cert.pem')),
            '-CAkey', next(ca.glob('*_sk')), '-set_serial', str(1000+i), '-days', '365', '-sha256',
            '-extfile', extension, '-out', tls/'server.crt')
        (node/'chaincode.env').write_text('CORE_CHAINCODE_ID='+package_id+'\n')
    for i in (1, 2):
        shutil.copytree(orgpaths[f'org{i}']/f'users/Admin@org{i}.labchain.internal', root/f'admin/org{i}')
    shutil.copytree(orgpaths['orderer']/'orderers/orderer.orderer.labchain.internal', root/'orderer')
    shutil.copytree(orgpaths['orderer']/'users/Admin@orderer.labchain.internal', root/'orderer-admin')
    for path in public.rglob('*'):
        if path.is_file() and b'PRIVATE KEY' in path.read_bytes():
            raise ValueError('Public artifacts contain private key material.')
    (root/'host-fingerprint').write_text(fingerprint()+'\n')
    manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file() and p.name != 'host-fingerprint'}
    (root/'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2)+'\n')
    (root/'COMPLETE').write_text('single-vps-v1\n')
    for path in root.rglob('*'):
        path.chmod(0o700 if path.is_dir() else 0o600)
    validate_runtime(network)
    print('Prepared one deployment with four distinct peers. No services started.')
    print('Protect generated/single-vps signing CAs in encrypted offline custody before bring-up.')


def validate_peer_core(network=NETWORK):
    """Check parsed YAML: an empty environment override cannot disable Docker in Viper."""
    try:
        core = yaml.safe_load((network/'config/core.single-vps.yaml').read_text())
    except yaml.YAMLError as error:
        raise ValueError('Invalid reviewed peer core YAML.') from error
    if not isinstance(core, dict):
        raise ValueError('Reviewed peer core configuration must be a mapping.')
    # Viper treats configuration keys case-insensitively and supports dotted paths.
    keys = {str(k).lower(): v for k, v in core.items()}
    vm = keys.get('vm')
    if not isinstance(vm, dict) or 'vm.endpoint' in keys or any(str(k).lower() == 'endpoint' for k in vm):
        raise ValueError('vm.endpoint must be absent from the reviewed peer core configuration.')
    if core.get('chaincode', {}).get('externalBuilders') != CCAAS_BUILDERS:
        raise ValueError('The reviewed peer core must preserve the CCAAS external builder.')


def validate_compose(config, network=NETWORK):
    """Fail closed on public publishing, host networking, shared ledgers or identity mounts."""
    validate_peer_core(network)
    services = config['services']
    expected = {'orderer'} | {f'{role}{i}' for role in ('peer', 'anchor') for i in range(1, 5)}
    if set(services) != expected or config['name'] != 'labchain-single-vps':
        raise ValueError('Unexpected single-VPS services/project.')
    net = config['networks']['fabric']
    if net.get('name') != 'labchain-fabric' or net.get('driver') != 'bridge' or net.get('internal'):
        raise ValueError('The labchain-fabric network must be a non-internal bridge for loopback-published host access.')
    versions = json.loads((network/'versions.json').read_text())
    for name, service in services.items():
        if service.get('network_mode') or set(service.get('networks', {})) != {'fabric'} or service.get('privileged'):
            raise ValueError('Each Fabric service must use only the Docker bridge.')
        if service.get('extra_hosts') or service.get('depends_on'):
            raise ValueError('Use Docker DNS and explicit service startup.')
        i = int(name[-1]) if name != 'orderer' else None
        expected_ports = {7050: 7050, 7053: 7053, 9444: 9444} if name == 'orderer' else (
            {7051: 7051+1000*(i-1), 9443: 9443 if i == 1 else 9443+i} if name.startswith('peer') else {})
        ports = service.get('ports', [])
        if len(ports) != len(expected_ports) or any(
            p.get('host_ip') != '127.0.0.1' or p.get('protocol', 'tcp') != 'tcp'
            or expected_ports.get(p['target']) != int(p['published']) for p in ports):
            raise ValueError('Only the reviewed, unique loopback CLI/health ports may be published.')
        role = 'peer' if name.startswith('peer') else 'orderer' if name == 'orderer' else 'chaincode'
        if service['image'] != versions[f'{role}_image']:
            raise ValueError('Image differs from reviewed version pins.')
        identity = 'orderer' if name == 'orderer' else f'node{i}/peer' if role == 'peer' else f'node{i}/chaincode/tls'
        mounts = service.get('volumes', [])
        if any(Path(str(v.get(field, ''))).name == 'docker.sock'
               for v in mounts for field in ('source', 'target')):
            raise ValueError('Docker control socket mounts are prohibited.')
        binds = [v for v in mounts if v['type'] == 'bind']
        expected_binds = {'/tls' if role == 'chaincode' else '/identity':
                          (network/'runtime/single-vps'/identity).resolve()}
        if role == 'peer':
            expected_binds[f'{PEER_CFG_PATH}/core.yaml'] = (network/'config/core.single-vps.yaml').resolve()
        if (len(binds) != len(expected_binds) or {v['target'] for v in binds} != set(expected_binds)
                or any(Path(v['source']).resolve() != expected_binds[v['target']] or not v.get('read_only') for v in binds)):
            raise ValueError('Incorrect or shared private identity/core configuration mount.')
        if role == 'peer':
            core_mount = next(v for v in binds if v['target'] == f'{PEER_CFG_PATH}/core.yaml')
            if core_mount.get('bind', {}).get('create_host_path', True):
                raise ValueError('The reviewed core file must exist; automatic host path creation is prohibited.')
        volumes = [v for v in mounts if v['type'] == 'volume']
        if role != 'chaincode':
            key = f'{name}-ledger'
            if len(volumes) != 1 or volumes[0]['source'] != key or config['volumes'][key]['name'] != f'labchain-{name}-ledger':
                raise ValueError('Each peer/orderer requires its own persistent ledger.')
        elif volumes:
            raise ValueError('Chaincode must not mount peer ledgers.')
        if role == 'chaincode' and service.get('tmpfs') != ['/tmp:size=16m,mode=1777']:
            raise ValueError('Chaincode requires one valid writable /tmp mount.')
        if role == 'peer':
            env = service['environment']
            if 'CORE_VM_ENDPOINT' in env:
                raise ValueError('CORE_VM_ENDPOINT is prohibited; leave vm.endpoint unconfigured in core.yaml.')
            if env.get('FABRIC_CFG_PATH') != PEER_CFG_PATH:
                raise ValueError('Every peer must select the reviewed core configuration using FABRIC_CFG_PATH.')
            try:
                builders = json.loads(env.get('CORE_CHAINCODE_EXTERNALBUILDERS', 'null'))
            except (ValueError, TypeError) as error:
                raise ValueError('Invalid CCAAS external builder configuration.') from error
            if builders != CCAAS_BUILDERS:
                raise ValueError('Every peer must use the reviewed CCAAS external builder configuration.')
            required = {'CORE_PEER_ID': name, 'CORE_PEER_ADDRESS': f'{name}:7051',
                        'CORE_PEER_LOCALMSPID': 'Org1MSP' if i <= 2 else 'Org2MSP',
                        'CORE_PEER_GOSSIP_EXTERNALENDPOINT': f'{name}:7051',
                        'CORE_PEER_GOSSIP_BOOTSTRAP': f'peer{i+1 if i%2 else i-1}:7051',
                        'CHAINCODE_AS_A_SERVICE_BUILDER_CONFIG': '{"address":"anchor%d"}' % i}
            if any(env.get(k) != v for k, v in required.items()):
                raise ValueError('Peer identity, organization or Docker DNS configuration differs.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['config', 'prepare', 'runtime', 'compose'])
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    try:
        if args.action == 'config':
            read_config(args.path)
        elif args.action == 'prepare':
            prepare()
        elif args.action == 'runtime':
            validate_runtime()
        else:
            import sys
            validate_compose(json.load(sys.stdin))
    except (ValueError, OSError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Single-VPS check failed: {error}\n')
