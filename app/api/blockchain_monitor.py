"""Administrative read-only Fabric explorer, separate from Phase 8 status."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, require_permission
from app.schemas import blockchain_monitor as s
from app.schemas.blockchain import BlockchainStatus
from app.services import blockchain_monitor_service as service
from app.services.blockchain_status_service import global_status

router = APIRouter(prefix='/admin/blockchain', tags=['Blockchain Monitor'], route_class=PrivateRoute,
    dependencies=[Depends(require_permission('BLOCKCHAIN_EXPLORER_VIEW'))])
Db = Annotated[Session, Depends(get_db)]
BlockNumber = Annotated[int, Query(ge=0, le=9007199254740991)]


@router.get('/overview', response_model=s.Overview)
def overview():
    return service.overview()


@router.get('/queue', response_model=BlockchainStatus)
def queue(db: Db):
    return global_status(db)


@router.get('/blocks', response_model=s.Blocks)
def blocks(before: BlockNumber | None = None, limit: Annotated[int, Query(ge=1, le=10)] = 10):
    return service.ledger({'action': 'blocks', 'before': before, 'limit': limit}, s.Blocks)


@router.get('/blocks/{number}', response_model=s.Block)
def block(number: s.Number):
    return service.ledger({'action': 'block', 'number': number}, s.Block)


@router.get('/transactions/{transaction_id}', response_model=s.TransactionDetail)
def transaction(transaction_id: s.Hash):
    return service.ledger({'action': 'transaction', 'transaction_id': transaction_id}, s.TransactionDetail)


@router.get('/anchors', response_model=s.Anchors)
def anchors(db: Db, before: Annotated[int | None, Query(ge=1)] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 20,
            status: Literal['PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD'] | None = None,
            event_type: Literal['REPORT_RELEASED', 'REPORT_REVOKED', 'REPORT_SUPERSEDED'] | None = None,
            block_number: BlockNumber | None = None, transaction_id: s.Hash | None = None,
            entity_reference: UUID | None = None):
    return service.anchors(db, before=before, limit=limit, status=status, event_type=event_type,
        block_number=block_number, transaction_id=transaction_id,
        entity_reference=str(entity_reference) if entity_reference else None)


@router.get('/reports/{report_id}/integrity', response_model=s.Integrity,
    dependencies=[Depends(require_permission('BLOCKCHAIN_INTEGRITY_VERIFY'))])
def integrity(report_id: Annotated[int, Path(ge=1)], db: Db):
    return service.integrity(db, report_id)
