#!/usr/bin/env bash
set -euo pipefail
# One explicitly invoked synthetic transaction; never reads application data.
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
single_ready
single_tools

single_peer peer1
single_orderer_flags
single_endorser_flags
anchor_id="TEST-$(python3 -c 'import uuid; print(uuid.uuid4())')"
payload="$(python3 - "$anchor_id" node1 <<'PY'
import hashlib,json,sys,uuid
print(json.dumps({'Args':['CreateAnchor',sys.argv[1],'REPORT_RELEASED',str(uuid.uuid4()),hashlib.sha256(b'RHU LabChain Phase 8A synthetic smoke test').hexdigest(),'',sys.argv[2]]}))
PY
)"
peer chaincode invoke -C "$CHANNEL" -n "$CHAINCODE" -c "$payload" "${ORDERER_FLAGS[@]}" "${ENDORSER_FLAGS[@]}" --waitForEvent --waitForEventTimeout 60s
"$NETWORK_DIR/scripts/verify-network-single-vps.sh" "$anchor_id"
printf 'Synthetic anchor committed and read from four peers: %s\n' "$anchor_id"
