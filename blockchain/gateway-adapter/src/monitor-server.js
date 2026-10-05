#!/usr/bin/env node
// Local, allowlisted read service. Unix socket permissions are its trust boundary.
import net from 'node:net';
import fs from 'node:fs';
import { config, executeMonitor, validateRequest } from './monitor.js';

process.removeAllListeners('warning');
process.on('warning', () => {});
const socket = '/run/rhu-labchain-monitor/monitor.sock';
process.umask(0o007);
let active = 0;
let cached = null;
let cachedAt = 0;
const lastSuccess = new Map();
const server = net.createServer(connection => {
  if (active >= 4) { connection.end('{"ok":false,"error":"BUSY"}\n'); return; }
  active++;
  let size = 0; let input = ''; let consumed = false; let running = false; let released = false;
  const release = () => { if (!released) { active--; released = true; } };
  const timer = setTimeout(() => connection.destroy(), 11000);
  connection.on('error', () => {});
  connection.once('close', () => { clearTimeout(timer); if (!running) release(); });
  connection.on('data', async bytes => {
    size += bytes.length;
    if (size > 2048 || consumed) { connection.destroy(); return; }
    input += bytes.toString('utf8');
    if (!input.endsWith('\n')) return;
    consumed = true;
    running = true;
    let output;
    try {
      const request = JSON.parse(input);
      validateRequest(request);
      let result;
      if (request.action === 'overview' && cached && Date.now() - cachedAt < 5000) result = cached;
      else {
        result = await executeMonitor(request, config());
        if (request.action === 'overview') {
          for (const node of result.nodes) {
            if (node.last_success_at) lastSuccess.set(node.name, node.last_success_at);
            else node.last_success_at = lastSuccess.get(node.name) ?? null;
          }
          cached = result; cachedAt = Date.now();
        }
      }
      output = JSON.stringify({ ok: true, result });
      if (Buffer.byteLength(output) > 1024 * 1024) throw new Error();
    } catch { output = '{"ok":false,"error":"QUERY_UNAVAILABLE"}'; }
    finally { running = false; release(); }
    connection.end(output + '\n');
  });
});
// Fail on an existing socket; systemd RuntimeDirectory removes stale state.
server.on('error', () => { process.stderr.write('Monitor could not start.\n'); process.exit(1); });
server.listen(socket, () => fs.chmodSync(socket, 0o660));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => server.close(() => process.exit(0)));
