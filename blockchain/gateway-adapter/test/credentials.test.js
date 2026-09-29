import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { credentials } from '../src/connection.js';
let root, config;
function openssl(...args) { execFileSync('openssl', args, { stdio: 'pipe' }); }
function leaf(role, name) {
  const key = path.join(root, `${name}.key`), csr = path.join(root, `${name}.csr`), cert = path.join(root, `${name}.pem`);
  openssl('req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-keyout', key, '-out', csr, '-subj', `/OU=${role}/CN=SyntheticService`);
  openssl('x509', '-req', '-in', csr, '-CA', config.tlsCA, '-CAkey', path.join(root, 'ca.key'), '-set_serial', name === 'client' ? '2' : name === 'admin' ? '3' : '4', '-days', '1', '-extfile', path.join(root, 'leaf.ext'), '-out', cert);
  return { key, cert };
}
before(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'rhu-adapter-test-'));
  for (const dir of ['msp', 'msp/signcerts', 'msp/keystore', 'msp/cacerts']) fs.mkdirSync(path.join(root, dir), { mode: 0o700 });
  config = { tlsCA: path.join(root, 'msp/cacerts/ca.pem'), cert: path.join(root, 'msp/signcerts/client.pem'), key: path.join(root, 'msp/keystore/client_sk') };
  openssl('req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-keyout', path.join(root, 'ca.key'), '-out', config.tlsCA, '-days', '1', '-subj', '/CN=SyntheticCA');
  fs.writeFileSync(path.join(root, 'leaf.ext'), 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n');
  const client = leaf('client', 'client');
  fs.copyFileSync(client.cert, config.cert); fs.copyFileSync(client.key, config.key); fs.chmodSync(config.key, 0o600);
  leaf('admin', 'admin'); leaf('peer', 'peer');
});
after(() => fs.rmSync(root, { recursive: true, force: true }));
test('dedicated EC client matches its key and CA', () => {
  const result = credentials(config);
  assert.equal(result.privateKey.asymmetricKeyType, 'ec');
  assert.ok(result.certificate.includes('BEGIN CERTIFICATE'));
});
for (const role of ['admin', 'peer']) {
  test(`${role} credentials are prohibited`, () => {
    const original = fs.readFileSync(config.cert);
    try {
      fs.copyFileSync(path.join(root, `${role}.pem`), config.cert);
      assert.throws(() => credentials(config), { code: 'CREDENTIAL_INVALID' });
    } finally { fs.writeFileSync(config.cert, original); }
  });
}
test('private key permissions and missing/mismatched keys fail without PEM disclosure', () => {
  fs.chmodSync(config.key, 0o640);
  try { assert.throws(() => credentials(config), { code: 'CREDENTIAL_INVALID' }); }
  finally { fs.chmodSync(config.key, 0o600); }
  const original = fs.readFileSync(config.key);
  try {
    fs.copyFileSync(path.join(root, 'admin.key'), config.key);
    assert.throws(() => credentials(config), { code: 'CREDENTIAL_INVALID' });
    fs.writeFileSync(config.key, 'PRIVATE KEY synthetic secret');
    assert.throws(() => credentials(config), (error) => error.code === 'CREDENTIAL_INVALID' && !error.message.includes('PRIVATE KEY'));
  } finally { fs.writeFileSync(config.key, original, { mode: 0o600 }); }
});
test('symlink and oversized credential files are refused', () => {
  const link = path.join(root, 'alias.key'); fs.symlinkSync(config.key, link);
  assert.throws(() => credentials({ ...config, key: link }), { code: 'CREDENTIAL_INVALID' });
  const huge = path.join(root, 'huge'); fs.writeFileSync(huge, Buffer.alloc(65537));
  assert.throws(() => credentials({ ...config, cert: huge }), { code: 'CREDENTIAL_INVALID' });
});

test('offline startup checker validates client and rejects malformed keys without a Gateway', () => {
  const command = path.resolve('src/check-credentials.js');
  const env = { PATH: '/usr/bin:/bin', BLOCKCHAIN_GATEWAY_TLS_CA_PATH: config.tlsCA,
    BLOCKCHAIN_CLIENT_CERT_PATH: config.cert, BLOCKCHAIN_CLIENT_KEY_PATH: config.key };
  assert.deepEqual(JSON.parse(execFileSync(process.execPath, [command], { env, encoding: 'utf8' })), { ok: true });
  const original = fs.readFileSync(config.key);
  try {
    fs.writeFileSync(config.key, 'SYNTHETIC_PRIVATE_KEY_INVALID');
    assert.throws(() => execFileSync(process.execPath, [command], { env, stdio: 'pipe' }),
      (error) => error.status === 1 && error.stdout.toString().trim() === '{"ok":false,"code":"CREDENTIAL_INVALID"}' &&
        !error.stderr.toString().includes('SYNTHETIC_PRIVATE'));
  } finally { fs.writeFileSync(config.key, original, { mode: 0o600 }); }
});
