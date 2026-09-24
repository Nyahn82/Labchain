#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
[[ $# == 0 ]] || fail 'Usage: stop-single-vps.sh'
# Stopping must remain possible if a certificate expired or the runtime is damaged.
single_config
single_compose --profile '*' stop
