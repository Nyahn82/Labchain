#!/usr/bin/env node
import { parseRequest, MAX_INPUT, MAX_OUTPUT, AdapterError, errorResult } from './protocol.js';
import { execute } from './adapter.js';

// Node's default warning handler can emit internal paths/stacks. Keep this
// subprocess boundary diagnostic-only; TLS verification remains unchanged.
process.removeAllListeners('warning');
process.on('warning', () => process.stderr.write('Adapter runtime warning.\n'));

async function input() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    const timer = setTimeout(() => finish(new AdapterError('INVALID_INPUT')), 5000);
    const finish = (error) => {
      clearTimeout(timer);
      process.stdin.removeAllListeners();
      process.stdin.pause();
      error ? reject(error) : resolve(Buffer.concat(chunks));
    };
    process.stdin.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_INPUT) finish(new AdapterError('INVALID_INPUT'));
      else chunks.push(chunk);
    });
    process.stdin.once('end', () => finish());
    process.stdin.once('error', () => finish(new AdapterError('INVALID_INPUT')));
  });
}
let result;
try {
  if (process.argv.length !== 2) throw new AdapterError('INVALID_INPUT');
  result = await execute(parseRequest(await input()));
} catch (error) { result = errorResult(null, error); }
let output = JSON.stringify(result);
if (Buffer.byteLength(output) > MAX_OUTPUT) {
  result = errorResult(result.action, new AdapterError('INVALID_RESPONSE'));
  output = JSON.stringify(result);
}
// One result, then terminate even if an OS/network handle survives cancellation.
process.stdout.write(output + '\n', () => process.exit(result.ok ? 0 : 1));
