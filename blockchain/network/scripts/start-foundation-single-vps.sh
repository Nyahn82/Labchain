#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
[[ $# == 0 ]] || fail 'Usage: start-foundation-single-vps.sh'
single_ready
single_compose up -d --no-deps --no-build orderer peer1
single_compose ps orderer peer1
