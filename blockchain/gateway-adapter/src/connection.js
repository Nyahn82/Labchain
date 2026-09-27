import fs from 'node:fs';
import path from 'node:path';
import { X509Certificate, createPrivateKey, createPublicKey } from 'node:crypto';
import * as grpc from '@grpc/grpc-js';
import { connect, signers } from '@hyperledger/fabric-gateway';
import { AdapterError, requireValue } from './protocol.js';

const DEFAULTS = { READY: 5000, EVALUATE: 10000, ENDORSE: 30000, SUBMIT: 10000, COMMIT: 30000 };
export function configuration(env = process.env) {
  const config = {
    endpoint: env.BLOCKCHAIN_GATEWAY_ENDPOINT ?? '127.0.0.1:7051',
    tlsCA: env.BLOCKCHAIN_GATEWAY_TLS_CA_PATH,
    mspId: env.BLOCKCHAIN_CLIENT_MSP_ID ?? 'Org1MSP',
    cert: env.BLOCKCHAIN_CLIENT_CERT_PATH,
    key: env.BLOCKCHAIN_CLIENT_KEY_PATH,
    channel: env.BLOCKCHAIN_CHANNEL ?? 'labchain-channel',
    chaincode: env.BLOCKCHAIN_CHAINCODE ?? 'labchain-anchor',
    sourceNode: env.BLOCKCHAIN_SOURCE_NODE ?? 'node1',
    deadlines: {},
  };
  requireValue(config.endpoint === '127.0.0.1:7051' && config.mspId === 'Org1MSP' &&
    config.channel === 'labchain-channel' && config.chaincode === 'labchain-anchor' && config.sourceNode === 'node1', 'CONFIG_INVALID');
  for (const field of ['tlsCA', 'cert', 'key']) requireValue(typeof config[field] === 'string' && config[field].length <= 4096 && path.isAbsolute(config[field]) && !config[field].includes('\0'), 'CONFIG_INVALID');
  for (const [stage, fallback] of Object.entries(DEFAULTS)) {
    const input = env[`BLOCKCHAIN_${stage}_TIMEOUT_MS`] ?? String(fallback);
    requireValue(typeof input === 'string' && /^\d{1,6}$/.test(input), 'CONFIG_INVALID');
    const value = Number(input);
    requireValue(value >= 100 && value <= 60000, 'CONFIG_INVALID');
    config.deadlines[stage.toLowerCase()] = value;
  }
  return config;
}
function boundedFile(file, secret = false) {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const info = fs.fstatSync(fd);
    requireValue(info.isFile() && info.size > 0 && info.size <= 65536, 'CREDENTIAL_INVALID');
    if (secret) {
      requireValue((info.mode & 0o777) === 0o600 && info.uid === process.getuid(), 'CREDENTIAL_INVALID');
      requireValue((fs.statSync(path.dirname(file)).mode & 0o777) === 0o700, 'CREDENTIAL_INVALID');
    }
    return fs.readFileSync(fd);
  } finally { fs.closeSync(fd); }
}
export function credentials(config) {
  try {
    const certificate = boundedFile(config.cert);
    const x509 = new X509Certificate(certificate);
    const keyBytes = boundedFile(config.key, true);
    let privateKey;
    try { privateKey = createPrivateKey(keyBytes); } finally { keyBytes.fill(0); }
    const roles = x509.subject.split('\n').filter((line) => line.startsWith('OU='));
    requireValue(roles.includes('OU=client') && !roles.some((r) => ['OU=admin', 'OU=peer', 'OU=orderer'].includes(r)) && !x509.ca, 'CREDENTIAL_INVALID');
    requireValue(Date.parse(x509.validFrom) <= Date.now() && Date.parse(x509.validTo) > Date.now(), 'CREDENTIAL_INVALID');
    requireValue(privateKey.asymmetricKeyType === 'ec' && privateKey.asymmetricKeyDetails.namedCurve === 'prime256v1', 'CREDENTIAL_INVALID');
    requireValue(x509.publicKey.export({ type: 'spki', format: 'der' }).equals(createPublicKey(privateKey).export({ type: 'spki', format: 'der' })), 'CREDENTIAL_INVALID');
    const caDir = path.join(path.dirname(path.dirname(config.cert)), 'cacerts');
    const files = fs.readdirSync(caDir);
    requireValue(files.length === 1, 'CREDENTIAL_INVALID');
    const ca = new X509Certificate(boundedFile(path.join(caDir, files[0])));
    requireValue(ca.ca && x509.checkIssued(ca) && x509.verify(ca.publicKey) && Date.parse(ca.validTo) > Date.now(), 'CREDENTIAL_INVALID');
    const tlsCA = boundedFile(config.tlsCA);
    requireValue(new X509Certificate(tlsCA).ca, 'CREDENTIAL_INVALID');
    return { certificate, privateKey, tlsCA };
  } catch { throw new AdapterError('CREDENTIAL_INVALID'); }
}
export async function openConnection(config) {
  const material = credentials(config);
  const client = new grpc.Client(config.endpoint, grpc.credentials.createSsl(material.tlsCA), {
    'grpc.max_receive_message_length': 65536,
    'grpc.max_send_message_length': 65536,
    'grpc.enable_retries': 0,
  });
  let gateway;
  try {
    await new Promise((resolve, reject) => client.waitForReady(Date.now() + config.deadlines.ready, (error) => error ? reject(error) : resolve()));
    gateway = connect({ client, identity: { mspId: config.mspId, credentials: material.certificate },
      signer: signers.newPrivateKeySigner(material.privateKey),
      evaluateOptions: () => ({ deadline: Date.now() + config.deadlines.evaluate }),
      endorseOptions: () => ({ deadline: Date.now() + config.deadlines.endorse }),
      submitOptions: () => ({ deadline: Date.now() + config.deadlines.submit }),
      commitStatusOptions: () => ({ deadline: Date.now() + config.deadlines.commit }),
    });
    return { contract: gateway.getNetwork(config.channel).getContract(config.chaincode, 'LabchainAnchor'),
      close: () => { gateway.close(); client.close(); } };
  } catch (error) {
    gateway?.close(); client.close();
    const tls = /certificate|tls|ssl/i.test(String(error?.message ?? ''));
    throw new AdapterError(tls ? 'TLS_FAILED' : 'GATEWAY_UNAVAILABLE');
  }
}
