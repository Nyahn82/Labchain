"""Permissioned outbox status; no live worker or Fabric probes."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, require_permission, require_role
from app.models import UserAccount
from app.schemas.blockchain import BlockchainStatus
from app.services.blockchain_status_service import global_status

router = APIRouter(prefix='/blockchain', tags=['Blockchain Status'], route_class=PrivateRoute,
    dependencies=[Depends(require_role('SYSTEM_ADMIN', 'LAB_STAFF', 'LAB_SUPERVISOR', 'DOCTOR'))])


@router.get('/status', response_model=BlockchainStatus,
    description='Permissioned application outbox status from MySQL. Does not check Fabric or affect readiness.')
def status(db: Annotated[Session, Depends(get_db)],
           actor: Annotated[UserAccount, Depends(require_permission('BLOCKCHAIN_STATUS_VIEW'))]):
    return global_status(db)
