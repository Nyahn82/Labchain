#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
use_tools
[[ "$NODE_ID" == node4 ]] || fail 'Run channel participation administration locally on node4.'
admin_tls="$NETWORK_DIR/runtime/orderer-admin/tls"
flags=(-o 127.0.0.1:7053 --ca-file "$NETWORK_DIR/runtime/public/orderer-tls-ca.crt" --client-cert "$admin_tls/client.crt" --client-key "$admin_tls/client.key" --no-status)
listing="$(osnadmin channel list "${flags[@]}")"
exists="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(any(c["name"]=="labchain-channel" for c in d["channels"]))' <<< "$listing")"
if [[ "$exists" == False ]]; then
  result="$(osnadmin channel join --channelID "$CHANNEL" --config-block "$NETWORK_DIR/runtime/public/labchain-channel.block" "${flags[@]}")"
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["name"]=="labchain-channel" and d["status"] in ("active","onboarding"), "Channel join failed"' <<< "$result"
fi
osnadmin channel list --channelID "$CHANNEL" "${flags[@]}"
