export const MAX_INPUT = 4096;
export const MAX_OUTPUT = 16384;
export const ACTIONS = new Set(['ping', 'anchor_exists', 'read_anchor', 'submit_anchor']);
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
export const HASH = /^[0-9a-f]{64}(?![\s\S])/;
export const EVENTS = new Set(['REPORT_RELEASED', 'REPORT_REVOKED', 'REPORT_SUPERSEDED']);
const CODES = Object.freeze({
  CONFIG_INVALID: [false, 'Adapter configuration is invalid.'],
  CREDENTIAL_INVALID: [false, 'Dedicated client credentials are invalid or inaccessible.'],
  GATEWAY_UNAVAILABLE: [true, 'Gateway is unavailable.'],
  TLS_FAILED: [false, 'Gateway TLS validation failed.'],
  ENDORSEMENT_FAILED: [true, 'Transaction endorsement failed.'],
  SUBMISSION_FAILED: [true, 'Transaction submission outcome is uncertain.'],
  COMMIT_TIMEOUT: [true, 'Commit confirmation is unavailable; reconcile before retrying.'],
  COMMIT_INVALID: [false, 'Transaction committed with an invalid validation code.'],
  ANCHOR_NOT_FOUND: [false, 'Anchor was not found.'],
  ANCHOR_CONFLICT: [false, 'Anchor already exists; reconciliation is required.'],
  EVALUATION_FAILED: [true, 'Anchor evaluation failed.'],
  INVALID_INPUT: [false, 'Request does not match the adapter protocol.'],
  INVALID_RESPONSE: [false, 'Gateway response does not match the anchor contract.'],
  INTERNAL_ERROR: [false, 'Adapter action could not be completed.'],
});
export class AdapterError extends Error {
  constructor(code, receipt = {}) {
    super(CODES[code]?.[1] ?? CODES.INTERNAL_ERROR[1]);
    this.code = Object.hasOwn(CODES, code) ? code : 'INTERNAL_ERROR';
    this.receipt = receipt;
  }
}
export function requireValue(condition, code = 'INVALID_INPUT') {
  if (!condition) throw new AdapterError(code);
}
export function exactKeys(object, keys, code = 'INVALID_INPUT') {
  requireValue(object !== null && typeof object === 'object' && !Array.isArray(object), code);
  requireValue(Object.keys(object).sort().join('|') === [...keys].sort().join('|'), code);
}
export function readId(value) {
  return typeof value === 'string' && (UUID.test(value) || (value.startsWith('TEST-') && UUID.test(value.slice(5))));
}
export function validateRequest(request) {
  requireValue(request && ACTIONS.has(request.action));
  if (request.action === 'ping') exactKeys(request, ['action']);
  else if (request.action !== 'submit_anchor') {
    exactKeys(request, ['action', 'anchorId']);
    requireValue(readId(request.anchorId));
  } else {
    exactKeys(request, ['action', 'anchorId', 'eventType', 'entityReference', 'contentHash', 'previousHash', 'sourceNode']);
    requireValue(typeof request.anchorId === 'string' && UUID.test(request.anchorId));
    requireValue(typeof request.entityReference === 'string' && UUID.test(request.entityReference));
    requireValue(EVENTS.has(request.eventType) && typeof request.contentHash === 'string' && HASH.test(request.contentHash));
    requireValue(request.sourceNode === 'node1');
    const absent = request.previousHash === null || request.previousHash === '';
    requireValue((request.eventType === 'REPORT_RELEASED' && absent) ||
      (typeof request.previousHash === 'string' && HASH.test(request.previousHash)));
  }
  return request;
}
export function parseRequest(bytes) {
  try {
    requireValue(bytes.length > 0 && bytes.length <= MAX_INPUT);
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    const request = JSON.parse(text);
    validateRequest(request);
    // Requests are flat. Tokenize strings as whole tokens to detect duplicate
    // keys (JSON.parse alone silently accepts them), including escaped key names.
    const tokens = text.match(/"(?:\\.|[^"\\])*"|[{}:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g);
    const seen = new Set();
    let key = false;
    for (const token of tokens) {
      if (token === '{' || token === ',') key = true;
      else if (key) {
        const name = JSON.parse(token);
        requireValue(!seen.has(name));
        seen.add(name);
        key = false;
      }
    }
    return request;
  } catch { throw new AdapterError('INVALID_INPUT'); }
}
const ANCHOR_KEYS = ['anchor_id', 'event_type', 'entity_type', 'entity_reference', 'content_hash', 'previous_hash',
  'created_at', 'source_node', 'source_msp', 'transaction_id'];
export function parseAnchor(bytes, expectedId) {
  try {
    requireValue(bytes.length <= MAX_OUTPUT, 'INVALID_RESPONSE');
    const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    exactKeys(data, ANCHOR_KEYS, 'INVALID_RESPONSE');
    requireValue(readId(data.anchor_id) && data.anchor_id === expectedId && EVENTS.has(data.event_type) && data.entity_type === 'REPORT', 'INVALID_RESPONSE');
    requireValue(typeof data.entity_reference === 'string' && UUID.test(data.entity_reference) &&
      typeof data.content_hash === 'string' && HASH.test(data.content_hash) &&
      typeof data.transaction_id === 'string' && HASH.test(data.transaction_id), 'INVALID_RESPONSE');
    requireValue((data.event_type === 'REPORT_RELEASED' && data.previous_hash === null) ||
      (typeof data.previous_hash === 'string' && HASH.test(data.previous_hash)), 'INVALID_RESPONSE');
    const nodes = { node1: 'Org1MSP', node2: 'Org1MSP', node3: 'Org2MSP', node4: 'Org2MSP' };
    requireValue(Object.hasOwn(nodes, data.source_node) && nodes[data.source_node] === data.source_msp, 'INVALID_RESPONSE');
    requireValue(typeof data.created_at === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(data.created_at) &&
      new Date(data.created_at).toISOString() === data.created_at, 'INVALID_RESPONSE');
    return data;
  } catch { throw new AdapterError('INVALID_RESPONSE'); }
}
export function errorResult(action, error) {
  const known = error instanceof AdapterError ? error : new AdapterError('INTERNAL_ERROR');
  const [retryable, message] = CODES[known.code];
  const detail = { code: known.code, retryable, message };
  // Only fixed, non-sensitive receipt fields can leave on a failed submission.
  if (typeof known.receipt.transaction_id === 'string' && HASH.test(known.receipt.transaction_id)) detail.transaction_id = known.receipt.transaction_id;
  if (Number.isInteger(known.receipt.validation_code) && known.receipt.validation_code >= 0 && known.receipt.validation_code <= 255) detail.validation_code = known.receipt.validation_code;
  if (typeof known.receipt.block_number === 'string' && /^(0|[1-9]\d{0,19})$/.test(known.receipt.block_number)) detail.block_number = known.receipt.block_number;
  return { ok: false, action: ACTIONS.has(action) ? action : null, error: detail };
}
