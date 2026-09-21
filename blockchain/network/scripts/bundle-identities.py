#!/usr/bin/env python3
"""Create separate private node bundles; keep signing CAs on bootstrap storage."""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

def copytree(source, dest):
    shutil.copytree(source, dest)

def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def create_bundles(generated):
    crypto = generated/'crypto-config'
    public = generated/'public'
    public.mkdir(mode=0o700)
    for name, path in [('org1',crypto/'peerOrganizations/org1.labchain.internal'),
                       ('org2',crypto/'peerOrganizations/org2.labchain.internal'),
                       ('orderer',crypto/'ordererOrganizations/orderer.labchain.internal')]:
        copytree(path/'msp', public/name/'msp')
        for f in (public/name/'msp').rglob('*'):
            if f.is_file() and b'PRIVATE KEY' in f.read_bytes():
                raise ValueError('Public MSP unexpectedly contains a private key.')
        shutil.copyfile(next((path/'tlsca').glob('*-cert.pem')),public/f'{name}-tls-ca.crt')
    shutil.copyfile(generated/'labchain-channel.block', public/'labchain-channel.block')
    run(sys.executable, str(Path(__file__).with_name('package-chaincode.py')), str(public))
    for node in range(1,5):
        org = 1 if node < 3 else 2
        orgpath = crypto/f'peerOrganizations/org{org}.labchain.internal'
        root = generated/f'bundles/node{node}'
        runtime = root/'runtime'
        runtime.mkdir(parents=True, mode=0o700)
        (runtime/'node-id').write_text(f'node{node}\n')
        copytree(orgpath/f'peers/peer{node}.org{org}.labchain.internal',runtime/'peer')
        copytree(public,runtime/'public')
        if node in (1,3):
            copytree(orgpath/f'users/Admin@org{org}.labchain.internal', runtime/'admin')
        if node == 4:
            opath = crypto/'ordererOrganizations/orderer.labchain.internal'
            copytree(opath/'orderers/orderer.orderer.labchain.internal',runtime/'orderer')
            copytree(opath/'users/Admin@orderer.labchain.internal',runtime/'orderer-admin')
        # A distinct local chaincode server key per host, signed by its TLS CA.
        tls = runtime/'chaincode/tls'
        tls.mkdir(parents=True,mode=0o700)
        request = generated/f'node{node}-chaincode.csr'
        extension = generated/f'node{node}-chaincode.ext'
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n')
        ca = orgpath/'tlsca'
        run('openssl','genpkey','-algorithm','EC','-pkeyopt','ec_paramgen_curve:P-256','-out',str(tls/'server.key'))
        run('openssl','req','-new','-key',str(tls/'server.key'),'-subj',f'/CN=anchor-node{node}','-out',str(request))
        run('openssl','x509','-req','-in',str(request),'-CA',str(next(ca.glob('*-cert.pem'))),
            '-CAkey',str(next(ca.glob('*_sk'))),'-set_serial',str(1000+node),'-days','365','-sha256',
            '-extfile',str(extension),'-out',str(tls/'server.crt'))
        (runtime/'chaincode.env').write_text('CORE_CHAINCODE_ID='+ (public/'package-id.txt').read_text())
        for p in runtime.rglob('*'):
            if p.is_dir():
                p.chmod(0o700)
            else:
                p.chmod(0o600)
        output = generated/f'bundles/node{node}.tar.gz'
        with tarfile.open(output,'w:gz') as tar:
            tar.add(runtime,arcname='runtime')
        output.chmod(0o600)
        (output.with_suffix(output.suffix+'.sha256')).write_text(hashlib.sha256(output.read_bytes()).hexdigest()+f'  node{node}.tar.gz\n')

if __name__ == '__main__':
    os.umask(0o077)
    create_bundles(Path(sys.argv[1]).resolve())
