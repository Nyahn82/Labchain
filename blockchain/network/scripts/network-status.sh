#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
use_tools
target="${1:-$NODE_ID}"
if [[ "$target" == "$NODE_ID" ]]; then
  compose --profile chaincode ps
  curl --fail --silent --show-error --max-time 10 --cacert "$NETWORK_DIR/runtime/peer/tls/ca.crt" https://127.0.0.1:9443/healthz
fi
use_peer "$target"
peer channel list
printf 'Node: %s\nPeer: %s\nChannel: %s\n' "$target" "$CORE_PEER_ADDRESS" "$CHANNEL"
peer channel getinfo -c "$CHANNEL"
