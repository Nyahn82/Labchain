#!/usr/bin/env bash
# Constants/arrays are consumed by the single-VPS entry points.
# shellcheck disable=SC2034
set -euo pipefail
NETWORK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$NETWORK_DIR/runtime/single-vps"
CHANNEL=labchain-channel
CHAINCODE=labchain-anchor
CC_VERSION=1.0.0
CC_SEQUENCE=1
ENDORSEMENT="AND('Org1MSP.peer','Org2MSP.peer')"
export FABRIC_LOGGING_SPEC=warn
fail() { printf '%s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || fail "Required command missing: $1"; }
single_config() {
  ENV_FILE="${LABCHAIN_SINGLE_VPS_ENV_FILE:-$NETWORK_DIR/.env.single-vps}"
  python3 "$NETWORK_DIR/scripts/single_vps.py" config "$ENV_FILE"
  # Export only the validated shared settings; never source operator input.
  export FABRIC_VERSION=2.5.16 DEPLOYMENT_MODE=single-vps
  FABRIC_RUN_UID="$(id -u)"; FABRIC_RUN_GID="$(id -g)"
  export FABRIC_RUN_UID FABRIC_RUN_GID
}
single_compose() {
  docker compose --project-name labchain-single-vps --env-file "$ENV_FILE" \
    -f "$NETWORK_DIR/compose/docker-compose.single-vps.yml" "$@"
}
validate_single_compose() {
  single_compose --profile '*' config --format json | python3 "$NETWORK_DIR/scripts/single_vps.py" compose
}
single_ready() {
  single_config
  python3 "$NETWORK_DIR/scripts/single_vps.py" runtime
  validate_single_compose
}
single_tools() {
  local tools_dir="${LABCHAIN_FABRIC_TOOLS:-$NETWORK_DIR/tools}"
  export PATH="$tools_dir/bin:$PATH" FABRIC_CFG_PATH="$tools_dir/config"
  need peer
  [[ "$(peer version)" == *'Version: v2.5.16'* ]] || fail 'Use pinned Fabric 2.5.16 native tools.'
  [[ -f "$FABRIC_CFG_PATH/core.yaml" ]] || fail 'Fabric core.yaml is missing.'
}
peer_number() {
  case "${1:-}" in peer1|peer2|peer3|peer4) printf '%s' "${1#peer}";; *) fail 'Select peer1, peer2, peer3 or peer4.';; esac
}
single_peer() {
  local number org
  number="$(peer_number "$1")"
  org=1; ((number <= 2)) || org=2
  export CORE_PEER_ADDRESS="127.0.0.1:$((7051+1000*(number-1)))"
  export CORE_PEER_LOCALMSPID="Org${org}MSP" CORE_PEER_TLS_ENABLED=true
  export CORE_PEER_TLS_SERVERHOSTOVERRIDE="$1"
  export CORE_PEER_TLS_ROOTCERT_FILE="$RUNTIME/public/org${org}-tls-ca.crt"
  export CORE_PEER_MSPCONFIGPATH="$RUNTIME/admin/org${org}/msp"
  [[ -d "$CORE_PEER_MSPCONFIGPATH/keystore" ]] || fail 'Missing organization administrator identity.'
}
single_orderer_flags() {
  ORDERER_FLAGS=(-o 127.0.0.1:7050 --ordererTLSHostnameOverride orderer --tls --cafile "$RUNTIME/public/orderer-tls-ca.crt")
}
single_endorser_flags() {
  # All peer certificates also include 127.0.0.1; container endpoints remain DNS names.
  unset CORE_PEER_TLS_SERVERHOSTOVERRIDE
  ENDORSER_FLAGS=(--peerAddresses 127.0.0.1:7051 --tlsRootCertFiles "$RUNTIME/public/org1-tls-ca.crt"
    --peerAddresses 127.0.0.1:9051 --tlsRootCertFiles "$RUNTIME/public/org2-tls-ca.crt")
}
