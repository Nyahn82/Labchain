"""Offline infrastructure checks; no Docker daemon or live patient data."""
import base64
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

NETWORK = Path(__file__).resolve().parents[1]

def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,NETWORK/'scripts'/filename)
    loaded=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded

config=module('network_config','config.py')
packaging=module('network_package','package-chaincode.py')
observations=module('network_observations','verify-observations.py')

class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=Path(self.tmp.name)/'network.env'
        self.text=(NETWORK/'.env.example').read_text()
        self.env.write_text(self.text)

    def test_example_is_syntax_valid_but_not_deployable(self):
        self.assertEqual(config.read_config(self.env,True)['NODE_ID'],'node1')
        with self.assertRaisesRegex(ValueError,'documentation'):
            config.read_config(self.env)

    def test_distinct_private_addresses_are_supported(self):
        self.env.write_text(self.text.replace('192.0.2.','10.60.0.'))
        self.assertEqual(config.read_config(self.env)['NODE4_IP'],'10.60.0.14')

    def test_duplicate_vps_addresses_are_rejected(self):
        self.env.write_text(self.text.replace('NODE4_IP=192.0.2.14','NODE4_IP=192.0.2.11'))
        with self.assertRaisesRegex(ValueError,'distinct'):
            config.read_config(self.env,True)

    def test_wrong_org_and_wrong_hostname_are_rejected(self):
        for old,new in [('ORG_ID=Org1MSP','ORG_ID=Org2MSP'),('PEER_HOSTNAME=node1','PEER_HOSTNAME=node2')]:
            with self.subTest(old=old):
                self.env.write_text(self.text.replace(old,new))
                with self.assertRaisesRegex(ValueError,'topology'):
                    config.read_config(self.env,True)

    def test_missing_duplicate_and_unknown_variables_are_rejected(self):
        for text in [self.text.replace('ORG_ID=Org1MSP\n',''),self.text+'ORG_ID=Org1MSP\n',self.text+'PATH=/tmp\n']:
            with self.subTest(text=text[-20:]):
                self.env.write_text(text)
                with self.assertRaises(ValueError):config.read_config(self.env,True)

    def test_shell_substitution_is_not_executed(self):
        marker=Path(self.tmp.name)/'executed'
        for value in [f'$(touch {marker})',f'`touch {marker}`','yes;true','"yes"']:
            self.env.write_text(self.text.replace('FIREWALL_READY=no','FIREWALL_READY='+value))
            with self.assertRaises(ValueError):config.read_config(self.env,True)
        self.assertFalse(marker.exists())

    def test_unsupported_versions_and_ports_fail(self):
        for old,new in [('FABRIC_VERSION=2.5.16','FABRIC_VERSION=latest'),('PEER_LISTEN_PORT=7051','PEER_LISTEN_PORT=80')]:
            self.env.write_text(self.text.replace(old,new))
            with self.assertRaises(ValueError):config.read_config(self.env,True)

    def test_shell_loader_accepts_final_line_without_newline(self):
        self.env.write_text(self.text.replace('192.0.2.','10.60.0.').rstrip('\n'))
        result=subprocess.run(['bash','-c','source "$1"; load_config; printf "%s" "$FIREWALL_READY"','bash',str(NETWORK/'scripts/common.sh')],env={**os.environ,'LABCHAIN_ENV_FILE':str(self.env)},capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'no')

    def test_loopback_and_wildcard_bind_fail(self):
        for address in ['127.0.0.1','0.0.0.0','224.0.0.1']:
            self.env.write_text(self.text.replace('NODE_BIND_IP=192.0.2.11','NODE_BIND_IP='+address))
            with self.assertRaises(ValueError):config.read_config(self.env,True)

class NodeSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.network=Path(self.tmp.name)
        (self.network/'scripts').mkdir()
        for name in ('configure-node.py','config.py'):
            shutil.copyfile(NETWORK/'scripts'/name,self.network/'scripts'/name)
        shutil.copyfile(NETWORK/'.env.example',self.network/'.env.example')

    def configure(self,node='node1',ips=None):
        return subprocess.run(['python3',str(self.network/'scripts/configure-node.py'),node,
            *(ips or ['10.60.0.11','10.60.0.12','10.60.0.13','10.60.0.14'])],capture_output=True,text=True)

    def test_each_node_gets_matching_restricted_configuration(self):
        for node in range(1,5):
            with self.subTest(node=node):
                result=self.configure(f'node{node}')
                self.assertEqual(result.returncode,0,result.stderr)
                env=self.network/'.env'
                values=config.read_config(env)
                self.assertEqual(values['NODE_ID'],f'node{node}')
                self.assertEqual(values['ORG_ID'],'Org1MSP' if node<=2 else 'Org2MSP')
                self.assertEqual(values['NODE_PUBLIC_IP'],f'10.60.0.{10+node}')
                self.assertEqual(values['FIREWALL_READY'],'no')
                self.assertEqual(env.stat().st_mode & 0o777,0o600)
                env.unlink()

    def test_existing_configuration_is_never_overwritten(self):
        env=self.network/'.env'
        env.write_text('existing operator configuration')
        result=self.configure()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Existing .env retained',result.stderr)
        self.assertEqual(env.read_text(),'existing operator configuration')

    def test_invalid_inventory_leaves_no_deployment_file(self):
        result=self.configure(ips=['192.0.2.11','192.0.2.12','192.0.2.13','192.0.2.14'])
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.network/'.env').exists())

class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.anchor='TEST-11111111-1111-4111-8111-111111111111'
        for number in range(1,5):
            (self.path/f'node{number}.info').write_text('Blockchain info: '+json.dumps({'height':8,'currentBlockHash':'Y3VycmVudA==','previousBlockHash':'cHJldmlvdXM='}))
            (self.path/f'node{number}.record').write_text(json.dumps({'anchor_id':self.anchor,'transaction_id':'synthetic-tx','content_hash':'a'*64}))

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()):return observations.verify(self.path,self.anchor)

    def test_all_four_converged_records_pass(self):
        self.assertEqual(self.check()['transaction_id'],'synthetic-tx')

    def test_one_lagging_peer_fails(self):
        path=self.path/'node4.info'
        path.write_text(path.read_text().replace('"height": 8','"height": 7'))
        with self.assertRaisesRegex(ValueError,'converged'):self.check()

    def test_equal_heights_but_different_block_hash_fails(self):
        path=self.path/'node2.info'
        path.write_text(path.read_text().replace('Y3VycmVudA==','b3RoZXI='))
        with self.assertRaisesRegex(ValueError,'converged'):self.check()

    def test_record_mismatch_fails(self):
        path=self.path/'node3.record'
        path.write_text(path.read_text().replace('synthetic-tx','different-tx'))
        with self.assertRaisesRegex(ValueError,'differ'):self.check()

    def test_wrong_anchor_fails(self):
        path=self.path/'node1.record'
        path.write_text(path.read_text().replace(self.anchor,'TEST-wrong'))
        with self.assertRaisesRegex(ValueError,'Unexpected'):self.check()

class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools=os.environ.get('LABCHAIN_FABRIC_TOOLS')
        if not tools or not (Path(tools)/'bin/cryptogen').exists():
            raise unittest.SkipTest('Set LABCHAIN_FABRIC_TOOLS to the pinned extracted Fabric tools.')
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.generated=Path(cls.tmp.name)/'bootstrap'
        cls.env={**os.environ,'LABCHAIN_BOOTSTRAP_DIR':str(cls.generated),'FABRIC_LOGGING_SPEC':'error'}
        subprocess.run([str(NETWORK/'scripts/generate-crypto.sh')],env=cls.env,check=True,capture_output=True)
        cls.tools=Path(tools)

    def test_four_distinct_peer_signing_and_tls_keys(self):
        signing=[];tls=[]
        for number in range(1,5):
            runtime=self.generated/f'bundles/node{number}/runtime'
            signing.append(hashlib.sha256(next((runtime/'peer/msp/keystore').glob('*')).read_bytes()).digest())
            tls.append(hashlib.sha256((runtime/'peer/tls/server.key').read_bytes()).digest())
        self.assertEqual(len(set(signing)),4)
        self.assertEqual(len(set(tls)),4)
        self.assertTrue(set(signing).isdisjoint(tls))

    def test_node_bundles_exclude_ca_keys_and_other_peer_identities(self):
        for number in range(1,5):
            runtime=self.generated/f'bundles/node{number}/runtime'
            files=[p for p in runtime.rglob('*') if p.is_file()]
            self.assertFalse(any('/tlsca/' in str(p) or '/ca/' in str(p) for p in files))
            self.assertEqual((runtime/'node-id').read_text().strip(),f'node{number}')
            self.assertEqual((runtime/'admin').exists(),number in (1,3))
            self.assertEqual((runtime/'orderer').exists(),number==4)
            for p in (runtime/'public').rglob('*'):
                if p.is_file():self.assertNotIn(b'PRIVATE KEY',p.read_bytes())

    def test_all_node_bundles_have_same_channel_and_package(self):
        for filename in ['labchain-channel.block','labchain-anchor.tgz','package-id.txt']:
            copies=[(self.generated/f'bundles/node{i}/runtime/public'/filename).read_bytes() for i in range(1,5)]
            self.assertTrue(all(x==copies[0] for x in copies))

    def test_peer_and_chaincode_certificates_verify(self):
        for number in range(1,5):
            runtime=self.generated/f'bundles/node{number}/runtime'
            for role,hostname in [('peer',f'node{number}.labchain.internal'),('chaincode','localhost')]:
                result=subprocess.run(['openssl','verify','-purpose','sslserver','-verify_hostname',hostname,'-CAfile',str(runtime/'peer/tls/ca.crt'),str(runtime/role/'tls/server.crt')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_orderer_admin_uses_client_tls_identity(self):
        runtime=self.generated/'bundles/node4/runtime'
        result=subprocess.run(['openssl','verify','-purpose','sslclient','-CAfile',str(runtime/'orderer/tls/ca.crt'),str(runtime/'orderer-admin/tls/client.crt')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_bootstrap_repeat_preserves_keys_and_block(self):
        path=self.generated/'crypto-config/peerOrganizations/org1.labchain.internal/peers/peer1.org1.labchain.internal/tls/server.key'
        before=path.read_bytes()
        block=(self.generated/'labchain-channel.block').read_bytes()
        subprocess.run([str(NETWORK/'scripts/generate-crypto.sh')],env=self.env,check=True,capture_output=True)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual((self.generated/'labchain-channel.block').read_bytes(),block)

    def test_package_is_deterministic_tls_only_and_native_id_matches(self):
        public=self.generated/'public'
        first=packaging.package(public)
        self.assertEqual(first,packaging.package(public))
        with tarfile.open(fileobj=io.BytesIO(first)) as archive:
            metadata=json.load(archive.extractfile('metadata.json'))
            self.assertEqual(metadata['type'],'ccaas')
            code=archive.extractfile('code.tar.gz').read()
        with tarfile.open(fileobj=io.BytesIO(code)) as archive:
            connection=json.load(archive.extractfile('connection.json'))
        self.assertEqual(connection['address'],'localhost:9999')
        self.assertTrue(connection['tls_required'])
        self.assertNotIn('PRIVATE KEY',connection['root_cert'])
        native=subprocess.check_output([str(self.tools/'bin/peer'),'lifecycle','chaincode','calculatepackageid',str(public/'labchain-anchor.tgz')],env={**self.env,'FABRIC_CFG_PATH':str(self.tools/'config')},text=True).strip()
        self.assertEqual(native,(public/'package-id.txt').read_text().strip())

    def test_native_channel_has_two_org_endorsement_and_one_raft_consenter(self):
        decoded=subprocess.check_output([str(self.tools/'bin/configtxgen'),'-inspectBlock',str(self.generated/'labchain-channel.block')],env=self.env,stderr=subprocess.DEVNULL)
        channel=json.loads(decoded)['data']['data'][0]['payload']['data']['config']['channel_group']
        app=channel['groups']['Application']
        self.assertEqual(set(app['groups']),{'Org1','Org2'})
        policy=app['policies']['Endorsement']['policy']['value']
        self.assertEqual(policy['rule']['n_out_of']['n'],2)
        self.assertEqual([x['principal']['msp_identifier'] for x in policy['identities']],['Org1MSP','Org2MSP'])
        consensus=channel['groups']['Orderer']['values']['ConsensusType']['value']
        self.assertEqual(consensus['type'],'etcdraft')
        self.assertEqual(len(consensus['metadata']['consenters']),1)
        for identity in policy['identities']:
            principal=subprocess.check_output([str(self.tools/'bin/configtxlator'),'proto_encode','--type','common.MSPRole'],input=json.dumps(identity['principal']).encode())
            identity['principal']=base64.b64encode(principal).decode()
        self.check_lifecycle_policy({'signature_policy':policy}, expected=0)
        policy['rule']['n_out_of']['n']=1
        self.check_lifecycle_policy({'signature_policy':policy}, expected=1)
        self.check_lifecycle_policy({'channel_config_policy_reference':'/Channel/Application/Endorsement'}, expected=1)

    def check_lifecycle_policy(self, application_policy, expected):
        binary=subprocess.check_output([str(self.tools/'bin/configtxlator'),'proto_encode','--type','protos.ApplicationPolicy'],input=json.dumps(application_policy).encode())
        definition={'sequence':1,'version':'1.0.0','validation_parameter':base64.b64encode(binary).decode()}
        env={**self.env,'PATH':str(self.tools/'bin')+os.pathsep+os.environ['PATH']}
        result=subprocess.run(['python3',str(NETWORK/'scripts/check-definition.py')],input=json.dumps(definition).encode(),env=env,capture_output=True)
        self.assertEqual(result.returncode,expected,result.stderr.decode())

    def test_private_material_is_not_in_git_scope(self):
        repo=NETWORK.parents[1]
        for path in ['blockchain/network/generated/crypto-config/key','blockchain/network/runtime/peer/tls/server.key','blockchain/network/organizations/org1/users/admin/msp/keystore/key','blockchain/network/wallet/user.json','blockchain/network/.env']:
            result=subprocess.run(['git','check-ignore','--quiet',path],cwd=repo)
            self.assertEqual(result.returncode,0,path)

if __name__=='__main__':unittest.main()
