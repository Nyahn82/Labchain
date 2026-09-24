#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
single_config
single_tools
for tool in cryptogen configtxgen openssl docker flock; do need "$tool"; done
[[ "$(cryptogen version 2>&1)" == *'Version: v2.5.16'* ]] || fail 'Use pinned cryptogen 2.5.16.'
[[ "$(configtxgen -version 2>&1)" == *'Version: v2.5.16'* ]] || fail 'Use pinned configtxgen 2.5.16.'
umask 077
mkdir -p "$NETWORK_DIR/runtime"
exec 9>"$NETWORK_DIR/runtime/.single-vps-prepare.lock"
flock -n 9 || fail 'Another single-VPS preparation is running.'
validate_single_compose
docker info >/dev/null
if [[ ! -d "$RUNTIME" ]]; then
  # Never generate new identities over existing ledger state, even if runtime was lost.
  existing_volumes="$(docker volume ls --format '{{.Name}}')"
  for volume in labchain-peer{1,2,3,4}-ledger labchain-orderer-ledger; do
    if grep -Fxq "$volume" <<< "$existing_volumes"; then
      fail "Existing $volume without runtime: restore identities and consistent state explicitly."
    fi
  done
fi
python3 "$NETWORK_DIR/scripts/single_vps.py" prepare
actual_id="$(peer lifecycle chaincode calculatepackageid "$RUNTIME/public/labchain-anchor.tgz")"
[[ "$actual_id" == "$(cat "$RUNTIME/public/package-id.txt")" ]] || fail 'Native package ID mismatch.'
printf '%s\n' 'Preparation complete. No image builds, services or firewall changes were performed.'
