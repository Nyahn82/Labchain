#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
[[ $# == 1 ]] || fail 'Usage: start-peer-single-vps.sh peer1|peer2|peer3|peer4'
peer_number "$1" >/dev/null
single_ready
single_compose up -d --no-deps --no-build "$1"
single_compose ps "$1"
