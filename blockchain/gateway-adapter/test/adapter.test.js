import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { execute } from '../src/adapter.js';
import { parseRequest, parseAnchor, errorResult, AdapterError, MAX_INPUT } from '../src/protocol.js';
import { configuration } from '../src/connection.js';

const id = '11111111-1111-4111-8111-111111111111';
const entity = '22222222-2222-4222-8222-222222222222';
const txid = 'a'.repeat(64);
const request = { action: 'submit_anchor', anchorId: id, eventType: 'REPORT_RELEASED', entityReference: entity,
  contentHash: 'b'.repeat(64), previousHash: null, sourceNode: 'node1' };
const env = { BLOCKCHAIN_GATEWAY_TLS_CA_PATH: '/synthetic/tls.crt', BLOCKCHAIN_CLIENT_CERT_PATH: '/synthetic/client.crt', BLOCKCHAIN_CLIENT_KEY_PATH: '/synthetic/key', BLOCKCHAIN_COMMIT_TIMEOUT_MS: '100', BLOCKCHAIN_ENDORSE_TIMEOUT_MS: '100', BLOCKCHAIN_SUBMIT_TIMEOUT_MS: '100', BLOCKCHAIN_EVALUATE_TIMEOUT_MS: '100' };
const anchor = { anchor_id: id, event_type: request.eventType, entity_type: 'REPORT', entity_reference: entity,
  content_hash: request.contentHash, previous_hash: null, created_at: '2026-09-27T12:00:00.000Z',
  source_node: 'node1', source_msp: 'Org1MSP', transaction_id: txid };
function fake(options = {}) {
  const calls = [];
  const fail = (stage) => { if (options.fail === stage) throw new Error('PRIVATE KEY synthetic secret patient-name'); };
  const open = async () => ({
    contract: { newProposal(name, args) {
      calls.push([name, args]);
      return { getTransactionId: () => txid,
        evaluate: async (deadline) => {
          calls.push(['evaluate', deadline]); fail('evaluate');
          if (options.fail === 'missing') throw { details: [{ message: 'Anchor not found.' }] };
          if (options.hang === 'evaluate') return new Promise(() => {});
          return Buffer.from(options.read ?? (name === 'AnchorExists' ? 'true' : JSON.stringify({ ...anchor, anchor_id: args.arguments[0] })));
        },
        endorse: async (deadline) => {
          calls.push(['endorse', deadline]); fail('endorse');
          if (options.fail === 'conflict') throw { details: [{ message: 'Anchor already exists.' }] };
          if (options.hang === 'endorse') return new Promise(() => {});
          return {
            getResult: () => Buffer.from(JSON.stringify(options.anchor ?? anchor)),
            submit: async (deadline) => {
              calls.push(['submit', deadline]); fail('submit');
              if (options.hang === 'submit') return new Promise(() => {});
              return { getStatus: async (deadline) => {
                calls.push(['commit', deadline]); fail('commit');
                if (options.hang === 'commit') return new Promise(() => {});
                return options.status ?? { transactionId: txid, code: 0, successful: true, blockNumber: 9007199254740993n };
              } };
            },
          };
        },
      };
    } },
    close: () => calls.push(['close']),
  });
  return { calls, open };
}

test('strict request JSON, bounded UTF-8 and no duplicate keys', () => {
  assert.deepEqual(parseRequest(Buffer.from(JSON.stringify(request))), request);
  for (const text of ['', '{}', 'null', '[]', '{"action":"ping"}\n{}', '{"action":"ping","action":"ping"}', '{"action":"ping","\\u0061ction":"ping"}', '{"action":"ping","patient":"private"}']) {
    assert.throws(() => parseRequest(Buffer.from(text)), { code: 'INVALID_INPUT' });
  }
  assert.throws(() => parseRequest(Buffer.alloc(MAX_INPUT + 1)), { code: 'INVALID_INPUT' });
  assert.throws(() => parseRequest(Buffer.from([0xff])), { code: 'INVALID_INPUT' });
});
for (const [field, value] of [['anchorId', 'TEST-' + id], ['anchorId', id + '\n'], ['entityReference', id.replace('-4111-', '-5111-')],
  ['contentHash', 'A'.repeat(64)], ['contentHash', 'b'.repeat(64) + '\n'], ['eventType', 'PATIENT'], ['sourceNode', 'node2'], ['previousHash', 'bad'], ['patientName', 'private']]) {
  test(`submit rejects ${field}=${JSON.stringify(value)}`, () => assert.throws(() => parseRequest(Buffer.from(JSON.stringify({ ...request, [field]: value }))), { code: 'INVALID_INPUT' }));
}
for (const eventType of ['REPORT_REVOKED', 'REPORT_SUPERSEDED']) {
  test(`${eventType} requires previous hash`, () => {
    assert.throws(() => parseRequest(Buffer.from(JSON.stringify({ ...request, eventType }))), { code: 'INVALID_INPUT' });
    assert.equal(parseRequest(Buffer.from(JSON.stringify({ ...request, eventType, previousHash: 'c'.repeat(64) }))).eventType, eventType);
  });
}
test('read actions accept TEST IDs and reject trailing whitespace', () => {
  assert.equal(parseRequest(Buffer.from(JSON.stringify({ action: 'read_anchor', anchorId: 'TEST-' + id }))).anchorId, 'TEST-' + id);
  assert.throws(() => parseRequest(Buffer.from(JSON.stringify({ action: 'anchor_exists', anchorId: id + '\n' }))));
});
test('configuration rejects unsafe values and deadline bounds', () => {
  assert.equal(configuration(env).mspId, 'Org1MSP');
  for (const change of [{ BLOCKCHAIN_CLIENT_KEY_PATH: 'relative' }, { BLOCKCHAIN_GATEWAY_ENDPOINT: 'public.example:7051' },
    { BLOCKCHAIN_CLIENT_MSP_ID: 'Org2MSP' }, { BLOCKCHAIN_SOURCE_NODE: 'node-1' }, { BLOCKCHAIN_CHANNEL: 'other' },
    { BLOCKCHAIN_READY_TIMEOUT_MS: '0' }, { BLOCKCHAIN_COMMIT_TIMEOUT_MS: '60001' }, { BLOCKCHAIN_SUBMIT_TIMEOUT_MS: 'Infinity' }]) {
    assert.throws(() => configuration({ ...env, ...change }), { code: 'CONFIG_INVALID' });
  }
});
test('ping has no chaincode invocation', async () => {
  const f = fake();
  assert.equal((await execute({ action: 'ping' }, env, f.open)).ok, true);
  assert.deepEqual(f.calls, [['close']]);
});
test('valid commit, exact argument order, bigint string, stage deadlines and close', async () => {
  const f = fake();
  const result = await execute(request, env, f.open);
  assert.equal(result.ok, true);
  assert.deepEqual(f.calls[0], ['CreateAnchor', { arguments: [id, 'REPORT_RELEASED', entity, 'b'.repeat(64), '', 'node1'] }]);
  assert.deepEqual(f.calls.map((c) => c[0]), ['CreateAnchor', 'endorse', 'submit', 'commit', 'close']);
  assert.equal(result.result.block_number, '9007199254740993');
  assert.equal(result.result.validation_code, 0);
  assert.equal(result.result.confirmed, true);
  assert.equal(result.result.transaction_id, txid);
  for (const [, options] of f.calls.slice(1, 4)) assert.equal(typeof options.deadline, 'number');
});
for (const stage of ['endorse', 'submit', 'commit', 'evaluate']) {
  test(`sanitized ${stage} failure and no retry`, async () => {
    const f = fake({ fail: stage });
    const result = await execute(stage === 'evaluate' ? { action: 'read_anchor', anchorId: id } : request, env, f.open);
    assert.equal(result.ok, false);
    assert.equal(result.error.code, { endorse: 'ENDORSEMENT_FAILED', submit: 'SUBMISSION_FAILED', commit: 'COMMIT_TIMEOUT', evaluate: 'EVALUATION_FAILED' }[stage]);
    assert.ok(!JSON.stringify(result).includes('PRIVATE KEY'));
    assert.ok(!JSON.stringify(result).includes('patient-name'));
    assert.equal(f.calls.filter((c) => c[0] === stage).length, 1);
    assert.equal(f.calls.at(-1)[0], 'close');
    if (stage !== 'evaluate') assert.equal(result.error.transaction_id, txid);
  });
  test(`${stage} timeout is bounded`, async () => {
    const f = fake({ hang: stage });
    const start = Date.now();
    const result = await execute(stage === 'evaluate' ? { action: 'read_anchor', anchorId: id } : request, env, f.open);
    assert.equal(result.ok, false);
    assert.ok(Date.now() - start < 1500);
    assert.equal(f.calls.at(-1)[0], 'close');
  });
}
for (const status of [{ code: 11, successful: false, blockNumber: 7n }, { code: 0, successful: false }, { code: 11, successful: true }]) {
  test(`commit must be VALID and successful: ${status.code}/${status.successful}`, async () => {
    const result = await execute(request, env, fake({ status: { transactionId: txid, ...status } }).open);
    assert.equal(result.ok, false);
    assert.equal(result.error.code, 'COMMIT_INVALID');
    assert.equal(result.error.validation_code, status.code);
  });
}
test('endorsement result alone is never confirmation; timeout retains transaction ID', async () => {
  const result = await execute(request, env, fake({ hang: 'commit' }).open);
  assert.equal(result.error.code, 'COMMIT_TIMEOUT');
  assert.equal(result.error.transaction_id, txid);
  assert.equal(result.result, undefined);
});
test('block number may be absent and commit remains confirmed', async () => {
  const result = await execute(request, env, fake({ status: { transactionId: txid, code: 0, successful: true } }).open);
  assert.equal(result.ok, true); assert.equal(result.result.block_number, null);
});
test('read result validates schema and anchor ID', async () => {
  const f = fake();
  const result = await execute({ action: 'read_anchor', anchorId: 'TEST-' + id }, env, f.open);
  assert.equal(result.result.anchor_id, 'TEST-' + id);
  assert.equal(f.calls[0][0], 'ReadAnchor');
  for (const change of [{ patient: 'private' }, { anchor_id: entity }, { content_hash: 'bad' }, { source_msp: 'unknown' }, { created_at: 'private' }]) {
    assert.throws(() => parseAnchor(Buffer.from(JSON.stringify({ ...anchor, ...change })), id), { code: 'INVALID_RESPONSE' });
  }
});
for (const value of ['true', 'false', '"true"', '{}', 'true\n']) {
  test(`exists boolean response ${JSON.stringify(value)}`, async () => {
    const result = await execute({ action: 'anchor_exists', anchorId: id }, env, fake({ read: value }).open);
    if (['true', 'false'].includes(value)) assert.equal(result.result, value === 'true');
    else assert.equal(result.error.code, 'INVALID_RESPONSE');
  });
}
test('known chaincode errors map to finite codes', async () => {
  assert.equal((await execute(request, env, fake({ fail: 'conflict' }).open)).error.code, 'ANCHOR_CONFLICT');
  assert.equal((await execute({ action: 'read_anchor', anchorId: id }, env, fake({ fail: 'missing' }).open)).error.code, 'ANCHOR_NOT_FOUND');
});
test('unknown errors have deterministic safe serialization', () => {
  assert.deepEqual(errorResult('private', new Error('SECRET')), { ok: false, action: null, error: { code: 'INTERNAL_ERROR', retryable: false, message: 'Adapter action could not be completed.' } });
  assert.equal(JSON.stringify(errorResult('ping', new AdapterError('unknown', { secret: 'PRIVATE' }))).includes('PRIVATE'), false);
});
test('CLI emits exactly one controlled JSON error and nonzero exit', () => {
  const run = spawnSync(process.execPath, ['src/cli.js'], { input: '{"action":"ping","secret":"PRIVATE"}', encoding: 'utf8', timeout: 3000 });
  assert.equal(run.status, 1); assert.equal(run.stderr, '');
  assert.equal(run.stdout.trim().split('\n').length, 1);
  assert.equal(JSON.parse(run.stdout).error.code, 'INVALID_INPUT');
  assert.ok(!run.stdout.includes('PRIVATE'));
});


test('known commit receipt survives a malformed chaincode response', async () => {
  const result = await execute(request, env, fake({ anchor: { ...anchor, patient: 'PRIVATE' } }).open);
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'INVALID_RESPONSE');
  assert.equal(result.error.transaction_id, txid);
  assert.equal(result.error.validation_code, 0);
  assert.equal(result.error.block_number, '9007199254740993');
  assert.ok(!JSON.stringify(result).includes('PRIVATE'));
});
