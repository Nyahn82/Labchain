'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const AnchorContract = require('../lib/anchor-contract');
const id = 'TEST-11111111-1111-4111-8111-111111111111';
const reference = '22222222-2222-4222-8222-222222222222';
const digest = 'ab'.repeat(32);
const args = [id, 'REPORT_RELEASED', reference, digest, '', 'node1'];
function fixture(msp = 'Org1MSP') {
  const state = new Map();
  const events = [];
  return { state, events, contract: new AnchorContract(), ctx: {
    clientIdentity: { getMSPID: () => msp },
    stub: {
      getState: async (k) => state.get(k) || Buffer.alloc(0),
      putState: async (k, v) => state.set(k, v),
      getTxTimestamp: () => ({ seconds: 1750000000n, nanos: 123000000 }),
      getTxID: () => 'synthetic-transaction-id',
      setEvent: (name, payload) => events.push([name, payload]),
    },
  } };
}
test('creates only the explicit non-clinical fields using the transaction timestamp', async () => {
  const {contract,ctx,state,events}=fixture();
  const record=JSON.parse(await contract.CreateAnchor(ctx,...args));
  assert.equal(record.created_at,'2025-06-15T15:06:40.123Z');
  assert.deepEqual(Object.keys(record),['anchor_id','event_type','entity_type','entity_reference','content_hash','previous_hash','created_at','source_node','source_msp','transaction_id']);
  assert.equal(record.entity_reference,reference);
  assert.equal(state.size,1);
  assert.equal(events[0][0],'AnchorCreated');
});
test('reads a committed anchor and reports existence', async () => {
  const {contract,ctx}=fixture();
  assert.equal(await contract.AnchorExists(ctx,id),false);
  const created=await contract.CreateAnchor(ctx,...args);
  assert.equal(await contract.AnchorExists(ctx,id),true);
  assert.equal(await contract.ReadAnchor(ctx,id),created);
});
test('rejects a duplicate without changing stored bytes', async () => {
  const {contract,ctx}=fixture();
  const before=await contract.CreateAnchor(ctx,...args);
  await assert.rejects(contract.CreateAnchor(ctx,...args),/already exists/);
  assert.equal(await contract.ReadAnchor(ctx,id),before);
});
test('reports a missing record',async()=>{const {contract,ctx}=fixture();await assert.rejects(contract.ReadAnchor(ctx,id),/not found/);});
for(const bad of ['', 'a'.repeat(63),'b'.repeat(65),'g'.repeat(64),'0x'+'a'.repeat(64),'a'.repeat(63)+'\n', 'a'.repeat(64)+'\n']) {
  test(`rejects invalid hash ${JSON.stringify(bad)}`,async()=>{
    const {contract,ctx,state}=fixture();const values=[...args];values[3]=bad;
    await assert.rejects(contract.CreateAnchor(ctx,...values),/Hash/);assert.equal(state.size,0);
  });
}
test('canonicalizes uppercase hexadecimal',async()=>{const {contract,ctx}=fixture();const values=[...args];values[3]=digest.toUpperCase();assert.equal(JSON.parse(await contract.CreateAnchor(ctx,...values)).content_hash,digest);});
for(const [index,bad,reason] of [[0,'patient-name','Anchor ID'],[0,id+'\n','Anchor ID'],[2,reference+'\n','opaque UUID'],[1,'RESULT_VERIFIED','Unsupported'],[2,'PATIENT-001','opaque UUID'],[4,'bad','Hash'],[5,'node3','Source node'],[5,'__proto__','Source node']]) {
  test(`rejects unsupported or identifying field ${index}`,async()=>{const {contract,ctx,state}=fixture();const values=[...args];values[index]=bad;await assert.rejects(contract.CreateAnchor(ctx,...values),new RegExp(reason));assert.equal(state.size,0);});
}
for(const event of ['REPORT_REVOKED','REPORT_SUPERSEDED']) {
  test(`${event} appends a separate record and requires a previous hash`,async()=>{
    const {contract,ctx}=fixture();const original=await contract.CreateAnchor(ctx,...args);
    const values=['33333333-3333-4333-8333-333333333333',event,reference,digest,'','node1'];
    await assert.rejects(contract.CreateAnchor(ctx,...values),/previous hash/);
    values[4]=digest;await contract.CreateAnchor(ctx,...values);assert.equal(await contract.ReadAnchor(ctx,id),original);
  });
}
test('Org2 can submit using its own source node',async()=>{const {contract,ctx}=fixture('Org2MSP');const values=[...args];values[5]='node3';assert.equal(JSON.parse(await contract.CreateAnchor(ctx,...values)).source_msp,'Org2MSP');});
for(const operation of ['CreateAnchor','ReadAnchor','AnchorExists','GetAnchorHistory']) {
  test(`${operation} rejects non-member organizations`,async()=>{const {contract,ctx}=fixture('OtherMSP');await assert.rejects(contract[operation](ctx,...(operation==='CreateAnchor'?args:[id])),/Unauthorized/);});
}
test('exports no update or delete transaction',()=>{
  assert.deepEqual(Object.getOwnPropertyNames(AnchorContract.prototype).sort(),['constructor','CreateAnchor','ReadAnchor','AnchorExists','GetAnchorHistory'].sort());
});
test('history returns the original record and always closes its iterator',async()=>{
  const {contract,ctx}=fixture();const created=await contract.CreateAnchor(ctx,...args);let closed=false;let read=false;
  ctx.stub.getHistoryForKey=async()=>({next:async()=>read?{done:true}:(read=true,{done:false,value:{txId:'history-tx',timestamp:ctx.stub.getTxTimestamp(),isDelete:false,value:Buffer.from(created)}}),close:async()=>{closed=true;}});
  const history=JSON.parse(await contract.GetAnchorHistory(ctx,id));assert.equal(history[0].record.anchor_id,id);assert.equal(history[0].is_delete,false);assert.equal(closed,true);
});
test('history closes on iterator failure',async()=>{const {contract,ctx}=fixture();let closed=false;ctx.stub.getHistoryForKey=async()=>({next:async()=>{throw new Error('iterator failure');},close:async()=>{closed=true;}});await assert.rejects(contract.GetAnchorHistory(ctx,id),/iterator failure/);assert.equal(closed,true);});
test('missing history returns an empty list',async()=>{const {contract,ctx}=fixture();ctx.stub.getHistoryForKey=async()=>({next:async()=>({done:true}),close:async()=>{}});assert.equal(await contract.GetAnchorHistory(ctx,id),'[]');});
