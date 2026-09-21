'use strict';
const { Contract } = require('fabric-contract-api');

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const anchorPattern = new RegExp(`^(?:TEST-)?${UUID}$`);
const entityPattern = new RegExp(`^${UUID}$`);
const events = new Set(['REPORT_RELEASED', 'REPORT_REVOKED', 'REPORT_SUPERSEDED']);
const nodes = { node1: 'Org1MSP', node2: 'Org1MSP', node3: 'Org2MSP', node4: 'Org2MSP' };

function authorize(ctx) {
  const msp = ctx.clientIdentity.getMSPID();
  if (!['Org1MSP', 'Org2MSP'].includes(msp)) throw new Error('Unauthorized organization.');
  return msp;
}
function key(id) {
  if (typeof id !== 'string' || ![36, 41].includes(id.length) || !anchorPattern.test(id)) throw new Error('Anchor ID must be a UUIDv4, optionally prefixed TEST-.');
  return `anchor:${id}`;
}
function hash(value) {
  if (typeof value !== 'string' || value.length !== 64 || !/^[0-9a-fA-F]{64}$/.test(value)) throw new Error('Hash must contain exactly 64 hexadecimal characters.');
  return value.toLowerCase();
}
function time(timestamp) {
  return new Date(Number(timestamp.seconds.toString()) * 1000 + Math.floor(timestamp.nanos / 1000000)).toISOString();
}

class AnchorContract extends Contract {
  constructor() { super('LabchainAnchor'); }

  async CreateAnchor(ctx, anchorId, eventType, entityReference, contentHash, previousHash, sourceNode) {
    const msp = authorize(ctx);
    const stateKey = key(anchorId);
    if (!events.has(eventType)) throw new Error('Unsupported event type.');
    if (typeof entityReference !== 'string' || entityReference.length !== 36 || !entityPattern.test(entityReference)) throw new Error('Entity reference must be an opaque UUIDv4.');
    if (!Object.hasOwn(nodes, sourceNode) || nodes[sourceNode] !== msp) throw new Error('Source node does not belong to the submitting organization.');
    const content = hash(contentHash);
    const previous = previousHash === '' ? null : hash(previousHash);
    if (eventType !== 'REPORT_RELEASED' && previous === null) throw new Error('This event requires a previous hash.');
    // The read before write participates in Fabric MVCC validation; concurrent
    // duplicates cannot both commit successfully, even on different endorsers.
    if ((await ctx.stub.getState(stateKey)).length) throw new Error('Anchor already exists.');
    const record = {
      anchor_id: anchorId,
      event_type: eventType,
      entity_type: 'REPORT',
      entity_reference: entityReference,
      content_hash: content,
      previous_hash: previous,
      created_at: time(ctx.stub.getTxTimestamp()),
      source_node: sourceNode,
      source_msp: msp,
      transaction_id: ctx.stub.getTxID(),
    };
    const encoded = JSON.stringify(record);
    await ctx.stub.putState(stateKey, Buffer.from(encoded));
    ctx.stub.setEvent('AnchorCreated', Buffer.from(JSON.stringify({ anchor_id: anchorId })));
    return encoded;
  }

  async ReadAnchor(ctx, anchorId) {
    authorize(ctx);
    const value = await ctx.stub.getState(key(anchorId));
    if (!value.length) throw new Error('Anchor not found.');
    return value.toString('utf8');
  }

  async AnchorExists(ctx, anchorId) {
    authorize(ctx);
    return (await ctx.stub.getState(key(anchorId))).length > 0;
  }

  async GetAnchorHistory(ctx, anchorId) {
    authorize(ctx);
    const iterator = await ctx.stub.getHistoryForKey(key(anchorId));
    const history = [];
    try {
      for (;;) {
        const item = await iterator.next();
        if (item.value) {
          history.push({
            transaction_id: item.value.txId,
            timestamp: time(item.value.timestamp),
            is_delete: item.value.isDelete,
            record: item.value.isDelete ? null : JSON.parse(item.value.value.toString('utf8')),
          });
        }
        if (item.done) break;
      }
    } finally { await iterator.close(); }
    return JSON.stringify(history);
  }
}
module.exports = AnchorContract;
