"""Explicit grant bootstrap. Default/preflight is SELECT-only; never creates roles."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from app.database import SessionLocal
from app.services.role_permission_matrix import MatrixError, execute_matrix, preflight


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--receipt-file', type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        plan = preflight(SessionLocal)
        print(json.dumps(plan, indent=2, sort_keys=True))
        if not plan['safe_to_execute']:
            raise MatrixError('UNSAFE: resolve preflight errors separately; no writes performed.')
        if not args.execute:
            print('PREFLIGHT_ONLY')
            return 0
        operation = str(uuid4())
        path = args.receipt_file or Path(__file__).resolve().parents[2] / '.phase9-runs' / f'rbac-{operation}.json'
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as receipt:
            state = {'operation_id': operation, 'timestamp': datetime.now(timezone.utc).isoformat(),
                     'matrix_version': plan['matrix_version'], 'state': 'PENDING', 'plan': plan, 'added': []}

            def record():
                receipt.seek(0)
                json.dump(state, receipt, indent=2, sort_keys=True)
                receipt.truncate()
                receipt.flush()
                os.fsync(receipt.fileno())

            def prepared(rows):
                state.update(state='PREPARED', added=rows)
                record()

            record()
            # Persist the new directory entry before any database write.
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            added = execute_matrix(SessionLocal, plan, record_prepared=prepared)
            state['state'] = 'COMMITTED'
            record()
        print('APPLIED' if added else 'NO_CHANGES')
        print(f'Receipt: {path}')
        return 0
    except MatrixError as exc:
        print(str(exc))
    except FileExistsError:
        print('Receipt already exists; stop and reconcile. Nothing retried.')
    except Exception:
        print('Execution failed; private details withheld. Reconcile any receipt before retrying.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
