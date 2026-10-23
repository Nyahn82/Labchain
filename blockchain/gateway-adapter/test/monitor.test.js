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

test('anchor evidence retains validated organization binding without clinical payload', async () => {
  const id = '00000000-0000-4000-8000-000000000001';
  const anchor = { anchor_id: id, event_type: 'REPORT_RELEASED', entity_type: 'REPORT', entity_reference: '00000000-0000-4000-8000-000000000002', content_hash: H, previous_hash: null, created_at: '2026-10-19T00:00:00.000Z', source_node: 'node1', source_msp: 'Org1MSP', transaction_id: H };
  const open = async () => ({ query: async () => Buffer.from(JSON.stringify(anchor)), close() {} });
  const result = await executeMonitor({ action: 'anchor', anchor_id: id }, cfg, open);
  assert.equal(result.source_node, 'node1'); assert.equal(result.source_msp, 'Org1MSP');
  assert.deepEqual(Object.keys(result).sort(), ['anchor_id','entity_reference','event_type','content_hash','previous_hash','transaction_id','source_node','source_msp','source_peer','checked_at'].sort());
  anchor.source_msp = 'Org2MSP';
  await assert.rejects(executeMonitor({ action: 'anchor', anchor_id: id }, cfg, open));
});

test('four-peer report evidence queries independent sessions and committed anchor writes', async () => {
  const { ledger, msp } = await import('@hyperledger/fabric-protos');
  const id = '00000000-0000-4000-8000-000000000001';
  const anchor = { anchor_id:id, entity_type:'REPORT', entity_reference:'00000000-0000-4000-8000-000000000002', event_type:'REPORT_RELEASED', content_hash:H, previous_hash:null, source_node:'node1', source_msp:'Org1MSP', transaction_id:H, created_at:'2026-10-23T00:00:00.000Z' };
  function committed(code=0, channel='labchain-channel', commitment=H) {
    const write=new ledger.rwset.kvrwset.KVWrite();write.setKey('anchor:'+id);write.setValue(Buffer.from(JSON.stringify({...anchor,content_hash:commitment})));
    const kv=new ledger.rwset.kvrwset.KVRWSet();kv.setWritesList([write]);
    const ns=new ledger.rwset.NsReadWriteSet();ns.setNamespace('labchain-anchor');ns.setRwset(kv.serializeBinary());
    const set=new ledger.rwset.TxReadWriteSet();set.setNsRwsetList([ns]);
    const ccid=new peer.ChaincodeID();ccid.setName('labchain-anchor');
    const ca=new peer.ChaincodeAction();ca.setChaincodeId(ccid);ca.setResults(set.serializeBinary());
    const proposal=new peer.ProposalResponsePayload();proposal.setExtension$(ca.serializeBinary());
    const endorsed=new peer.ChaincodeEndorsedAction();endorsed.setProposalResponsePayload(proposal.serializeBinary());
    const cap=new peer.ChaincodeActionPayload();cap.setAction(endorsed);
    const action=new peer.TransactionAction();action.setPayload(cap.serializeBinary());
    const tx=new peer.Transaction();tx.setActionsList([action]);
    const ch=new common.ChannelHeader();ch.setChannelId(channel);ch.setTxId(H);ch.setType(common.HeaderType.ENDORSER_TRANSACTION);
    const creator=new msp.SerializedIdentity();creator.setMspid('Org1MSP');creator.setIdBytes(Buffer.from('synthetic'));
    const sh=new common.SignatureHeader();sh.setCreator(creator.serializeBinary());
    const head=new common.Header();head.setChannelHeader(ch.serializeBinary());head.setSignatureHeader(sh.serializeBinary());
    const payload=new common.Payload();payload.setHeader(head);payload.setData(tx.serializeBinary());
    const env=new common.Envelope();env.setPayload(payload.serializeBinary());
    const b=block(2,code);b.getData().setDataList([env.serializeBinary()]);b.getHeader().setDataHash(createHash('sha256').update(env.serializeBinary()).digest());
    return b.serializeBinary();
  }
  assert.doesNotThrow(() => committed());
  const request={action:'report_evidence',events:[{anchor_id:id,transaction_id:H,block_number:2}]};
  for (const failure of [null,'peer1','lagging','invalid','conflict','bad-channel','timeout-and-invalid','timeout-and-conflict']) {
    const calls=[],closed=[];
    const result=await executeMonitor(request,cfg,async(_,target)=>({
      async query(contract,name,args) {
        calls.push([target.name,name]);
        if(target.name===failure) throw new MonitorError('UNAVAILABLE');
        if(name==='GetChainInfo') return info(failure==='lagging'&&target.name==='peer4'?2:3);
        if(name==='GetBlockByNumber') return committed(['invalid','timeout-and-invalid'].includes(failure)&&target.name==='peer3'?11:0,failure==='bad-channel'&&target.name==='peer3'?'other-channel':'labchain-channel',failure==='timeout-and-conflict'&&target.name==='peer3'?'b'.repeat(64):H);
        if(name==='LabchainAnchor:ReadAnchor') {
          if(['timeout-and-invalid','timeout-and-conflict'].includes(failure)&&target.name==='peer3') throw new MonitorError('TIMEOUT');
          return Buffer.from(JSON.stringify({...anchor,content_hash:failure==='conflict'&&target.name==='peer3'?'b'.repeat(64):H}));
        }
        assert.fail(name);
      },close(){closed.push(target.name);}
    }));
    assert.deepEqual(result.peers.map(p=>p.peer),PEERS.map(p=>p.name));
    assert.equal(new Set(closed).size,4);
    const state=p=>result.peers.find(x=>x.peer===p).events[0];
    if(failure===null) {
      assert(result.peers.every(p=>p.events[0].status==='OBSERVED'));
      assert(PEERS.every(p=>calls.filter(c=>c[0]===p.name).length===3));
      assert(result.peers.every(p=>p.events[0].evidence.transaction.creator_msp==='Org1MSP'));
    } else if(failure==='peer1') {
      assert.equal(state('peer1').status,'OFFLINE');
      assert(result.peers.slice(1).every(p=>p.events[0].status==='OBSERVED'));
    } else if(failure==='lagging') assert.equal(state('peer4').status,'LAGGING');
    else if(failure==='invalid') assert.equal(state('peer3').evidence.transaction.validation_code,11);
    else if(failure==='conflict') assert.equal(state('peer3').status,'CONFLICT');
    else if(failure==='bad-channel') assert.equal(state('peer3').status,'FAILED');
    else {
      assert.equal(state('peer3').status,'TIMEOUT');
      if(failure==='timeout-and-invalid') assert.equal(state('peer3').evidence.transaction.validation_code,11);
      else assert.equal(state('peer3').evidence.anchor.content_hash,'b'.repeat(64)); // backend must reject known invalid evidence
    }
  }
  assert.throws(()=>validateRequest({...request,events:Array(5).fill(request.events[0])}));
  assert.throws(()=>validateRequest({...request,events:[...request.events,...request.events]}));
});
