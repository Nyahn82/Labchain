# Phase 8B-2: dedicated client identity and local Gateway adapter

Phase 8B-1 transactional capture remains unchanged. This phase adds a dedicated
Org1 CLIENT and a local Node Gateway adapter. It does not deliver outbox rows,
create migrations, change FastAPI routes/readiness, deploy a worker, change
chaincode or reconfigure/restart Fabric.

## Retained trust hierarchy

The original full cryptogen tree exists at:

```text
blockchain/network/generated/single-vps/crypto-config/
```

It contains both peer organizations and the orderer organization, their signing
and TLS CA certificates/keys, MSPs, administrators and peer/orderer identities.
The retained Org1 signing CA matches the runtime/public Org1 MSP and peer1 MSP
trust roots. CA private key contents are never printed or copied into the
application runtime.

This is an academic single-VPS prototype. Cryptogen extension is appropriate
only because the retained hierarchy and original trusted CAs exist. A production
organization should use managed Fabric CA / organizational PKI with enrollment,
revocation, rotation and controlled CA custody.

## Provisioning

The explicit command is:

```bash
blockchain/network/scripts/provision-app-client-single-vps.sh
```

It requires Linux x86_64, user/group rhuadmin:rhuadmin, the fixed
`blockchain/network/tools/bin/cryptogen` reporting Fabric 2.5.16, the reviewed
single-VPS environment, and successful existing Phase 8A runtime validation.
A separate lock prevents concurrent client provisioning.

The helper verifies the complete source tree, CA/key matches, runtime trust
roots and retained node identities. Missing or conflicting material fails closed;
there is no new CA, self-signed client, administrator fallback or network reset.

It copies the **existing** hierarchy into private ignored staging, changes only
Org1 Users Count from 0 to 1 in a temporary configuration, and runs
`cryptogen extend --input=<staged existing hierarchy>`. It verifies that every
pre-existing crypto file is byte-for-byte unchanged and that additions are
confined to the new Org1 User1 directory. Only that new directory is published
back into the retained tree. Existing peer/orderer/admin/CA files are never
replaced. Temporary copies are cleaned up; existing crypto and ledger volumes
are never deleted.

The resulting certificate must be signed by the original CA and have client
NodeOU, with matching private key. The username is incidental; renaming an
Admin/peer certificate does not satisfy validation. A valid existing client is
validated and reused; unexpected existing identities fail safely.

## Runtime separation and permissions

Exact application directory:

```text
blockchain/network/runtime/app-client-single-vps/org1/msp/
  signcerts/User1@org1.labchain.internal-cert.pem
  keystore/<cryptogen-generated-name>_sk
  cacerts/ca.org1.labchain.internal-cert.pem
  tlscacerts/tlsca.org1.labchain.internal-cert.pem
  config.yaml
```

This is deliberately a **sibling** of `runtime/single-vps`. Phase 8A's immutable
manifest covers every file in that directory, so adding a client beneath it
would invalidate existing operational checks. No Phase 8A validator or manifest
exception was introduced.

Application directories are 0700; all copied files, including the private key,
are 0600; ownership is rhuadmin:rhuadmin. Only the five listed MSP entries are
published. No client TLS private key or organization CA private key is copied.
Git ignore and tracked-file checks run before publication and on reuse. Existing
`runtime/`, `generated/`, key and `node_modules` ignore rules already cover the
new files; no broad ignore-rule change is needed.

## Gateway boundary

See [adapter protocol and configuration](../blockchain/gateway-adapter/README.md).
The adapter is a subprocess using one bounded JSON request/result and no inbound
port. It connects to peer1 at 127.0.0.1:7051 using the existing TLS CA and verified
IP SAN, without hostname overrides or disabled certificate validation.

Actions are ping, anchor_exists, read_anchor and submit_anchor. Submit is prepared
for Phase 8B-3 and tested only with fakes in this phase. Its explicit endorsement,
submission and commit-status stages preserve transaction IDs and distinguish
invalid/uncertain commits. Success requires Fabric VALID commit status, not an
endorsement result. Block numbers are decimal strings. Errors use a finite
allowlist, fixed messages, bounded deadlines, and no raw SDK output. There are no
automatic retries or duplicate reconciliation in this adapter.

The dedicated CLIENT uses normal channel policies; it receives no administrator
or peer signing role. Gateway read validation proves the TLS connection, client
acceptance, channel access and chaincode evaluate path. It does not prove the
future cross-organization write/commit path, which is deliberately untested live.

## Validation and phase boundary

Provisioning tests build a separate synthetic network under a temporary directory.
They never provision the live client. The live provisioning command is an explicit
operation, separate from unit tests. Existing runtime validation and original
crypto fingerprints are checked after that operation.

The manual read-only validation uses the existing synthetic Phase 8A anchor
`TEST-75d3f8ae-baa4-4f51-9f6c-526e58c028b2`. No new anchor is created, and the
identifier is confined to documentation/manual commands, not adapter source.

Actual outbox delivery starts in Phase 8B-3. PENDING rows are not blockchain
anchored. Worker leases, retries, reconciliation, service deployment, status APIs,
frontend badges and public blockchain verification remain deferred. Single-host
failure and shared rhuadmin account/custody limitations remain those of the
reviewed academic prototype.
