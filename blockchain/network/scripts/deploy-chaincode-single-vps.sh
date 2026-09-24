#!/usr/bin/env bash
set -euo pipefail
# Explicit CCAAS build/start and Fabric lifecycle; no peer/orderer is started here.
# shellcheck source-path=SCRIPTDIR
# shellcheck source=single-vps-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/single-vps-common.sh"
single_ready
single_tools
action="${1:-query}"
target="${2:-peer1}"
peer_number "$target" >/dev/null
single_peer "$target"
single_orderer_flags
single_endorser_flags
package="$RUNTIME/public/labchain-anchor.tgz"
package_id="$(peer lifecycle chaincode calculatepackageid "$package")"
[[ "$package_id" == "$(cat "$RUNTIME/public/package-id.txt")" ]] || fail 'Package ID does not match the reviewed bootstrap package.'
definition=(--channelID "$CHANNEL" --name "$CHAINCODE" --version "$CC_VERSION" --sequence "$CC_SEQUENCE" --signature-policy "$ENDORSEMENT")
case "$action" in
  build)
    single_compose --profile chaincode build anchor1
    ;;
  start)
    number="$(peer_number "$target")"
    single_compose up -d --no-deps --no-build "anchor$number"
    ;;

  package)
    printf 'Package: %s\nPackage ID: %s\n' "$package" "$package_id"
    ;;
  install)
    installed="$(peer lifecycle chaincode queryinstalled --output json)"
    exists="$(python3 -c 'import json,sys; print(any(x["package_id"]==sys.argv[1] for x in json.load(sys.stdin).get("installed_chaincodes",[])))' "$package_id" <<< "$installed")"
    if [[ "$exists" == False ]]; then peer lifecycle chaincode install "$package"; fi
    peer lifecycle chaincode queryinstalled --output json
    ;;
  approve)
    peer lifecycle chaincode approveformyorg "${definition[@]}" --package-id "$package_id" "${ORDERER_FLAGS[@]}" --waitForEvent --waitForEventTimeout 60s
    ;;
  commit)
    committed="$(peer lifecycle chaincode querycommitted --channelID "$CHANNEL" --output json)"
    exists="$(python3 -c 'import json,sys; print(any(x["name"]=="labchain-anchor" for x in json.load(sys.stdin).get("chaincode_definitions",[])))' <<< "$committed")"
    if [[ "$exists" == False ]]; then
      readiness="$(peer lifecycle chaincode checkcommitreadiness "${definition[@]}" --output json)"
      python3 -c 'import json,sys; a=json.load(sys.stdin)["approvals"]; assert a.get("Org1MSP") and a.get("Org2MSP"), "Both organizations must approve first"' <<< "$readiness"
      peer lifecycle chaincode commit "${definition[@]}" "${ORDERER_FLAGS[@]}" "${ENDORSER_FLAGS[@]}" --waitForEvent --waitForEventTimeout 60s
    fi
    peer lifecycle chaincode querycommitted --channelID "$CHANNEL" --name "$CHAINCODE" --output json | python3 "$NETWORK_DIR/scripts/check-definition.py"
    echo 'Committed definition requires both organizations.'
    ;;
  query)
    peer lifecycle chaincode querycommitted --channelID "$CHANNEL" --name "$CHAINCODE" --output json
    ;;
  *) fail 'Usage: deploy-chaincode-single-vps.sh build|start|package|install|approve|commit|query [peerN]';;
esac
