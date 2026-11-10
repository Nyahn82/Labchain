#!/usr/bin/env bash
# Read-only Fabric inspection for this project's single-VPS network.
# Does not submit transactions or start/stop containers.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash peer-read.sh peer1|peer2|peer3|peer4 OPERATION [VALUE]
Operations:
  version, channels, info, definition, organizations
  anchor UUID, history UUID, exists UUID
  block NUMBER, transaction TX_ID
Run as the existing Fabric operator on the VPS.
USAGE
}
if [[ ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -ge 2 && $# -le 3 ]] || { usage >&2; exit 2; }
target=$1
operation=$2
value=${3:-}
case "$target" in peer1|peer2|peer3|peer4) ;; *) usage >&2; exit 2;; esac
case "$operation" in
  version|channels|info|definition|organizations)
    [[ $# == 2 ]] || { usage >&2; exit 2; } ;;
  anchor|history|exists)
    [[ $value =~ ^(TEST-)?[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]] \
      || { printf '%s\n' 'Use an existing event UUIDv4, optionally TEST-prefixed.' >&2; exit 2; } ;;
  block)
    [[ $value =~ ^(0|[1-9][0-9]{0,14})$ ]] \
      || { printf '%s\n' 'Use a nonnegative decimal block number.' >&2; exit 2; } ;;
  transaction)
    [[ $value =~ ^[0-9a-f]{64}$ ]] \
      || { printf '%s\n' 'Use a 64-character lowercase transaction ID.' >&2; exit 2; } ;;
  *) usage >&2; exit 2 ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
source "$repo_dir/blockchain/network/scripts/single-vps-common.sh"
single_ready
single_tools
single_peer "$target"
umask 077
work=''
cleanup() {
  if [[ -n "$work" ]]; then
    rm -f -- "$work/value.hex" "$work/value.pb" "$work/value.json"
    rmdir -- "$work"
  fi
}
trap cleanup EXIT
new_work() { work=$(mktemp -d /tmp/labchain-peer-read.XXXXXX); }
ctor() { python3 -c 'import json,sys; print(json.dumps({"Args":sys.argv[1:]}))' "$@"; }
decode_query() {
  local function=$1 proto=$2
  new_work
  peer chaincode query -C "$CHANNEL" -n qscc \
    -c "$(ctor "$function" "$CHANNEL" "$value")" --hex > "$work/value.hex"
  # --hex avoids the extra newline produced by this CLI's --raw output.
  python3 - "$work/value.hex" "$work/value.pb" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[2]).write_bytes(bytes.fromhex(Path(sys.argv[1]).read_text().strip()))
PY
  configtxlator proto_decode --input "$work/value.pb" \
    --type "$proto" --output "$work/value.json"
  cat "$work/value.json"
}

case "$operation" in
  version) peer version ;;
  channels) peer channel list ;;
  info) peer channel getinfo -c "$CHANNEL" ;;
  definition) peer lifecycle chaincode querycommitted -C "$CHANNEL" -n "$CHAINCODE" ;;
  anchor|history|exists)
    case "$operation" in
      anchor) function=ReadAnchor ;;
      history) function=GetAnchorHistory ;;
      exists) function=AnchorExists ;;
    esac
    peer chaincode query -C "$CHANNEL" -n "$CHAINCODE" \
      -c "$(ctor "$function" "$value")" | python3 -m json.tool ;;
  block) decode_query GetBlockByNumber common.Block ;;
  transaction) decode_query GetTransactionByID protos.ProcessedTransaction ;;
  organizations)
    # Current configuration is fetched from the orderer. The selected peer
    # determines which existing organization administrator identity is used.
    new_work
    single_orderer_flags
    peer channel fetch config "$work/value.pb" -c "$CHANNEL" "${ORDERER_FLAGS[@]}"
    configtxlator proto_decode --input "$work/value.pb" \
      --type common.Block --output "$work/value.json"
    python3 - "$work/value.json" <<'PY'
import json,sys
b=json.load(open(sys.argv[1]))
config=b['data']['data'][0]['payload']['data']['config']
groups=config['channel_group']['groups']
def organizations(group):
    return {name: org['values']['MSP']['value']['config']['name']
            for name,org in group['groups'].items()}
print(json.dumps({
    'configuration_block': b['header']['number'],
    'configuration_sequence': config['sequence'],
    'application_organizations': organizations(groups['Application']),
    'orderer_organizations': organizations(groups['Orderer']),
    'consensus_type': groups['Orderer']['values']['ConsensusType']['value']['type'],
    'application_endorsement_policy': groups['Application']['policies']['Endorsement']['policy'],
},indent=2))
PY
    ;;
esac
