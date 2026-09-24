# Phase 8A — Single-VPS Hyperledger Fabric foundation

## Status and scope

The current deployment target is **one physical Ubuntu VPS** hosting the existing FastAPI application, MySQL and Nginx, plus four real Fabric peer processes/containers, one Raft orderer and four external chaincode services. This is an academic/prototype topology with logical organization separation. It is **not infrastructure decentralized or physically decentralized**: one VPS failure takes down all peers and the orderer. The single orderer also remains a single availability point. Future production deployment should distribute organizations and ordering nodes across independently operated hosts, with separately controlled administrator keys.

The repository changes have been validated offline only. **No Fabric services were started, and no live commit or restart-persistence claim is made.** No FastAPI workflow, MySQL schema, Alembic migration, Nginx configuration, frontend, patient portal or report-release workflow changes are included. MySQL remains the operational source of truth. Phase 8B application integration has not begun.

The old `docker-compose.node1.yml` through `node4.yml`, `.env.example`, and per-node scripts remain as legacy separate-VPS infrastructure. Do not run them for this deployment or combine their host-network containers on this VPS. Existing four-host runtime, genesis blocks and ledger volumes are not converted by preparation. A deployed legacy network requires a separately reviewed migration; never regenerate keys over existing ledgers.

## Topology and ports

Use `blockchain/network/compose/docker-compose.single-vps.yml`. All services join one user-defined Docker **bridge** named `labchain-fabric`, with `internal: false`. A normal, non-internal bridge supports the loopback-published ports used by the host CLI/status scripts on the deployed Docker Engine. None uses host networking. No Docker socket is mounted. Every published Fabric port binds only to `127.0.0.1`; no Fabric port is published on the VPS public interfaces and no UFW Fabric rules are required. Containers may have normal bridge egress; inbound Fabric access from outside the VPS remains unavailable through the reviewed port mappings. The public host surface remains SSH 22 and web 80/443.

| Service | Container | Organization | Internal ports | Host mappings, all bound to `127.0.0.1` |
|---|---|---|---|---|
| `orderer` | `labchain-orderer` | OrdererMSP | 7050 TLS ordering, 7053 mTLS admin, 9444 HTTPS operations | 7050→7050, 7053→7053, 9444→9444 |
| `peer1` | `labchain-peer1` | Org1MSP | 7051 TLS peer/gossip, 7052 chaincode listener, 9443 HTTPS operations | 7051→7051, 9443→9443 |
| `peer2` | `labchain-peer2` | Org1MSP | 7051, 7052, 9443 | 8051→7051, 9445→9443 |
| `peer3` | `labchain-peer3` | Org2MSP | 7051, 7052, 9443 | 9051→7051, 9446→9443 |
| `peer4` | `labchain-peer4` | Org2MSP | 7051, 7052, 9443 | 10051→7051, 9447→9443 |
| `anchor1`–`anchor4` | `labchain-anchor1`–`labchain-anchor4` | Separate server for each peer | 9999 TLS | None |

The loopback mappings support native host Fabric CLI, osnadmin and curl commands in the supplied scripts. They are enabled in this implementation, not required by Fabric itself. Removing them would require replacing the host CLI/health workflow. There is no optional public mapping. Do not publish 7052 or 9999. Check for host port conflicts before bring-up.

Fabric service-to-service communication uses Docker DNS. Containers use `peer1:7051` through `peer4:7051` and `orderer:7050`. Gossip bootstrap pairs are peer1↔peer2 and peer3↔peer4; external endpoints use each peer's service DNS. Channel anchor peers are peer1 and peer3. Each peer directly receives ordering blocks. No fake public IPs, host DNS entries or `/etc/hosts` edits are needed. TLS SANs cover the actual service names; peer/orderer certificates also support loopback host administration.

Fabric remains **2.5.16**, using the reviewed peer/orderer image digests and tool archive checksum in `network/versions.json`. Chaincode stays JavaScript with the existing pinned Node 22.23.2 image and locked Fabric libraries 2.5.8. No version pins or application dependencies changed.

## Identities, ledgers and chaincode

Preparation uses the existing cryptogen prototype approach with new DNS-aware templates. Runtime layout:

```text
blockchain/network/runtime/single-vps/
  node1/peer/{msp,tls}/       # unique peer1 private identity
  node1/chaincode/tls/       # unique anchor1 server certificate/key
  node1/chaincode.env        # shared package ID
  node2/{peer,chaincode}/    # unique peer2/anchor2 material; also chaincode.env
  node3/{peer,chaincode}/    # unique peer3/anchor3 material; also chaincode.env
  node4/{peer,chaincode}/    # unique peer4/anchor4 material; also chaincode.env
  orderer/{msp,tls}/
  admin/org1/{msp,tls}/      # host administration only, never mounted in peers
  admin/org2/{msp,tls}/
  orderer-admin/{msp,tls}/   # dedicated client TLS identity for osnadmin
  public/                   # organization roots, genesis block, CCAAS package/ID
  host-fingerprint
  manifest.json
  COMPLETE
```

Every peer has separate signing/MSP and TLS private keys. Each anchor has another independent TLS private key. Organizational trust roots are shared as required by Fabric; peer private keys are not. Bind mounts are read-only and limited to the particular service identity. Runtime directories/files use modes 0700/0600. Anchor containers use the preparing operator's UID/GID so they can read their restricted TLS files.

Separate named persistent volumes are:

- `labchain-peer1-ledger`
- `labchain-peer2-ledger`
- `labchain-peer3-ledger`
- `labchain-peer4-ledger`
- `labchain-orderer-ledger`

Normal scripts only stop/restart containers and never delete these volumes. Keep the same deployment path, Compose project, volume names and identities on restart. All peers use LevelDB with history enabled.

All four peers install the same deterministic `labchain-anchor` CCAAS package. Its address is `{{.address}}:9999`; per-peer `CHAINCODE_AS_A_SERVICE_BUILDER_CONFIG` resolves that to `anchor1:9999` through `anchor4:9999`. This uses [Fabric's supported multi-peer CCAAS templates](https://hyperledger-fabric.readthedocs.io/en/release-2.5/cc_basic.html#running-with-multiple-peers), keeping the package ID consistent within each organization while using separate services. TLS is required and verifies each anchor's DNS name against its organization TLS CA. The package contains public roots only, with no private client key. Anchor services publish no host port; peers reach them over the Fabric bridge using Docker DNS. Treat membership in this bridge as trusted operator access; the prototype uses server-authenticated CCAAS TLS, not client mutual TLS.

Channel `labchain-channel`, chaincode `labchain-anchor`, version `1.0.0`, sequence `1` and the policy `AND('Org1MSP.peer','Org2MSP.peer')` are unchanged. Org1 and Org2 must both approve and endorse. Commit/invoke explicitly target peer1 and peer3; automatic endpoint failover is outside this phase. CCAAS package IDs identify connection metadata, not JavaScript image contents: use the reviewed image/source and do not rebuild changed contract code under an approved version.

The unchanged contract exposes `CreateAnchor`, `ReadAnchor`, `AnchorExists` and `GetAnchorHistory`, with no update/delete transaction. Only opaque UUID references, permitted event names, hashes, source organization/node and transaction metadata are stored. Duplicate anchors are rejected; revocation/supersession append new records. Never use patient identifiers or clinical data in smoke tests. No document hashing or clinical verification is implemented here.

## Preparation: no services start

Use a restricted Fabric operator with Docker privileges, separate from the application account. Docker privileges are root-equivalent. The paths below show the reviewed checkout at `/opt/rhu-labchain`; scripts are path-relative and can be deployed to a dedicated operator-owned checkout instead. Do not grant the application user access to runtime keys. The single-VPS configuration uses shared settings only, with no `NODE_ID`, `NODE1_IP`–`NODE4_IP`, or `FIREWALL_READY` bypass.

Prerequisites: Linux x86_64 Ubuntu, Docker Engine/Compose (2.24+), Python 3, Bash, OpenSSL, curl, util-linux/flock and pinned Fabric native tools. Reserve capacity for FastAPI/MySQL/Nginx before Fabric: configured memory caps total 8.25 GiB (4×1536 MiB peers, 4×384 MiB anchors, 768 MiB orderer), plus the application, OS, builds and headroom. CPU caps total 7 CPUs across services; they are limits, not reservations or throughput guarantees. Monitor growing ledger storage and certificate expiry.

Review `free -h`, `df -h`, `ss -lnt`, clock synchronization and existing service health without changing clinical records. Do not install/upgrade host software or alter UFW as an automatic part of these scripts.

```bash
cd /opt/rhu-labchain/blockchain/network
# First use only; preserve an existing .env.single-vps.
cp -n .env.single-vps.example .env.single-vps
chmod 600 .env.single-vps
# Choose either the checksum-verifying installer or existing pinned tools:
scripts/install-tools.sh
# On this VPS the existing pinned tools can instead be selected with:
# export LABCHAIN_FABRIC_TOOLS=/opt/rhu-fabric/fabric-samples
scripts/prepare-single-vps.sh
```

Preparation validates the non-internal bridge and loopback-only port publishing, generates the separate identities, channel block and shared package, checks native package ID/TLS material, and records **one fingerprint for the complete deployment**. It does not build images, start containers, modify firewall rules or touch the application. It checks Docker volumes read-only and refuses fresh identities when any single-VPS ledger already exists without runtime. Repeating preparation preserves completed artifacts; incomplete state or modified artifacts fail closed. A preparation lock prevents concurrent generation.

Signing CAs are created under ignored `generated/single-vps/crypto-config/`, never mounted into containers or included in public artifacts. Protect that directory with encrypted offline custody before startup; it is not needed by normal start/status/lifecycle scripts. Never commit generated identities or keys. `.gitignore` covers generated crypto, runtime bundles, private keys, admin material and local configuration while allowing the new example template.

## Bring up one peer at a time

Run these commands manually, inspecting each result before continuing. Initial status checks deliberately work **before channel creation**: peer status checks HTTPS health and lists channels; orderer status checks HTTPS health and queries its mTLS participation API. A missing channel is normal at this stage. Failure to connect or an unhealthy process is not success; investigate and repeat the status command after readiness.

```bash
# Only these two services start; no anchors, peer2, peer3 or peer4.
scripts/start-foundation-single-vps.sh
scripts/single-vps-status.sh orderer
scripts/single-vps-status.sh peer1

# Only peer2 starts here.
scripts/start-peer-single-vps.sh peer2
scripts/single-vps-status.sh peer2

# Explicit later steps, each followed by verification.
scripts/start-peer-single-vps.sh peer3
scripts/single-vps-status.sh peer3
scripts/start-peer-single-vps.sh peer4
scripts/single-vps-status.sh peer4
```

All starts specify services and `--no-deps --no-build`. Fabric images may be pulled by Compose at this explicit startup step if absent. Services have profiles; an unqualified `compose up` does not start every peer. Do not use `--profile '*' up`. Peer1/peer3 can log missing bootstrap partners until peer2/peer4 are explicitly started. There is no separate-host fingerprint restriction between the four peers.

## Channel, chaincode and synthetic acceptance

After all four peers have passed initial health checks:

```bash
scripts/create-channel-single-vps.sh
scripts/join-channel-single-vps.sh peer1
scripts/join-channel-single-vps.sh peer2
scripts/join-channel-single-vps.sh peer3
scripts/join-channel-single-vps.sh peer4
scripts/single-vps-status.sh peer1 --channel
scripts/single-vps-status.sh peer2 --channel
scripts/single-vps-status.sh peer3 --channel
scripts/single-vps-status.sh peer4 --channel

# Explicit image build and separate service starts; does not start other peers.
scripts/deploy-chaincode-single-vps.sh build
scripts/deploy-chaincode-single-vps.sh package
scripts/deploy-chaincode-single-vps.sh start peer1
scripts/deploy-chaincode-single-vps.sh start peer2
scripts/deploy-chaincode-single-vps.sh start peer3
scripts/deploy-chaincode-single-vps.sh start peer4
scripts/deploy-chaincode-single-vps.sh install peer1
scripts/deploy-chaincode-single-vps.sh install peer2
scripts/deploy-chaincode-single-vps.sh install peer3
scripts/deploy-chaincode-single-vps.sh install peer4
scripts/deploy-chaincode-single-vps.sh approve peer1
scripts/deploy-chaincode-single-vps.sh approve peer3
scripts/deploy-chaincode-single-vps.sh commit
scripts/deploy-chaincode-single-vps.sh query
scripts/verify-network-single-vps.sh
scripts/smoke-test-single-vps.sh
```

Creation/join/install retain existing objects; approval explicitly submits an organization transaction. Commit checks both approvals and verifies the committed definition's actual policy bytes. The explicit smoke test submits one synthetic `TEST-UUID` anchor endorsed by both organizations and reads it from **all four peers**, comparing record/transaction IDs, block heights, current and previous block hashes. Convergence retries are bounded; evidence stays under ignored `artifacts/single-vps/validation.*`. A lagging or missing peer fails acceptance. Container status alone does not prove commitment.

Before claiming operational readiness, collect successful live synthetic evidence, confirm no public Fabric listener, and test restart persistence during a planned maintenance window: stop using the supplied stop script, restart only the services already introduced using the same staged commands, restart the corresponding anchors, and run `verify-network-single-vps.sh TEST-<previous-UUID>`. Do not regenerate identities, remove volumes or recreate the channel. Check the existing application remains healthy independently of Fabric. No live acceptance commands were executed during this topology change.

## Stop, backup and recovery

```bash
scripts/stop-single-vps.sh
```

This stops existing single-VPS services while retaining containers, ledgers and identities. It can still stop services when certificate validation fails. There is no reset script. Never use `down -v`, pruning, volume deletion, a new genesis block or replacement identities as ordinary troubleshooting.

Back up all five ledger volumes with the matching complete runtime, `.env.single-vps`, channel/package artifacts and reviewed source/version pins. Back up signing CAs separately under encrypted access control. A MySQL backup is not a Fabric backup. For consistent prototype snapshots, stop Fabric services first and verify they are stopped; preserve ownership and modes. Do not blindly copy live LevelDB/Raft directories. Plan the outage: one host and one orderer have no availability failover.

A copied deployment is rejected on another machine by `runtime/single-vps/host-fingerprint`. For **explicit disaster recovery**, fence the old VPS so no duplicate peer/orderer identities run; restore all matching identities and consistent ledgers on the replacement; verify checksums, certificate validity and version pins; then, only as an authorized recovery operation, update the one fingerprint using `sha256sum /etc/machine-id` (store only the hash). Preserve `manifest.json` and all identities/channel artifacts. Re-run preparation validation before staged startup and verify prior synthetic records. No normal script rewrites this fingerprint. The manifest detects accidental runtime changes and is not an external signed attestation.

Certificate renewal and upgrades require a reviewed procedure updating certificates and the artifact manifest together; a runtime mismatch must not be bypassed casually. Chaincode server certificates expire after one year. Keep trusted roots/identities consistent and validate new SANs. Cryptogen is a prototype bootstrap, not a production enrollment/revocation service. Longer-term production work should establish independent administration, CA operations and distributed multi-orderer availability.

## Static validation

Commands executed for this change (no daemon service launch):

```bash
cd /opt/rhu-labchain
docker compose --env-file blockchain/network/.env.single-vps.example \
  -f blockchain/network/compose/docker-compose.single-vps.yml --profile '*' config --quiet
LABCHAIN_FABRIC_TOOLS=/opt/rhu-fabric/fabric-samples \
  python3 -m unittest discover -s blockchain/network/tests -v
for script in blockchain/network/scripts/*.sh; do bash -n "$script"; done
npm test --prefix blockchain/chaincode/labchain-anchor
git diff --check
```

The suite uses temporary synthetic crypto and a recording Docker stub for startup-selection tests. Native tests inspect real Fabric-generated blocks, TLS certificates and package IDs; they do not launch a network. Current results: **37 network tests passed with no skips; 31 existing chaincode tests passed; new and legacy Compose rendering and all Bash syntax checks passed.** Validation used Compose 5.5.1, Fabric native tools 2.5.16 and host Node 24.21.0. The deployment image remains pinned to Node 22.23.2; its build/runtime were not exercised here. Full backend/frontend regression was not needed because no shared Python application, application dependency or frontend file changed. No migration, volume removal, destructive reset or service startup occurred.
