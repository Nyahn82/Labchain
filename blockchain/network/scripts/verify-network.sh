#!/usr/bin/env bash
set -euo pipefail
# Run from node1/node3. All four peers must converge; no one-host fallback.
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
use_tools
require_admin "$NODE_ID"
anchor_id="${1:-}"
if [[ -n "$anchor_id" ]]; then
  [[ "$anchor_id" =~ ^TEST-[0-9a-f-]{36}$ ]] || fail 'Validation accepts only synthetic TEST UUID anchors.'
fi
output_dir="$NETWORK_DIR/artifacts"
mkdir -p "$output_dir"
work="$(mktemp -d "$output_dir/validation.XXXXXX")"
for attempt in {1..12}; do
  success=true
  for number in 1 2 3 4; do
    target="node$number"
    use_peer "$target"
    if ! peer channel getinfo -c "$CHANNEL" > "$work/$target.info"; then success=false; continue; fi
    if [[ -n "$anchor_id" ]]; then
      payload="$(python3 -c 'import json,sys; print(json.dumps({"Args":["ReadAnchor",sys.argv[1]]}))' "$anchor_id")"
      if ! peer chaincode query -C "$CHANNEL" -n "$CHAINCODE" -c "$payload" > "$work/$target.record"; then success=false; fi
    fi
  done
  if [[ "$success" == true ]] && python3 "$NETWORK_DIR/scripts/verify-observations.py" "$work" "$anchor_id"; then
    printf 'All four peers converged. Synthetic validation evidence: %s\n' "$work"
    exit 0
  fi
  [[ "$attempt" == 12 ]] || sleep 5
done
fail 'Cross-peer convergence failed within the bounded retry period. Evidence was retained.'
