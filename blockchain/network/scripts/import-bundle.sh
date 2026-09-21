#!/usr/bin/env bash
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
load_config
[[ $# == 1 ]] || fail 'Usage: import-bundle.sh /secure/path/nodeN.tar.gz'
[[ ! -e "$NETWORK_DIR/runtime" ]] || fail 'Existing runtime retained; import never overwrites identities.'
python3 - "$1" "$NODE_ID" "$NETWORK_DIR" <<'PY'
import hashlib,sys,tarfile
from pathlib import Path
bundle=Path(sys.argv[1]).resolve()
expected=bundle.with_suffix(bundle.suffix+'.sha256').read_text().split()[0]
if hashlib.sha256(bundle.read_bytes()).hexdigest()!=expected:
    sys.exit('Bundle checksum mismatch.')
with tarfile.open(bundle) as tar:
    for member in tar.getmembers():
        parts=Path(member.name).parts
        if not parts or parts[0]!='runtime' or '..' in parts or not (member.isfile() or member.isdir()):
            sys.exit('Unsafe bundle member.')
    if tar.extractfile('runtime/node-id').read().decode().strip()!=sys.argv[2]:
        sys.exit('Bundle belongs to a different node.')
    tar.extractall(sys.argv[3],filter='data')
print('Imported only the selected node identity bundle.')
PY
