# Single-VPS Fabric operator reference

Read the [deployment and recovery guide](../../docs/PHASE_8A_BLOCKCHAIN_NETWORK.md) first. Run from `blockchain/network`, as the restricted Fabric operator, with `.env.single-vps` and the pinned Fabric CLI installed or selected by `LABCHAIN_FABRIC_TOOLS`. These commands are for one physical VPS; legacy per-node commands are not used.

| Operation | Command |
|---|---|
| Prepare identities/artifacts without starting services | `scripts/prepare-single-vps.sh` |
| Start only orderer + peer1 | `scripts/start-foundation-single-vps.sh` |
| Verify orderer before channel creation | `scripts/single-vps-status.sh orderer` |
| Verify peer1 before channel join | `scripts/single-vps-status.sh peer1` |
| Add only peer2, then verify | `scripts/start-peer-single-vps.sh peer2`, then `scripts/single-vps-status.sh peer2` |
| Add peers 3/4 separately | Repeat the two commands above with `peer3`, then `peer4` |
| Activate ordering channel | `scripts/create-channel-single-vps.sh` |
| Join one peer | `scripts/join-channel-single-vps.sh peerN` |
| Verify joined peer | `scripts/single-vps-status.sh peerN --channel` |
| Build reviewed shared chaincode image | `scripts/deploy-chaincode-single-vps.sh build` |
| Start only one peer's anchor server | `scripts/deploy-chaincode-single-vps.sh start peerN` |
| Inspect shared package ID | `scripts/deploy-chaincode-single-vps.sh package` |
| Install on one peer | `scripts/deploy-chaincode-single-vps.sh install peerN` |
| Approve Org1 / Org2 | `scripts/deploy-chaincode-single-vps.sh approve peer1` / `approve peer3` |
| Commit / inspect definition | `scripts/deploy-chaincode-single-vps.sh commit` / `query` |
| Compare all four ledgers | `scripts/verify-network-single-vps.sh` |
| Explicit synthetic transaction and four-peer verification | `scripts/smoke-test-single-vps.sh` |
| Verify a previously committed synthetic anchor | `scripts/verify-network-single-vps.sh TEST-<UUID>` |
| Stop existing Fabric services, retain all state | `scripts/stop-single-vps.sh` |

Replace `peerN` with exactly one of `peer1`–`peer4`. Foundation startup and adding peer2 never start peer3/peer4 or anchors. Channel checks are optional until the channel is created/joined. Failures require investigation; “container Up” does not prove ledger convergence.

All four peers mount the reviewed `config/core.single-vps.yaml` read-only at `/etc/hyperledger/fabric/core.yaml` and select it with `FABRIC_CFG_PATH`. It deliberately omits `vm.endpoint`: Fabric's legacy Docker chaincode launcher is disabled and the Docker daemon health checker is not registered. `CORE_VM_ENDPOINT` must remain absent; an empty environment value does not reliably override the upstream YAML default. Peers do not mount Docker's control socket. Docker Compose manages peers and external CCAAS containers; the peer uses its configured external builder to reach the anchor services.

If health reports a failed `docker` component, verify the reviewed config mount and selection rather than granting socket access. Source changes do not alter already-running containers; applying them requires a separately scheduled operator action. Do not regenerate identities or remove ledger volumes. Network validation requires PyYAML in the Python interpreter running the scripts (`python3-yaml` on Ubuntu).

Read-only diagnostics:

```bash
docker compose --env-file .env.single-vps -f compose/docker-compose.single-vps.yml --profile '*' ps
docker compose --env-file .env.single-vps -f compose/docker-compose.single-vps.yml logs --tail=100 orderer peer1
docker compose --env-file .env.single-vps -f compose/docker-compose.single-vps.yml logs --tail=100 peer2 anchor2
docker stats --no-stream
```

`labchain-fabric` is a user-defined, non-internal Docker bridge. Fabric service-to-service communication uses Docker DNS; host-side Fabric CLI/status operations use loopback-published ports. Every published Fabric port binds only to `127.0.0.1`, with no Fabric port published on the VPS public interfaces and no UFW Fabric rules required. Containers may have normal bridge egress; inbound Fabric access from outside the VPS remains unavailable through the reviewed port mappings. This remains a one-VPS academic/prototype deployment. Runtime checks protect service mounts, version pins, separate ledgers and the complete deployment's host fingerprint. Never delete volumes, regenerate crypto or run a destructive reset to resolve a failed check. Follow the guide's fenced recovery and consistent backup procedure.
