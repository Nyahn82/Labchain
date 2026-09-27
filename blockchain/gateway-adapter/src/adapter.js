import { AdapterError, errorResult, validateRequest, parseAnchor, HASH, requireValue } from './protocol.js';
import { configuration, openConnection } from './connection.js';

export async function bounded(operation, timeout, code) {
  let timer;
  try {
    return await Promise.race([Promise.resolve().then(operation), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new AdapterError(code)), timeout);
    })]);
  } finally { clearTimeout(timer); }
}
function blockString(value) {
  if (value === undefined || value === null) return null;
  requireValue(typeof value === 'bigint' && value >= 0n && value <= 18446744073709551615n, 'INVALID_RESPONSE');
  return value.toString();
}
function stageError(error, fallback, receipt = {}) {
  if (error instanceof AdapterError) return new AdapterError(error.code, receipt);
  // Inspect only to classify exact deployed contract errors; never emit raw text.
  const messages = [error?.message, ...(Array.isArray(error?.details) ? error.details.map((d) => d?.message) : [])];
  if (messages.some((m) => typeof m === 'string' && m.includes('Anchor already exists.'))) return new AdapterError('ANCHOR_CONFLICT', receipt);
  if (messages.some((m) => typeof m === 'string' && m.includes('Anchor not found.'))) return new AdapterError('ANCHOR_NOT_FOUND', receipt);
  return new AdapterError(fallback, receipt);
}
export async function execute(request, env = process.env, open = openConnection) {
  let session;
  let action = null;
  let transactionId;
  const receipt = {};
  try {
    validateRequest(request);
    action = request.action;
    const config = configuration(env);
    session = await open(config);
    const contract = session.contract;
    if (action === 'ping') return { ok: true, action, result: { ready: true, msp_id: config.mspId,
      channel: config.channel, chaincode: config.chaincode, source_node: config.sourceNode } };
    if (action !== 'submit_anchor') {
      const name = action === 'anchor_exists' ? 'AnchorExists' : 'ReadAnchor';
      let bytes;
      try {
        bytes = await bounded(() => contract.newProposal(name, { arguments: [request.anchorId] }).evaluate(
          { deadline: Date.now() + config.deadlines.evaluate }), config.deadlines.evaluate, 'GATEWAY_UNAVAILABLE');
      } catch (error) { throw stageError(error, 'EVALUATION_FAILED'); }
      if (action === 'anchor_exists') {
        const result = Buffer.from(bytes).toString('utf8');
        requireValue(result === 'true' || result === 'false', 'INVALID_RESPONSE');
        return { ok: true, action, result: result === 'true' };
      }
      return { ok: true, action, result: parseAnchor(bytes, request.anchorId) };
    }
    const proposal = contract.newProposal('CreateAnchor', { arguments: [request.anchorId, request.eventType,
      request.entityReference, request.contentHash, request.previousHash ?? '', request.sourceNode] });
    transactionId = proposal.getTransactionId();
    requireValue(typeof transactionId === 'string' && HASH.test(transactionId), 'INVALID_RESPONSE');
    receipt.transaction_id = transactionId;
    let transaction;
    try { transaction = await bounded(() => proposal.endorse({ deadline: Date.now() + config.deadlines.endorse }), config.deadlines.endorse, 'ENDORSEMENT_FAILED'); }
    catch (error) { throw stageError(error, 'ENDORSEMENT_FAILED', receipt); }
    let commit;
    try { commit = await bounded(() => transaction.submit({ deadline: Date.now() + config.deadlines.submit }), config.deadlines.submit, 'SUBMISSION_FAILED'); }
    catch (error) { throw stageError(error, 'SUBMISSION_FAILED', receipt); }
    let status;
    try { status = await bounded(() => commit.getStatus({ deadline: Date.now() + config.deadlines.commit }), config.deadlines.commit, 'COMMIT_TIMEOUT'); }
    catch (error) { throw stageError(error, 'COMMIT_TIMEOUT', receipt); }
    requireValue(status.transactionId === transactionId && Number.isInteger(status.code) && status.code >= 0 && status.code <= 255, 'INVALID_RESPONSE');
    receipt.validation_code = status.code;
    receipt.block_number = blockString(status.blockNumber);
    if (status.successful !== true || status.code !== 0) throw new AdapterError('COMMIT_INVALID', receipt);
    const result = parseAnchor(transaction.getResult(), request.anchorId);
    requireValue(result.transaction_id === transactionId && result.event_type === request.eventType &&
      result.entity_reference === request.entityReference && result.content_hash === request.contentHash &&
      result.previous_hash === (request.previousHash || null) && result.source_node === config.sourceNode &&
      result.source_msp === config.mspId, 'INVALID_RESPONSE');
    return { ok: true, action, result: { ...receipt, confirmed: true, anchor: result } };
  } catch (error) {
    if (error instanceof AdapterError) error.receipt = { ...receipt, ...error.receipt };
    return errorResult(action, error);
  } finally { session?.close(); }
}
