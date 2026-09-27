# Local Fabric Gateway adapter — Phase 8B-2

This private Node 24 package is a one-request subprocess, not a network service.
It does not listen on a port or access MySQL. Python outbox delivery, retries,
leases, status APIs and UI belong to later phases.

Runtime dependencies are pinned exactly to `@hyperledger/fabric-gateway` 1.12.0
and `@grpc/grpc-js` 1.14.5. The latter avoids the advisories affecting 1.14.0–1.14.3.
Use `npm ci --ignore-scripts --omit=optional` for repeatable installation. The
optional PKCS#11 native module is unnecessary for the prototype's EC file signer.
`node_modules` and private credentials are ignored by Git. Neither installation
nor unit tests provision a live identity or submit a live transaction.

## Configuration and credentials

See `.env.example`; pass values in the child environment. No `.env` loader or
shell evaluation exists in the adapter. Endpoint, MSP, channel, chaincode and
source node are restricted to this reviewed single-VPS topology:
`127.0.0.1:7051`, `Org1MSP`, `labchain-channel`, `labchain-anchor`, `node1`.

Use the dedicated normal CLIENT provisioned by
`../network/scripts/provision-app-client-single-vps.sh`. Admin, peer and orderer
signing identities are prohibited. The client certificate must have `OU=client`,
be currently valid, match its EC P-256 private key, and chain directly to the CA
in the sibling MSP `cacerts` directory. It is not acceptable to rename an admin
certificate to look like a client.

Credential files are bounded regular files, with direct symlinks refused. The
private key must belong to the process user, have mode 0600, and reside in a 0700
directory. The key is loaded only for signing and never sent in arguments or
output. Do not put key contents in an environment variable.

Peer TLS uses the existing Org1 TLS CA and normal certificate/hostname checking.
There is no insecure gRPC option or hostname override. Peer1's certificate has
127.0.0.1 in its SAN. Node currently emits an IP-address SNI deprecation warning
for this gRPC connection; the CLI renders runtime warnings as a fixed sanitized
diagnostic. That warning does not bypass certificate verification.

All five stage deadlines are explicit. Environment overrides accept integer
milliseconds from 100 through 60000. Standard input has a fixed 5-second deadline
and 4096-byte maximum; output is bounded to 16384 bytes. gRPC messages are bounded
to 65536 bytes. gRPC retries are disabled and the adapter does not retry actions.

## Protocol

Invoke `node src/cli.js`, write exactly one UTF-8 JSON object to stdin, and close
stdin. No CLI arguments are accepted. Stdout contains exactly one JSON result;
stderr contains only sanitized diagnostics. Exit 0 means action success;
nonzero means controlled failure. Unexpected fields and duplicate JSON keys
are rejected.

Requests:

```json
{"action":"ping"}
{"action":"anchor_exists","anchorId":"TEST-11111111-1111-4111-8111-111111111111"}
{"action":"read_anchor","anchorId":"TEST-11111111-1111-4111-8111-111111111111"}
```

Submit request (protocol example only; do not use for live Phase 8B-2 validation):

```json
{"action":"submit_anchor","anchorId":"11111111-1111-4111-8111-111111111111","eventType":"REPORT_RELEASED","entityReference":"22222222-2222-4222-8222-222222222222","contentHash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","previousHash":null,"sourceNode":"node1"}
```

Submit IDs must be lowercase UUIDv4 without `TEST-`. Read/exists also accept
`TEST-` UUIDv4. Hashes are lowercase 64-character hex. Event types are
REPORT_RELEASED, REPORT_REVOKED, REPORT_SUPERSEDED. Null/empty previous hashes
are allowed only for release; other events require a hash. A release may also
provide a hash, matching the deployed contract. Phase 8B-1 producers use null.

`ping` validates configuration/credentials and waits for TLS gRPC readiness. It
does not prove channel authorization. `anchor_exists` returns a boolean;
`read_anchor` returns the exact validated ten-field chaincode anchor object.
Unexpected response fields are rejected, never passed through.

Success envelope:

```json
{"ok":true,"action":"anchor_exists","result":true}
```

Submit follows `newProposal → endorse → submit → getStatus`. The six CreateAnchor
arguments are anchorId, eventType, entityReference, contentHash, previousHash,
sourceNode, in that order. An endorsement response is not confirmation. Success
requires `successful === true`, validation code 0, matching transaction ID and
matching returned anchor data. The result contains:

```text
transaction_id, validation_code, block_number (decimal string or null),
confirmed=true, anchor
```

Block numbers never cross JSON as JavaScript numbers. Failed transactions return
no success result. Where known, sanitized errors include transaction ID, validation
code and block number so the future worker can reconcile an uncertain outcome.
A timeout after submission does not prove failure to commit. The adapter never
reconciles, overwrites, or retries an existing anchor automatically.

Failure envelope:

```json
{"ok":false,"action":"submit_anchor","error":{"code":"COMMIT_TIMEOUT","retryable":true,"message":"Commit confirmation is unavailable; reconcile before retrying."}}
```

Finite codes: CONFIG_INVALID, CREDENTIAL_INVALID, GATEWAY_UNAVAILABLE, TLS_FAILED,
ENDORSEMENT_FAILED, SUBMISSION_FAILED, COMMIT_TIMEOUT, COMMIT_INVALID,
ANCHOR_NOT_FOUND, ANCHOR_CONFLICT, EVALUATION_FAILED, INVALID_INPUT,
INVALID_RESPONSE, INTERNAL_ERROR. Messages are fixed strings. Invalid/unrecognized
request actions return `action: null`. No raw peer errors, stack traces, PEM,
proposal bytes, clinical content or arbitrary SDK metadata are serialized.

## Manual read-only validation

After provisioning, from the repository root, explicitly set the environment:

```bash
export BLOCKCHAIN_GATEWAY_ENDPOINT=127.0.0.1:7051
export BLOCKCHAIN_GATEWAY_TLS_CA_PATH="$PWD/blockchain/network/runtime/single-vps/public/org1-tls-ca.crt"
export BLOCKCHAIN_CLIENT_MSP_ID=Org1MSP
client_msp="$PWD/blockchain/network/runtime/app-client-single-vps/org1/msp"
client_certs=("$client_msp"/signcerts/*)
client_keys=("$client_msp"/keystore/*)
export BLOCKCHAIN_CLIENT_CERT_PATH="${client_certs[0]}"
export BLOCKCHAIN_CLIENT_KEY_PATH="${client_keys[0]}"
export BLOCKCHAIN_CHANNEL=labchain-channel
export BLOCKCHAIN_CHAINCODE=labchain-anchor
export BLOCKCHAIN_SOURCE_NODE=node1
printf '%s\n' '{"action":"ping"}' | node blockchain/gateway-adapter/src/cli.js
printf '%s\n' '{"action":"anchor_exists","anchorId":"TEST-75d3f8ae-baa4-4f51-9f6c-526e58c028b2"}' | node blockchain/gateway-adapter/src/cli.js
printf '%s\n' '{"action":"read_anchor","anchorId":"TEST-75d3f8ae-baa4-4f51-9f6c-526e58c028b2"}' | node blockchain/gateway-adapter/src/cli.js
```

This anchor is an explicit manual test fixture, never hard-coded into runtime
source. These actions only evaluate existing ledger state. Do not call
`submit_anchor` against the live network during Phase 8B-2.

## Tests

`npm test` uses Node's built-in test runner, fake proposals/transactions and
temporary synthetic certificates. No live submit test exists. `npm run check`
checks modern JavaScript syntax; there is no TypeScript build step.

See [Phase 8B-2 implementation notes](../../docs/PHASE_8B_GATEWAY_ADAPTER.md).
