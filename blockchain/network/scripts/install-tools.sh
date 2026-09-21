#!/usr/bin/env bash
set -euo pipefail
# Native Fabric tools; no Docker daemon, Python venv, or system path changes.
NETWORK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'This pinned tool bundle requires Linux x86_64.' >&2; exit 1; }
if [[ -x "$NETWORK_DIR/tools/bin/peer" ]]; then
  "$NETWORK_DIR/tools/bin/peer" version | grep -F 'Version: v2.5.16' >/dev/null
  test -f "$NETWORK_DIR/tools/config/core.yaml"
  echo 'Pinned Fabric tools already installed.'
  exit 0
fi
mkdir -p "$NETWORK_DIR/tools"
archive="$NETWORK_DIR/tools/fabric-2.5.16.tar.gz"
curl --fail --show-error --location --proto '=https' --tlsv1.2 \
  https://github.com/hyperledger/fabric/releases/download/v2.5.16/hyperledger-fabric-linux-amd64-2.5.16.tar.gz -o "$archive"
printf '%s  %s\n' 18c91e7f2f11b601e6622cc70454d568af897707ee9adf111e9fa91a233881bf "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$NETWORK_DIR/tools" bin config
"$NETWORK_DIR/tools/bin/peer" version
