#!/usr/bin/env bash
set -euo pipefail
# One explicitly invoked synthetic transaction; never reads application data.
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
use_tools
require_admin "$NODE_ID"
use_peer "$NODE_ID"
orderer_flags
endorser_flags
anchor_id="TEST-$(python3 -c 'import uuid; print(uuid.uuid4())')"
payload="$(python3 - "$anchor_id" "$NODE_ID" <<'PY'
import hashlib,json,sys,uuid
print(json.dumps({'Args':['CreateAnchor',sys.argv[1],'REPORT_RELEASED',str(uuid.uuid4()),hashlib.sha256(b'RHU LabChain Phase 8A synthetic smoke test').hexdigest(),'',sys.argv[2]]}))
PY
)"
peer chaincode invoke -C "$CHANNEL" -n "$CHAINCODE" -c "$payload" "${ORDERER_FLAGS[@]}" "${ENDORSER_FLAGS[@]}" --waitForEvent --waitForEventTimeout 60s
"$NETWORK_DIR/scripts/verify-network.sh" "$anchor_id"
printf 'Synthetic anchor committed and read from four peers: %s\n' "$anchor_id"
