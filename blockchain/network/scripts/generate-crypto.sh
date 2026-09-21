#!/usr/bin/env bash
set -euo pipefail
# Explicit academic/prototype bootstrap. Do not run on production application hosts.
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
use_tools
need cryptogen
need configtxgen
need openssl
umask 077
generated="${LABCHAIN_BOOTSTRAP_DIR:-$NETWORK_DIR/generated}"
if [[ -f "$generated/COMPLETE" ]]; then
  echo 'Existing bootstrap retained. Never regenerate identities for an existing ledger.'
  exit 0
fi
[[ ! -e "$generated" ]] || fail 'Incomplete bootstrap directory exists; preserve it and investigate. No keys were replaced.'
mkdir -p "$generated"
cp "$NETWORK_DIR/config/configtx.yaml" "$generated/configtx.yaml"
cryptogen generate --config="$NETWORK_DIR/config/crypto-config.yaml" --output="$generated/crypto-config"
FABRIC_CFG_PATH="$generated" configtxgen -profile LabchainChannel -channelID "$CHANNEL" -outputBlock "$generated/labchain-channel.block"
python3 "$NETWORK_DIR/scripts/bundle-identities.py" "$generated"
printf '%s\n' 'Prototype bootstrap complete; private CAs stay offline.' > "$generated/COMPLETE"
echo 'Created separate node bundles. Transfer only the bundle for the intended VPS over authenticated SSH.'
