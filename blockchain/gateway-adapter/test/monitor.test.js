import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, verify } from 'node:crypto';
import { common, peer } from '@hyperledger/fabric-protos';
import timestamp from 'google-protobuf/google/protobuf/timestamp_pb.js';
import { PEERS, MonitorError, executeMonitor, ledgerInfo, blockDetail, blockHash, validateRequest, number, definition, directSession } from '../src/monitor.js';

const H = 'a'.repeat(64);
function info(height = 3) {
  const b = new common.BlockchainInfo(); b.setHeight(height);
  b.setCurrentblockhash(Buffer.alloc(32, 1)); b.setPreviousblockhash(Buffer.alloc(32, 2)); return b.serializeBinary();
}
function block(n = 2, code = 0) {
  const ch = new common.ChannelHeader(); ch.setTxId(H);
  const ts = new timestamp.Timestamp(); ts.setSeconds(1791072000); ch.setTimestamp(ts);
  const header = new common.Header(); header.setChannelHeader(ch.serializeBinary());
  const payload = new common.Payload(); payload.setHeader(header); payload.setData(Buffer.from('PRIVATE CLINICAL PAYLOAD'));
  const env = new common.Envelope(); env.setPayload(payload.serializeBinary()); env.setSignature(Buffer.from('PRIVATE SIGNATURE'));
  const data = new common.BlockData(); data.setDataList([env.serializeBinary()]);
  const bh = new common.BlockHeader(); bh.setNumber(n); bh.setPreviousHash(Buffer.alloc(32, 2));
  bh.setDataHash(createHash('sha256').update(env.serializeBinary()).digest());
  const meta = new common.BlockMetadata(); meta.setMetadataList([new Uint8Array(), new Uint8Array(), Buffer.from([code])]);
  const b = new common.Block(); b.setHeader(bh); b.setData(data); b.setMetadata(meta); return b;
}
function chaincode() {
  const d = new peer.lifecycle.QueryChaincodeDefinitionResult(); d.setVersion('1.0.0'); d.setSequence(1);
  const policy = new peer.ApplicationPolicy(); policy.setChannelConfigPolicyReference('/Channel/Application/Endorsement');
  d.setValidationParameter(policy.serializeBinary()); return d.serializeBinary();
}
const cfg = { peers: PEERS, ordererCA: '/fake/ca' };
const health = async () => ({ name: 'orderer', status: 'ONLINE', signal: 'TLS operations /healthz', height: null });
function opener(fail = null, heights = {}) {
  const calls = []; let closes = 0;
  return { calls, get closes() { return closes; }, open: async (_, target) => ({
    async query(contract, name, args) {
      calls.push([target.name, contract, name, args]);
      if (target.name === fail) throw new MonitorError('TIMEOUT');
      if (name === 'GetChainInfo') return info(heights[target.name] ?? 3);
      if (name === 'QueryChaincodeDefinition') return chaincode();
      if (name === 'GetBlockByNumber') return block(Number(args[1])).serializeBinary();
      if (name === 'GetBlockByTxID') return block().serializeBinary();
      throw new Error('PRIVATE ERROR /keys/secret');
    }, close() { closes++; },
  }) };
}
test('ledger heights parsed without precision loss; malformed hashes rejected', () => {
  assert.equal(ledgerInfo(info()).height, 3);
  assert.throws(() => number('9007199254740992'));
  assert.throws(() => number('-1'));
  assert.throws(() => ledgerInfo(new common.BlockchainInfo().serializeBinary()));
});
test('Fabric block hash uses DER header rather than protobuf encoding', () => {
  const header = new common.BlockHeader(); header.setNumber(0); header.setDataHash(Buffer.alloc(32, 0xaa));
  const expectedDER = Buffer.from('302702010004000420' + 'aa'.repeat(32), 'hex');
  assert.equal(blockHash(header), createHash('sha256').update(expectedDER).digest('hex'));
  assert.notEqual(blockHash(header), createHash('sha256').update(header.serializeBinary()).digest('hex'));
});
test('block metadata contains validation code and excludes signatures, payload and protobuf', () => {
  const b = blockDetail(block(2, 11).serializeBinary());
  assert.equal(b.number, 2); assert.equal(b.transaction_count, 1);
  assert.equal(b.transactions[0].transaction_id, H);
  assert.equal(b.transactions[0].validation_status, 'MVCC_READ_CONFLICT');
  assert.equal(b.transactions[0].validation_code, 11);
  assert.doesNotMatch(JSON.stringify(b), /PRIVATE|payload|signature|certificate/i);
  const broken = block(); broken.getHeader().setDataHash(Buffer.alloc(32));
  assert.throws(() => blockDetail(broken.serializeBinary()));
});
test('all four direct peer probes online with real committed definition', async () => {
  const fake = opener(); const result = await executeMonitor({ action: 'overview' }, cfg, fake.open, health);
  assert.equal(result.status, 'ONLINE'); assert.equal(result.ledger_height, 3);
  assert.deepEqual(result.nodes.map(n => n.name), PEERS.map(p => p.name));
  assert.ok(result.nodes.every(n => n.channel_member && n.last_success_at));
  assert.equal(result.chaincode.version, '1.0.0'); assert.equal(result.orderer.height, null);
  assert.equal(fake.closes, 5);
});
test('peer timeout gives partial status and does not claim worker IDLE implies health', async () => {
  const fake = opener('peer2'); const result = await executeMonitor({ action: 'overview' }, cfg, fake.open, health);
  assert.equal(result.status, 'DEGRADED'); assert.equal(result.nodes[1].status, 'OFFLINE');
  assert.equal(result.nodes[1].error_code, 'TIMEOUT'); assert.equal(result.nodes[1].height, null);
  assert.equal(result.nodes[0].status, 'ONLINE');
});
test('lagging peer is degraded, unavailable configuration is unknown', async () => {
  const fake = opener(null, { peer4: 2 });
  assert.equal((await executeMonitor({ action: 'overview' }, cfg, fake.open, health)).nodes[3].status, 'DEGRADED');
  const unknown = await executeMonitor({ action: 'overview' }, cfg, async () => { throw new MonitorError('NOT_CONFIGURED'); }, health);
  assert.equal(unknown.status, 'UNKNOWN'); assert.equal(unknown.ledger_height, null);
});
test('errors are sanitized and no fake chaincode version is returned', async () => {
  const result = await executeMonitor({ action: 'overview' }, cfg, async () => { throw new Error('PRIVATE KEY /path/password'); }, health);
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE|password|\/path/);
  assert.equal(result.chaincode, null);
});
test('block pagination is descending, exclusive and bounded at genesis', async () => {
  const fake = opener(); const first = await executeMonitor({ action: 'blocks', before: null, limit: 2 }, cfg, fake.open);
  assert.deepEqual(first.items.map(b => b.number), [2, 1]); assert.equal(first.next_before, 1);
  const last = await executeMonitor({ action: 'blocks', before: 1, limit: 2 }, cfg, fake.open);
  assert.deepEqual(last.items.map(b => b.number), [0]); assert.equal(last.next_before, null);
  assert.equal(fake.calls.filter(c => c[2] === 'GetBlockByNumber').length, 3);
});
test('block detail and transaction lookup read a single block', async () => {
  const fake = opener();
  const b = await executeMonitor({ action: 'block', number: 2 }, cfg, fake.open);
  assert.equal(b.transactions.length, 1); assert.equal(b.source_peer, 'peer1');
  const tx = await executeMonitor({ action: 'transaction', transaction_id: H }, cfg, fake.open);
  assert.equal(tx.block_number, 2); assert.equal(tx.validation_status, 'VALID');
  assert.equal(fake.calls.length, 2);
});
test('write actions, arbitrary query names, endpoints and unbounded pages are rejected', () => {
  for (const request of [{ action: 'submit_anchor' }, { action: 'overview', endpoint: 'evil' },
    { action: 'blocks', before: null, limit: 11 }, { action: 'block', number: -1 },
    { action: 'transaction', transaction_id: 'PRIVATE' }]) assert.throws(() => validateRequest(request));
  assert.equal(definition(chaincode()).endorsement_policy, '/Channel/Application/Endorsement');
});

test('direct peer transport signs a real QSCC proposal, sets a deadline and never uses Gateway evaluate/submit', async () => {
  const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  let closed = false;
  const client = {
    processProposal(signed, options, callback) {
      assert.ok(options.deadline > Date.now() && options.deadline <= Date.now() + 2500);
      assert.ok(verify('sha256', signed.getProposalBytes_asU8(), publicKey, signed.getSignature_asU8()));
      const proposal = peer.Proposal.deserializeBinary(signed.getProposalBytes_asU8());
      const payload = peer.ChaincodeProposalPayload.deserializeBinary(proposal.getPayload_asU8());
      const invocation = peer.ChaincodeInvocationSpec.deserializeBinary(payload.getInput_asU8());
      assert.equal(invocation.getChaincodeSpec().getChaincodeId().getName(), 'qscc');
      assert.deepEqual(invocation.getChaincodeSpec().getInput().getArgsList_asU8().map(x => Buffer.from(x).toString()), ['GetChainInfo', 'labchain-channel']);
      const result = new peer.Response(); result.setStatus(200); result.setPayload(info());
      const response = new peer.ProposalResponse(); response.setResponse(result); callback(null, response);
    },
    makeUnaryRequest() { assert.fail('Must not delegate to Gateway'); },
    close() { closed = true; },
  };
  const session = directSession({ mspId: 'Org1MSP' }, client, { privateKey, certificate: Buffer.from('synthetic-certificate') });
  assert.equal(ledgerInfo(await session.query('qscc', 'GetChainInfo', ['labchain-channel'])).height, 3);
  session.close(); assert.equal(closed, true);
});

test('transport timeout and chaincode errors have finite, secret-free classification', async () => {
  const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  for (const code of [4, 14]) {
    const client = { processProposal(s, o, cb) { cb({ code, message: 'PRIVATE_KEY PEM /secret' }); }, close() {} };
    const session = directSession({ mspId: 'Org1MSP' }, client, { privateKey, certificate: Buffer.from('synthetic') });
    await assert.rejects(session.query('qscc', 'GetChainInfo', ['labchain-channel']), e => e.code === (code === 4 ? 'TIMEOUT' : 'UNAVAILABLE') && !e.message.includes('PRIVATE'));
    session.close();
  }
});
