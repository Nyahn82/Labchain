// Read-only Fabric queries. No endorse/submit/commit or Docker API exists here.
import fs from 'node:fs';
import https from 'node:https';
import { createHash } from 'node:crypto';
import * as grpc from '@grpc/grpc-js';
import { connect, signers } from '@hyperledger/fabric-gateway';
import { common, gateway, peer } from '@hyperledger/fabric-protos';
import { configuration, credentials } from './connection.js';
import { parseAnchor } from './protocol.js';

export const CHANNEL = 'labchain-channel';
export const CHAINCODE = 'labchain-anchor';
export const PEERS = [
  { name: 'peer1', msp: 'Org1MSP', port: 7051 },
  { name: 'peer2', msp: 'Org1MSP', port: 8051 },
  { name: 'peer3', msp: 'Org2MSP', port: 9051 },
  { name: 'peer4', msp: 'Org2MSP', port: 10051 },
];
const HASH = /^[0-9a-f]{64}$/;
const UINT = /^(0|[1-9][0-9]{0,15})$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_BLOCK = 8 * 1024 * 1024;
const TIMEOUT = 2500;
export class MonitorError extends Error {
  constructor(code = 'QUERY_FAILED') { super(code); this.code = code; }
}
function ensure(condition, code = 'INVALID_RESPONSE') { if (!condition) throw new MonitorError(code); }
export function number(value) {
  const text = String(value);
  ensure(UINT.test(text) && Number.isSafeInteger(Number(text)), 'INVALID_NUMBER');
  return Number(text);
}
function digest(bytes) { return createHash('sha256').update(bytes).digest('hex'); }
function hash(bytes, empty = false) {
  const data = Buffer.from(bytes);
  ensure(data.length === 32 || (empty && data.length === 0));
  return data.length ? data.toString('hex') : null;
}
// Fabric hashes ASN.1 DER BlockHeader, NOT protobuf BlockHeader or block bytes.
function der(tag, bytes) {
  const length = bytes.length;
  const size = length < 128 ? Buffer.from([length]) : (() => {
    let hex = length.toString(16); if (hex.length % 2) hex = '0' + hex;
    const value = Buffer.from(hex, 'hex'); return Buffer.concat([Buffer.from([0x80 + value.length]), value]);
  })();
  return Buffer.concat([Buffer.from([tag]), size, bytes]);
}
export function blockHash(header) {
  let hex = number(header.getNumber()).toString(16);
  if (hex.length % 2) hex = '0' + hex;
  let integer = Buffer.from(hex, 'hex');
  if (integer[0] & 0x80) integer = Buffer.concat([Buffer.from([0]), integer]);
  return digest(der(0x30, Buffer.concat([der(2, integer),
    der(4, Buffer.from(header.getPreviousHash_asU8())), der(4, Buffer.from(header.getDataHash_asU8()))])));
}
export function ledgerInfo(bytes) {
  const info = common.BlockchainInfo.deserializeBinary(bytes);
  return { height: number(info.getHeight()), current_block_hash: hash(info.getCurrentblockhash_asU8()),
    previous_block_hash: hash(info.getPreviousblockhash_asU8(), true) };
}
function transaction(envelopeBytes, code = null) {
  const envelope = common.Envelope.deserializeBinary(envelopeBytes);
  const payload = common.Payload.deserializeBinary(envelope.getPayload_asU8());
  const header = common.ChannelHeader.deserializeBinary(payload.getHeader().getChannelHeader_asU8());
  const id = header.getTxId();
  ensure(!id || HASH.test(id));
  const timestamp = header.getTimestamp();
  const seconds = timestamp ? number(timestamp.getSeconds()) : null;
  const time = seconds === null ? null : new Date(seconds * 1000).toISOString();
  const label = code === null ? 'UNKNOWN' : Object.entries(peer.TxValidationCode).find(([, v]) => v === code)?.[0] ?? 'UNKNOWN';
  return { transaction_id: id || null, validation_code: code, validation_status: label, timestamp: time };
}
export function blockDetail(bytes) {
  ensure(bytes.length <= MAX_BLOCK);
  const block = common.Block.deserializeBinary(bytes);
  const header = block.getHeader();
  ensure(header && block.getData());
  const data = block.getData().getDataList_asU8();
  ensure(data.length <= 1000, 'LIMIT_EXCEEDED');
  // Validate the block data hash before displaying the header hash.
  ensure(digest(Buffer.concat(data.map(x => Buffer.from(x)))) === hash(header.getDataHash_asU8()));
  const filter = block.getMetadata()?.getMetadataList_asU8()[common.BlockMetadataIndex.TRANSACTIONS_FILTER];
  const transactions = data.map((bytes, i) => transaction(bytes, filter?.[i] ?? null));
  return { number: number(header.getNumber()), block_hash: blockHash(header),
    previous_block_hash: hash(header.getPreviousHash_asU8(), true), transaction_count: data.length,
    timestamp: transactions.find(t => t.timestamp)?.timestamp ?? null, transactions };
}
export function definition(bytes) {
  const result = peer.lifecycle.QueryChaincodeDefinitionResult.deserializeBinary(bytes);
  const version = result.getVersion();
  ensure(/^[A-Za-z0-9._-]{1,64}$/.test(version));
  const policy = peer.ApplicationPolicy.deserializeBinary(result.getValidationParameter_asU8());
  // Only a safe channel policy reference is exposed; signature principals stay private.
  const reference = policy.getChannelConfigPolicyReference();
  return { name: CHAINCODE, version, sequence: number(result.getSequence()),
    endorsement_policy: /^\/[A-Za-z0-9/_-]{1,120}$/.test(reference) ? reference : 'Signature policy (details withheld)' };
}
export function config(env = process.env) {
  const base = configuration(env);
  return { ...base, peers: PEERS.map((p, i) => ({ ...p, tlsCA: env[`MONITOR_PEER${i + 1}_TLS_CA_PATH`] })),
    ordererCA: env.MONITOR_ORDERER_TLS_CA_PATH };
}
function publicCA(path) {
  ensure(typeof path === 'string' && path.startsWith('/'), 'NOT_CONFIGURED');
  const fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try { const st = fs.fstatSync(fd); ensure(st.isFile() && st.size <= 65536); return fs.readFileSync(fd); }
  finally { fs.closeSync(fd); }
}
export async function openPeer(config, target) {
  let material;
  try { material = credentials(config); } catch { throw new MonitorError('NOT_CONFIGURED'); }
  let ca;
  try { ca = publicCA(target.tlsCA); } catch { throw new MonitorError('NOT_CONFIGURED'); }
  const endpoint = `127.0.0.1:${target.port}`;
  const client = new peer.EndorserClient(endpoint, grpc.credentials.createSsl(ca), {
    'grpc.max_receive_message_length': MAX_BLOCK, 'grpc.max_send_message_length': 65536, 'grpc.enable_retries': 0,
  });
  return directSession(config, client, material);
}
export function directSession(config, client, material) {
  const sdk = connect({ client, identity: { mspId: config.mspId, credentials: material.certificate } });
  const signer = signers.newPrivateKeySigner(material.privateKey);
  return {
    // Send directly to this peer's Endorser, so Gateway discovery cannot silently
    // evaluate on another peer and misattribute its height. Never submit the result.
    async query(contract, name, args) {
      const proposal = sdk.getNetwork(CHANNEL).getContract(contract).newProposal(name, { arguments: args });
      const signed = gateway.ProposedTransaction.deserializeBinary(proposal.getBytes()).getProposal();
      signed.setSignature(await signer(proposal.getDigest()));
      const response = await new Promise((resolve, reject) => client.processProposal(signed,
        { deadline: Date.now() + TIMEOUT }, (error, value) => error ? reject(new MonitorError(
          error.code === grpc.status.DEADLINE_EXCEEDED ? 'TIMEOUT' : 'UNAVAILABLE')) : resolve(value)));
      const result = response.getResponse();
      ensure(result?.getStatus() === 200, 'QUERY_FAILED');
      return result.getPayload_asU8();
    },
    close() { sdk.close(); client.close(); },
  };
}
export function ordererHealth(caPath) {
  return new Promise((resolve) => {
    const finish = status => resolve({ name: 'orderer', status, signal: 'TLS operations /healthz', height: null });
    let ca; try { ca = publicCA(caPath); } catch { finish('UNKNOWN'); return; }
    const request = https.get({ hostname: '127.0.0.1', port: 9444, path: '/healthz', ca, rejectUnauthorized: true }, response => {
      const parts = []; let size = 0;
      response.on('data', chunk => { size += chunk.length; if (size > 4096) request.destroy(); else parts.push(chunk); });
      response.on('end', () => {
        try { finish(response.statusCode === 200 && JSON.parse(Buffer.concat(parts)).status === 'OK' ? 'ONLINE' : 'DEGRADED'); }
        catch { finish('UNKNOWN'); }
      });
      response.on('error', () => finish('UNKNOWN'));
    });
    const timer = setTimeout(() => { request.destroy(); finish('OFFLINE'); }, TIMEOUT);
    request.on('close', () => clearTimeout(timer));
    request.on('error', () => finish('OFFLINE'));
  });
}
export function validateRequest(r) {
  ensure(r && typeof r === 'object' && !Array.isArray(r), 'INVALID_REQUEST');
  const keys = { overview: ['action'], blocks: ['action', 'before', 'limit'], block: ['action', 'number'],
    transaction: ['action', 'transaction_id'], anchor: ['action', 'anchor_id'] }[r.action];
  ensure(keys && Object.keys(r).sort().join() === keys.sort().join(), 'INVALID_REQUEST');
  if (r.action === 'blocks') {
    ensure(Number.isInteger(r.limit) && r.limit >= 1 && r.limit <= 10, 'INVALID_REQUEST');
    if (r.before !== null) number(r.before);
  }
  if (r.action === 'block') number(r.number);
  if (r.action === 'transaction') ensure(HASH.test(r.transaction_id), 'INVALID_REQUEST');
  if (r.action === 'anchor') ensure(UUID.test(r.anchor_id), 'INVALID_REQUEST');
}
export async function executeMonitor(request, cfg, open = openPeer, health = ordererHealth) {
  validateRequest(request);
  const checked = new Date().toISOString();
  if (request.action === 'overview') {
    const nodes = await Promise.all(cfg.peers.map(async target => {
      const node = { name: target.name, msp: target.msp, status: 'UNKNOWN', channel_member: null,
        height: null, current_block_hash: null, previous_block_hash: null, checked_at: checked,
        last_success_at: null, error_code: null };
      let session;
      try {
        session = await open(cfg, target);
        Object.assign(node, ledgerInfo(await session.query('qscc', 'GetChainInfo', [CHANNEL])),
          { status: 'ONLINE', channel_member: true, last_success_at: checked });
      } catch (e) {
        node.error_code = e instanceof MonitorError ? e.code : 'QUERY_FAILED';
        node.status = ['TIMEOUT', 'UNAVAILABLE'].includes(node.error_code) ? 'OFFLINE' : 'UNKNOWN';
        if (node.error_code === 'QUERY_FAILED') node.status = 'DEGRADED';
      } finally { session?.close(); }
      return node;
    }));
    const heights = nodes.filter(n => n.height !== null).map(n => n.height);
    const max = heights.length ? Math.max(...heights) : null;
    for (const node of nodes) if (node.status === 'ONLINE' && node.height < max) node.status = 'DEGRADED';
    const tips = new Set(nodes.filter(n => n.height === max).map(n => n.current_block_hash));
    if (tips.size > 1) for (const node of nodes) if (node.height === max) node.status = 'DEGRADED';
    const orderer = await health(cfg.ordererCA);
    let chaincode = null;
    const target = cfg.peers.find(p => nodes.some(n => n.name === p.name && n.height !== null));
    let session;
    if (target) try {
      session = await open(cfg, target);
      const args = new peer.lifecycle.QueryChaincodeDefinitionArgs(); args.setName(CHAINCODE);
      chaincode = definition(await session.query('_lifecycle', 'QueryChaincodeDefinition', [args.serializeBinary()]));
    } catch { /* Explicit unknown definition; never substitute configured version. */ }
    finally { session?.close(); }
    return { channel: CHANNEL, topology: 'SINGLE_VPS', checked_at: checked, nodes, orderer, chaincode,
      status: nodes.every(n => n.status === 'ONLINE') && orderer.status === 'ONLINE' && chaincode ? 'ONLINE'
        : nodes.every(n => n.status === 'OFFLINE') ? 'OFFLINE'
          : heights.length ? 'DEGRADED' : 'UNKNOWN', ledger_height: max };
  }
  // A bounded query on one explicitly identified peer, never a scan of the ledger.
  const session = await open(cfg, cfg.peers[0]);
  try {
    const query = (name, args) => session.query('qscc', name, [CHANNEL, ...args]);
    if (request.action === 'blocks') {
      const info = ledgerInfo(await query('GetChainInfo', []));
      const start = Math.min(request.before ?? info.height, info.height) - 1;
      const numbers = Array.from({ length: Math.max(0, Math.min(request.limit, start + 1)) }, (_, i) => start - i);
      const items = [];
      // Batches of at most 5 cap concurrent in-flight protobuf memory.
      for (let i = 0; i < numbers.length; i += 5) {
        items.push(...await Promise.all(numbers.slice(i, i + 5).map(async n => {
          const b = blockDetail(await query('GetBlockByNumber', [String(n)]));
          ensure(b.number === n); const { transactions, ...summary } = b; return summary;
        })));
      }
      return { items, next_before: items.length && items.at(-1).number > 0 ? items.at(-1).number : null,
        ledger_height: info.height, source_peer: 'peer1', checked_at: checked };
    }
    if (request.action === 'block') {
      const b = blockDetail(await query('GetBlockByNumber', [String(request.number)]));
      ensure(b.number === number(request.number));
      return { ...b, source_peer: 'peer1', checked_at: checked };
    }
    if (request.action === 'transaction') {
      const b = blockDetail(await query('GetBlockByTxID', [request.transaction_id]));
      const tx = b.transactions.find(t => t.transaction_id === request.transaction_id); ensure(tx);
      return { ...tx, block_number: b.number, block_hash: b.block_hash, source_peer: 'peer1', checked_at: checked };
    }
    const anchor = parseAnchor(await session.query(CHAINCODE, 'LabchainAnchor:ReadAnchor', [request.anchor_id]), request.anchor_id);
    return { anchor_id: anchor.anchor_id, entity_reference: anchor.entity_reference, event_type: anchor.event_type,
      content_hash: anchor.content_hash, previous_hash: anchor.previous_hash, transaction_id: anchor.transaction_id,
      source_peer: 'peer1', checked_at: checked };
  } finally { session.close(); }
}
