"""Idempotent, explicit prototype peer registry bootstrap; no network operations."""
import sys
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.database import SessionLocal
from app.models import BlockchainNode
from app.models.blockchain import OutboxIntegrityError

NODES = (
    ('node1', 7051, 'Org1MSP peer1'), ('node2', 8051, 'Org1MSP peer2'),
    ('node3', 9051, 'Org2MSP peer3'), ('node4', 10051, 'Org2MSP peer4'),
)


def ensure_blockchain_nodes(db):
    created = []
    for code, port, role in NODES:
        rows = list(db.scalars(select(BlockchainNode).where(
            (BlockchainNode.node_code == code) | (BlockchainNode.port == port)).with_for_update()))
        if rows:
            if len(rows) != 1 or (rows[0].node_code, rows[0].port, rows[0].node_role, rows[0].is_active) != (code, port, role, True):
                raise OutboxIntegrityError('Blockchain node registry conflicts with reviewed metadata; manual review required.')
        else:
            db.add(BlockchainNode(node_code=code, port=port, node_role=role, is_active=True))
            db.flush()
            created.append(code)
    return created


def main():
    try:
        with SessionLocal.begin() as db:
            created = ensure_blockchain_nodes(db)
    except OutboxIntegrityError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except SQLAlchemyError:
        print('Blockchain node bootstrap failed; check migrations and registry conflicts, then retry.', file=sys.stderr)
        raise SystemExit(1) from None
    print(f'Blockchain nodes ready; created {len(created)} node(s).')


if __name__ == '__main__':
    main()
