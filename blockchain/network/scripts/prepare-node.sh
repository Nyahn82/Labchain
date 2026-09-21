#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
use_tools
need docker
need openssl
need curl
need ip
[[ "$(uname -s)" == Linux ]] || fail 'Linux is required for this host-network topology.'
python3 "$NETWORK_DIR/scripts/config.py" "$ENV_FILE" --host
[[ "$(cat "$NETWORK_DIR/runtime/node-id")" == "$NODE_ID" ]] || fail 'Wrong node identity bundle.'
[[ -f "$NETWORK_DIR/runtime/chaincode.env" ]] || fail 'Missing chaincode package identity.'
[[ -f "$NETWORK_DIR/runtime/public/labchain-channel.block" ]] || fail 'Missing channel block.'
actual_id="$(peer lifecycle chaincode calculatepackageid "$NETWORK_DIR/runtime/public/labchain-anchor.tgz")"
[[ "$actual_id" == "$(cat "$NETWORK_DIR/runtime/public/package-id.txt")" ]] || fail 'Chaincode package hash mismatch.'
openssl x509 -in "$NETWORK_DIR/runtime/peer/tls/server.crt" -checkhost "$PEER_HOSTNAME" -noout
openssl x509 -in "$NETWORK_DIR/runtime/peer/tls/server.crt" -checkend 86400 -noout
openssl verify -CAfile "$NETWORK_DIR/runtime/peer/tls/ca.crt" "$NETWORK_DIR/runtime/peer/tls/server.crt"
# A copied prepared runtime cannot silently become a second copy of a peer.
fingerprint="$(sha256sum /etc/machine-id | cut -d ' ' -f1)"
if [[ -e "$NETWORK_DIR/runtime/host-fingerprint" ]]; then
  [[ "$(cat "$NETWORK_DIR/runtime/host-fingerprint")" == "$fingerprint" ]] || fail 'This prepared identity belongs to another host; use the documented recovery procedure.'
else
  (umask 077; printf '%s\n' "$fingerprint" > "$NETWORK_DIR/runtime/host-fingerprint")
fi
compose --profile chaincode config --quiet
docker info >/dev/null
services=(peer)
[[ "$NODE_ID" == node4 ]] && services+=(orderer)
compose pull "${services[@]}"
compose --profile chaincode build anchor
printf 'Prepared %s; host fingerprint %s. No services started.\n' "$NODE_ID" "$fingerprint"
