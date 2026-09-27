#!/usr/bin/env bash
set -euo pipefail
NETWORK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Linux x86_64 is required.' >&2; exit 1; }
# Fixed binary path: never select cryptogen from PATH or an environment override.
CRYPTOGEN="$NETWORK_DIR/tools/bin/cryptogen"
[[ -x "$CRYPTOGEN" && "$("$CRYPTOGEN" version 2>&1)" == *'Version: v2.5.16'* ]] || { echo 'Pinned Fabric cryptogen 2.5.16 is required.' >&2; exit 1; }
exec python3 "$NETWORK_DIR/scripts/provision_app_client.py" "$@"
