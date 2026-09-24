#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
[[ $# == 1 ]] || fail 'Usage: join-channel-single-vps.sh peerN'
peer_number "$1" >/dev/null
single_ready
single_tools
single_peer "$1"
channels="$(peer channel list)"
if ! grep -Fxq "$CHANNEL" <<< "$channels"; then
  peer channel join -b "$RUNTIME/public/labchain-channel.block"
fi
peer channel getinfo -c "$CHANNEL"
