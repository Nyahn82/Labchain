"""Offline topology, real crypto, package and guarded-command tests. No services start."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

NETWORK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('single_vps', NETWORK/'scripts/single_vps.py')
single = importlib.util.module_from_spec(spec)
spec.loader.exec_module(single)


def render(network):
    return json.loads(subprocess.check_output([
        'docker', 'compose', '--env-file', str(network/'.env.single-vps.example'),
        '-f', str(network/'compose/docker-compose.single-vps.yml'), '--profile', '*',
        'config', '--format', 'json'], text=True))


class SingleConfigurationTests(unittest.TestCase):
    def test_shared_config_and_rejected_legacy_or_unsafe_input(self):
        text = (NETWORK/'.env.single-vps.example').read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'env'
            path.write_text(text)
            self.assertEqual(single.read_config(path), single.EXPECTED)
            for bad in [text+'NODE_ID=node1\n', text+'NODE1_IP=10.0.0.1\n', text+'FIREWALL_READY=yes\n',
                        text+'FABRIC_VERSION=2.5.16\n', text.replace('2.5.16', 'latest'),
                        text.replace('2.5.16', '$(touch /tmp/unsafe)'), 'FABRIC_VERSION=2.5.16\n']:
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    single.read_config(path)

    def test_runtime_and_secret_paths_are_ignored_but_template_is_tracked(self):
        repo = NETWORK.parents[1]
        for path in ['runtime/single-vps/node1/peer/msp/keystore/key', 'runtime/single-vps/node4/peer/tls/server.key',
                     'runtime/single-vps/admin/org1/msp/keystore/key', 'runtime/single-vps/orderer-admin/tls/client.key',
                     'generated/single-vps/crypto-config/ca/key', '.env.single-vps']:
            self.assertEqual(subprocess.run(['git', 'check-ignore', '--quiet', str(NETWORK/path)], cwd=repo).returncode, 0)
        self.assertEqual(subprocess.run(['git', 'check-ignore', '--quiet', str(NETWORK/'.env.single-vps.example')], cwd=repo).returncode, 1)


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose is required for static rendering; no daemon is used.')
class SingleComposeTests(unittest.TestCase):
    def setUp(self):
        self.config = render(NETWORK)

    def test_reviewed_topology_has_unique_loopback_ports_identities_and_ledgers(self):
        single.validate_compose(self.config)
        self.assertFalse(self.config['networks']['fabric'].get('internal', False))
        self.assertEqual(
            {p['host_ip'] for s in self.config['services'].values() for p in s.get('ports', [])},
            {'127.0.0.1'},
        )
        ports = [p['published'] for s in self.config['services'].values() for p in s.get('ports', [])]
        self.assertEqual(len(ports), len(set(ports)))
        self.assertEqual(len(self.config['volumes']), 5)
        for i in range(1, 5):
            peer = self.config['services'][f'peer{i}']
            self.assertEqual(peer['environment']['CORE_PEER_LISTENADDRESS'], '0.0.0.0:7051')
            self.assertNotIn('ports', self.config['services'][f'anchor{i}'])
            self.assertFalse(peer.get('depends_on'))
        self.assertEqual(self.config['services']['peer1']['profiles'], ['foundation'])
        self.assertEqual(self.config['services']['peer2']['profiles'], ['peer2'])
        self.assertEqual(self.config['services']['peer3']['profiles'], ['peer3'])
        self.assertEqual(self.config['services']['peer4']['profiles'], ['peer4'])

    def test_public_host_network_shared_identity_and_wrong_dns_are_rejected(self):
        for mutation in ['public', 'host', 'identity', 'volume', 'dns', 'image', 'dependency', 'network', 'tmpfs']:
            config = copy.deepcopy(self.config)
            peer = config['services']['peer2']
            if mutation == 'public': peer['ports'][0]['host_ip'] = '0.0.0.0'
            if mutation == 'host': peer['network_mode'] = 'host'
            if mutation == 'identity': peer['volumes'][0]['source'] = str(NETWORK/'runtime/single-vps/node1/peer')
            if mutation == 'volume': config['volumes']['peer2-ledger']['name'] = 'labchain-peer1-ledger'
            if mutation == 'dns': peer['environment']['CORE_PEER_GOSSIP_BOOTSTRAP'] = '192.0.2.11:7051'
            if mutation == 'image': peer['image'] = 'fabric-peer:latest'
            if mutation == 'dependency': peer['depends_on'] = {'peer3': {}}
            if mutation == 'network': config['networks']['fabric']['internal'] = True
            if mutation == 'tmpfs': config['services']['anchor1']['tmpfs'] = ['/tmp:size=16m', 'mode=1777']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                single.validate_compose(config)


class SingleBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools = os.environ.get('LABCHAIN_FABRIC_TOOLS')
        if not tools or not (Path(tools)/'bin/cryptogen').exists():
            raise unittest.SkipTest('Set LABCHAIN_FABRIC_TOOLS to pinned Fabric 2.5.16 native tools.')
        cls.tools = Path(tools)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.network = Path(cls.tmp.name)/'network'
        cls.network.mkdir()
        for directory in ['scripts', 'config', 'compose']:
            shutil.copytree(NETWORK/directory, cls.network/directory)
        for filename in ['versions.json', '.env.single-vps.example']:
            shutil.copyfile(NETWORK/filename, cls.network/filename)
        shutil.copyfile(NETWORK/'.env.single-vps.example', cls.network/'.env.single-vps')
        cls.env = {**os.environ, 'PATH': str(cls.tools/'bin')+os.pathsep+os.environ['PATH'],
                   'FABRIC_CFG_PATH': str(cls.tools/'config')}
        with mock.patch.dict(os.environ, cls.env), contextlib.redirect_stdout(io.StringIO()):
            single.prepare(cls.network)
        cls.root = cls.network/'runtime/single-vps'

    def test_twelve_private_keys_are_distinct_and_certificates_match_service_dns(self):
        single.validate_runtime(self.network)
        for p in self.root.rglob('*'):
            self.assertEqual(p.stat().st_mode & 0o777, 0o700 if p.is_dir() else 0o600)
        for p in (self.root/'public').rglob('*'):
            if p.is_file(): self.assertNotIn(b'PRIVATE KEY', p.read_bytes())
        self.assertFalse(any('/ca/' in str(p) or '/tlsca/' in str(p) for p in self.root.rglob('*')))
        for i in range(1, 5):
            self.assertFalse((self.root/f'node{i}/admin').exists())

    def test_package_is_shared_templated_tls_and_matches_native_fabric_id(self):
        public = self.root/'public'
        data = (public/'labchain-anchor.tgz').read_bytes()
        self.assertEqual(data, single.load_packaging().package(public, '{{.address}}:9999'))
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            code = tar.extractfile('code.tar.gz').read()
        with tarfile.open(fileobj=io.BytesIO(code)) as tar:
            connection = json.load(tar.extractfile('connection.json'))
        self.assertEqual(connection['address'], '{{.address}}:9999')
        self.assertTrue(connection['tls_required'])
        self.assertNotIn('PRIVATE KEY', connection['root_cert'])
        native = subprocess.check_output([str(self.tools/'bin/peer'), 'lifecycle', 'chaincode', 'calculatepackageid',
                                          str(public/'labchain-anchor.tgz')], env=self.env, text=True).strip()
        self.assertEqual(native, (public/'package-id.txt').read_text().strip())
        for i in range(1, 5):
            self.assertEqual((self.root/f'node{i}/chaincode.env').read_text().strip(), 'CORE_CHAINCODE_ID='+native)

    def test_native_channel_uses_bridge_dns_two_org_policy_and_one_orderer(self):
        output = subprocess.check_output([str(self.tools/'bin/configtxgen'), '-inspectBlock',
                                          str(self.root/'public/labchain-channel.block')], env=self.env, stderr=subprocess.DEVNULL)
        group = json.loads(output)['data']['data'][0]['payload']['data']['config']['channel_group']
        app = group['groups']['Application']
        self.assertEqual(set(app['groups']), {'Org1', 'Org2'})
        policy = app['policies']['Endorsement']['policy']['value']
        self.assertEqual(policy['rule']['n_out_of']['n'], 2)
        self.assertEqual([x['principal']['msp_identifier'] for x in policy['identities']], ['Org1MSP', 'Org2MSP'])
        for org, peer in [('Org1', 'peer1'), ('Org2', 'peer3')]:
            anchors = app['groups'][org]['values']['AnchorPeers']['value']['anchor_peers']
            self.assertEqual(anchors, [{'host': peer, 'port': 7051}])
        orderer = group['groups']['Orderer']
        consenters = orderer['values']['ConsensusType']['value']['metadata']['consenters']
        self.assertEqual(len(consenters), 1)
        self.assertEqual((consenters[0]['host'], consenters[0]['port']), ('orderer', 7050))
        self.assertEqual(orderer['groups']['OrdererOrg']['values']['Endpoints']['value']['addresses'], ['orderer:7050'])

    def test_repeat_preserves_all_identity_artifacts(self):
        before = (self.root/'manifest.json').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()): single.prepare(self.network)
        self.assertEqual(before, (self.root/'manifest.json').read_bytes())
        single.validate_runtime(self.network)

    def test_foreign_host_and_modified_runtime_fail_without_regeneration(self):
        for path, replacement in [(self.root/'host-fingerprint', b'foreign-host\n'),
                                  (self.root/'node2/peer/tls/server.key', b'wrong-key')]:
            before = path.read_bytes()
            try:
                path.write_bytes(replacement)
                with self.assertRaises(ValueError): single.prepare(self.network)
                self.assertEqual(path.read_bytes(), replacement)
            finally:
                path.write_bytes(before)

    def test_partial_bootstrap_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Path(directory)
            (network/'generated/single-vps').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'restore|Restore'):
                single.prepare(network)
            self.assertFalse((network/'runtime/single-vps').exists())

    @unittest.skipUnless(shutil.which('docker'), 'Compose required for static rendering.')
    def test_start_commands_select_only_requested_services_and_stop_retains_volumes(self):
        # A recording Docker stub intercepts every call. Nothing can start.
        fake = self.network/'fake-bin'
        fake.mkdir(exist_ok=True)
        config_file = fake/'compose.json'
        config_file.write_text(json.dumps(render(self.network)))
        log = fake/'calls.jsonl'
        docker = fake/'docker'
        docker.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                          'with open(os.environ["DOCKER_CALL_LOG"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                          'if "config" in sys.argv: print(open(os.environ["DOCKER_CONFIG"]).read())\n')
        docker.chmod(0o755)
        env = {**self.env, 'PATH': str(fake)+os.pathsep+self.env['PATH'], 'DOCKER_CALL_LOG': str(log),
               'DOCKER_CONFIG': str(config_file), 'LABCHAIN_SINGLE_VPS_ENV_FILE': str(self.network/'.env.single-vps')}
        for script, args, services in [('start-foundation-single-vps.sh', [], ['orderer', 'peer1']),
                                        ('start-peer-single-vps.sh', ['peer2'], ['peer2']),
                                        ('start-peer-single-vps.sh', ['peer3'], ['peer3']),
                                        ('start-peer-single-vps.sh', ['peer4'], ['peer4'])]:
            log.write_text('')
            result = subprocess.run(['bash', str(self.network/'scripts'/script), *args], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            ups = [call[call.index('up')+1:] for call in calls if 'up' in call]
            self.assertEqual(ups, [['-d', '--no-deps', '--no-build', *services]])
        log.write_text('')
        subprocess.run(['bash', str(self.network/'scripts/stop-single-vps.sh')], env=env, check=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(calls[0][-1], 'stop')
        self.assertNotIn('down', calls[0])
        self.assertNotIn('-v', calls[0])
        log.write_text('')
        result = subprocess.run(['bash', str(self.network/'scripts/start-peer-single-vps.sh'), 'all'], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log.read_text(), '')


if __name__ == '__main__':
    unittest.main()
