#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
single_ready
single_tools
flags=(-o 127.0.0.1:7053 --ca-file "$RUNTIME/public/orderer-tls-ca.crt"
  --client-cert "$RUNTIME/orderer-admin/tls/client.crt" --client-key "$RUNTIME/orderer-admin/tls/client.key" --no-status)
listing="$(osnadmin channel list "${flags[@]}")"
exists="$(python3 -c 'import json,sys; print(any(c["name"]=="labchain-channel" for c in (json.load(sys.stdin)["channels"] or [])))' <<< "$listing")"
if [[ "$exists" == False ]]; then
  result="$(osnadmin channel join --channelID "$CHANNEL" --config-block "$RUNTIME/public/labchain-channel.block" "${flags[@]}")"
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["name"]=="labchain-channel" and d["status"] in ("active","onboarding"), d' <<< "$result"
fi
osnadmin channel list --channelID "$CHANNEL" "${flags[@]}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["name"]=="labchain-channel" and d["status"]=="active", d; print(json.dumps(d,indent=2))'
