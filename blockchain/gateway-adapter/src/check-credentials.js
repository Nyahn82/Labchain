#!/usr/bin/env node
// Offline only: no Gateway connection, evaluate, submit, or database access.
import { configuration, credentials } from './connection.js';
process.removeAllListeners('warning');
process.on('warning', () => process.stderr.write('Adapter runtime warning.\n'));
let result;
try {
  if (process.argv.length !== 2) throw new Error();
  credentials(configuration());
  result = { ok: true };
} catch {
  result = { ok: false, code: 'CREDENTIAL_INVALID' };
}
process.stdout.write(JSON.stringify(result) + '\n', () => process.exit(result.ok ? 0 : 1));
