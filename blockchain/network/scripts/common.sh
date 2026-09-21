#!/usr/bin/env bash
# Shared constants and arrays are consumed by scripts sourcing this file.
# shellcheck disable=SC2034
set -euo pipefail
NETWORK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CHANNEL=labchain-channel
CHAINCODE=labchain-anchor
CC_VERSION=1.0.0
CC_SEQUENCE=1
ENDORSEMENT="AND('Org1MSP.peer','Org2MSP.peer')"
export FABRIC_LOGGING_SPEC=warn
fail() { printf '%s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || fail "Required command missing: $1"; }
load_config() {
  ENV_FILE="${LABCHAIN_ENV_FILE:-$NETWORK_DIR/.env}"
  need python3
  python3 "$NETWORK_DIR/scripts/config.py" "$ENV_FILE"
  while IFS='=' read -r key value || [[ -n "$key" ]]; do
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    export "$key=$value"
  done < "$ENV_FILE"
  FABRIC_RUN_UID="$(id -u)"
  FABRIC_RUN_GID="$(id -g)"
  export FABRIC_RUN_UID FABRIC_RUN_GID
}
use_tools() {
  local tools_dir="${LABCHAIN_FABRIC_TOOLS:-$NETWORK_DIR/tools}"
  export PATH="$tools_dir/bin:$PATH" FABRIC_CFG_PATH="$tools_dir/config"
  need peer
  [[ "$(peer version)" == *'Version: v2.5.16'* ]] || fail 'Use the pinned Fabric 2.5.16 CLI tools.'
  [[ -f "$FABRIC_CFG_PATH/core.yaml" ]] || fail 'Fabric core.yaml is missing.'
}
compose() { docker compose --env-file "$ENV_FILE" -f "$NETWORK_DIR/compose/docker-compose.$NODE_ID.yml" "$@"; }
node_org() { case "$1" in node1|node2) printf Org1MSP;; node3|node4) printf Org2MSP;; *) fail 'Unknown node.';; esac; }
use_peer() {
  local target="${1:-$NODE_ID}" target_org
  target_org="$(node_org "$target")"
  export CORE_PEER_ADDRESS="$target.labchain.internal:7051"
  export CORE_PEER_LOCALMSPID="$ORG_ID"
  export CORE_PEER_TLS_ENABLED=true
  local org_dir=org1
  [[ "$target_org" == Org2MSP ]] && org_dir=org2
  export CORE_PEER_TLS_ROOTCERT_FILE="$NETWORK_DIR/runtime/public/$org_dir-tls-ca.crt"
  if [[ -d "$NETWORK_DIR/runtime/admin/msp" ]]; then
    export CORE_PEER_MSPCONFIGPATH="$NETWORK_DIR/runtime/admin/msp"
  else
    export CORE_PEER_MSPCONFIGPATH="$NETWORK_DIR/runtime/peer/msp"
  fi
}
require_admin() {
  [[ -d "$NETWORK_DIR/runtime/admin/msp/keystore" ]] || fail 'Run this operation from the organization admin host: node1 or node3.'
  [[ "$(node_org "$1")" == "$ORG_ID" ]] || fail 'An organization admin may manage only its own peers.'
}
orderer_flags() {
  ORDERER_FLAGS=(-o "$ORDERER_HOST:$ORDERER_PORT" --tls --cafile "$NETWORK_DIR/runtime/public/orderer-tls-ca.crt")
}
endorser_flags() {
  ENDORSER_FLAGS=(--peerAddresses node1.labchain.internal:7051 --tlsRootCertFiles "$NETWORK_DIR/runtime/public/org1-tls-ca.crt" --peerAddresses node3.labchain.internal:7051 --tlsRootCertFiles "$NETWORK_DIR/runtime/public/org2-tls-ca.crt")
}
