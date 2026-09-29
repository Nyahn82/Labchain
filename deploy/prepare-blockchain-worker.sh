#!/bin/bash -p
# Preparation only: never starts/enables a worker or changes live Fabric/MySQL.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if (( EUID != 0 )); then
    echo 'Run preparation as root after reviewing the script. No changes made.' >&2
    exit 1
fi
if (( $# != 0 )); then
    echo 'This preparation script accepts no arguments.' >&2
    exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# Do not inherit Python hooks, a user's PATH, or secret environment variables.
exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 \
    /usr/bin/python3 -I -B "$SCRIPT_DIR/prepare_blockchain_worker.py"
