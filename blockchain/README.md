# RHU LabChain Fabric foundation — Phase 8A

This directory contains infrastructure for **four separate Linux VPS hosts**, two Fabric peer organizations, one Raft orderer, and an append-only integrity-anchor contract. It does not connect FastAPI to Fabric and does not anchor production reports.

**Status:** repository artifacts and offline tests are available. A live four-VPS deployment and cross-peer commit/convergence evidence are still required before claiming that the network is operational. No Docker daemon or four-host access was available during repository validation.

Start with [the Phase 8A deployment guide](../docs/PHASE_8A_BLOCKCHAIN_NETWORK.md). It contains prerequisites, exact node-by-node commands, firewall rules, identity distribution, lifecycle steps, acceptance checks, backup and recovery procedures.

- [`network/compose/`](network/compose/): one Compose definition per VPS; never combine them on one host.
- [`network/config/`](network/config/): cryptogen prototype and channel configuration templates.
- [`network/scripts/`](network/scripts/): validated configuration, bootstrap, node operations, lifecycle and synthetic smoke tests.
- [`network/versions.json`](network/versions.json): pinned versions, image digests and CLI archive checksum.
- [`chaincode/labchain-anchor/`](chaincode/labchain-anchor/): JavaScript contract, dependency lock, pinned Node runtime and unit tests.
- [`network/tests/`](network/tests/): offline configuration, identity, packaging and verification tests.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md): operator command reference.

Generated `network/runtime/`, `network/generated/`, identity bundles, local tools and private key material are ignored by Git. Never distribute the entire bootstrap directory to a VPS.

MySQL remains the operational source of truth. The database's existing blockchain-support tables are unchanged and are not themselves a blockchain. Automatic anchoring belongs to Phase 8B.
