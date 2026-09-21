#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
use_tools
target="${1:-$NODE_ID}"
require_admin "$target"
use_peer "$target"
channels="$(peer channel list)"
if ! grep -Fxq "$CHANNEL" <<< "$channels"; then
  peer channel join -b "$NETWORK_DIR/runtime/public/labchain-channel.block"
fi
peer channel getinfo -c "$CHANNEL"
