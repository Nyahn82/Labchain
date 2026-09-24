#!/usr/bin/env python3
"""Deterministic CCAAS package: public CA certificates only, never private keys."""
import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

def archive(files):
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as tar:
            for name, content in sorted(files.items()):
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(content), 0o644, 0
                tar.addfile(entry, io.BytesIO(content))
    return result.getvalue()

def package(public, address="localhost:9999"):
    roots = ''.join((public / f'org{i}-tls-ca.crt').read_text() for i in (1,2))
    if 'PRIVATE KEY' in roots:
        raise ValueError('Private material is forbidden in a chaincode package.')
    connection = {'address':address,'dial_timeout':'10s','tls_required':True,
                  'client_auth_required':False,'root_cert':roots}
    code = archive({'connection.json':json.dumps(connection, sort_keys=True).encode()})
    metadata = json.dumps({'path':'','type':'ccaas','label':'labchain-anchor_1.0'}, sort_keys=True).encode()
    return archive({'metadata.json':metadata,'code.tar.gz':code})

if __name__ == '__main__':
    public = Path(sys.argv[1])
    data = package(public)
    output = public/'labchain-anchor.tgz'
    if output.exists() and output.read_bytes() != data:
        sys.exit('Existing package differs; do not replace a deployed package in place.')
    output.write_bytes(data)
    (public/'package-id.txt').write_text('labchain-anchor_1.0:'+hashlib.sha256(data).hexdigest()+'\n')
