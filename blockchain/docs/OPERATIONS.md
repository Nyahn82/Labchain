# Fabric operator reference

Use the [full deployment and recovery guide](../../docs/PHASE_8A_BLOCKCHAIN_NETWORK.md) before these commands. Run from `blockchain/network` on the appropriate VPS with its own validated `.env` and `runtime/`. Docker access requires root-equivalent operator privileges; private admin bundles must remain restricted to their intended operator.

| Operation | Command | Where |
|---|---|---|
| Prepare without starting | `scripts/prepare-node.sh` | Every VPS |
| Start with persistent state | `scripts/start-node.sh` | Every VPS after firewall verification |
| Stop without deleting state | `scripts/stop-node.sh` | Every VPS |
| Containers / peer health / channel | `scripts/network-status.sh` | Local VPS |
| Remote channel state | `scripts/network-status.sh node2` | Org1 admin on VPS 1; analogous for other peers |
| Activate channel on orderer | `scripts/create-channel.sh` | VPS 4 |
| Join Org1 peer | `scripts/join-channel.sh node1` / `node2` | VPS 1 |
| Join Org2 peer | `scripts/join-channel.sh node3` / `node4` | VPS 3 |
| Inspect package ID | `scripts/deploy-chaincode.sh package` | VPS 1 or 3 |
| Install on peer | `scripts/deploy-chaincode.sh install node2` | Its organization admin host |
| Approve organization definition | `scripts/deploy-chaincode.sh approve` | VPS 1 and VPS 3, independently |
| Commit / verify definition | `scripts/deploy-chaincode.sh commit` | VPS 1 after both approvals |
| Query definition | `scripts/deploy-chaincode.sh query` | VPS 1 or 3 |
| Compare four ledgers | `scripts/verify-network.sh` | VPS 1 or 3 |
| Submit synthetic anchor and compare peers | `scripts/smoke-test.sh` | VPS 1 or 3 |

For raw Docker inspection on VPS N, set N to its real number:

```bash
NODE_NUMBER=1
docker compose --env-file .env -f "compose/docker-compose.node${NODE_NUMBER}.yml" --profile chaincode ps
docker compose --env-file .env -f "compose/docker-compose.node${NODE_NUMBER}.yml" logs --tail=100 peer
docker compose --env-file .env -f "compose/docker-compose.node${NODE_NUMBER}.yml" logs --tail=100 anchor
docker stats --no-stream
```

On VPS 4 only:

```bash
docker compose --env-file .env -f compose/docker-compose.node4.yml logs --tail=100 orderer
curl --fail --cacert runtime/orderer/tls/ca.crt https://127.0.0.1:9444/healthz
```

Logs and health responses are not proof of cross-peer commitment. Run the channel, lifecycle and smoke checks. A status query before channel creation/join is expected to fail at the channel step; it must not be reported as a successful deployment.

There is deliberately no reset script. Normal commands do not remove volumes, identities or channel blocks. Do not use `docker compose down -v`, volume pruning, or identity regeneration to troubleshoot an existing ledger. Recovery requires the explicit procedure in the guide.
