#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
[[ $# == 1 || ($# == 2 && $2 == --channel) ]] || fail 'Usage: single-vps-status.sh orderer|peerN [--channel]'
target="$1"
if [[ "$target" != orderer ]]; then number="$(peer_number "$target")"; fi
single_ready
single_tools
need curl
single_compose ps "$target"
if [[ "$target" == orderer ]]; then
  curl --fail --silent --show-error --max-time 10 --cacert "$RUNTIME/public/orderer-tls-ca.crt" https://127.0.0.1:9444/healthz
  # mTLS participation query is valid even before channel creation.
  osnadmin channel list -o 127.0.0.1:7053 --ca-file "$RUNTIME/public/orderer-tls-ca.crt" \
    --client-cert "$RUNTIME/orderer-admin/tls/client.crt" --client-key "$RUNTIME/orderer-admin/tls/client.key" --no-status \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "channels" in d, d; print(json.dumps(d,indent=2))'
else
  port=$((9443+number)); [[ "$number" != 1 ]] || port=9443
  curl --fail --silent --show-error --max-time 10 --cacert "$RUNTIME/node$number/peer/tls/ca.crt" "https://127.0.0.1:$port/healthz"
  single_peer "$target"
  peer channel list
  if [[ "${2:-}" == --channel ]]; then peer channel getinfo -c "$CHANNEL"; fi
fi
