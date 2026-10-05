#!/usr/bin/env bash
set -euo pipefail
NETWORK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Python verifies the fixed cryptogen binary against the reviewed 2.5.16 archive.
# No generate command, runtime publication, /etc install, or service operation.
exec python3 "$NETWORK_DIR/scripts/provision_monitor_client.py" "$@"
