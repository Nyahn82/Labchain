# RHU LabChain Fabric foundation — Phase 8A

The deployment target is **one Ubuntu VPS** running the existing FastAPI/MySQL/Nginx stack plus four real Fabric peer containers, two peer organizations, one Raft orderer and four external anchor services. Each peer has separate identities and persistent ledger storage. This academic prototype is **not physically decentralized**: one VPS failure takes down the whole Fabric network, and its single orderer is an availability point. Future production deployment should distribute organizations and orderers across independent hosts.

Start with the [single-VPS deployment guide](../docs/PHASE_8A_BLOCKCHAIN_NETWORK.md) and [operator reference](docs/OPERATIONS.md). Bring-up explicitly starts orderer + peer1, verifies them, then adds/verifies peer2, peer3 and peer4 individually before channel and chaincode deployment.

- [`network/compose/docker-compose.single-vps.yml`](network/compose/docker-compose.single-vps.yml): user-defined, non-internal `labchain-fabric` Docker bridge, loopback-only host CLI/health ports, five distinct ledger volumes.
- [`network/.env.single-vps.example`](network/.env.single-vps.example): shared configuration, no per-host node/IP inventory.
- [`network/config/`](network/config/): separate single-VPS cryptogen/channel templates alongside preserved legacy templates.
- [`network/scripts/`](network/scripts/): explicit `single-vps` preparation, staged startup, status, channel/lifecycle and synthetic checks.
- [`network/versions.json`](network/versions.json): unchanged reviewed Fabric 2.5.16 and image/tool pins.
- [`network/tests/`](network/tests/): offline topology, configuration, crypto, package and guarded-command tests.
- [`chaincode/labchain-anchor/`](chaincode/labchain-anchor/): unchanged append-only synthetic integrity contract and unit tests.

Fabric service-to-service communication uses Docker DNS. Host-side Fabric CLI/status operations use published ports bound exclusively to `127.0.0.1`; no Fabric port is published on the VPS public interfaces and no UFW Fabric rules are required. Containers may have normal bridge egress; inbound Fabric access from outside the VPS remains unavailable through the reviewed port mappings.

Peers share the read-only [`core.single-vps.yaml`](network/config/core.single-vps.yaml) based on Fabric 2.5.16. Its `vm.endpoint` is intentionally unconfigured, disabling the legacy Docker chaincode launcher and preventing Docker daemon health-check registration. Chaincode remains in external CCAAS services; peers never mount Docker's control socket. Docker Compose manages both peer and CCAAS containers externally.

Legacy per-node Compose files/scripts target separate VPSs and must not be used for the single-VPS deployment. Generated crypto, runtime identities/admin keys, bundles and local configuration remain Git-ignored.

Only offline validation has been performed; no Fabric services were started during the topology change. Live commitment and persistence still need explicit administrator acceptance. There is no application integration, migration or production report anchoring; MySQL remains the operational source of truth. Phase 8B is outside this work.
