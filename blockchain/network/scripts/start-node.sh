#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
[[ "$FIREWALL_READY" == yes ]] || fail 'Apply and verify the documented member-only firewall rules before starting Fabric.'
python3 "$NETWORK_DIR/scripts/config.py" "$ENV_FILE" --host
[[ "$(cat "$NETWORK_DIR/runtime/node-id")" == "$NODE_ID" ]] || fail 'Wrong node identity bundle.'
[[ "$(cat "$NETWORK_DIR/runtime/host-fingerprint")" == "$(sha256sum /etc/machine-id | cut -d ' ' -f1)" ]] || fail 'Run prepare-node.sh on the intended host first.'
compose --profile chaincode up -d --no-build
compose --profile chaincode ps
