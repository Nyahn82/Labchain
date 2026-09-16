"""Phase 4B result entry, review and verification; no reporting endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.laboratory import Paging
from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import UserAccount
from app.schemas import results as s
from app.schemas.identity import Identifier, Page
from app.services import result_service as service

router = APIRouter(tags=['Laboratory Results'], route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
Reader = Annotated[UserAccount, Depends(require_permission('LAB_RESULT_READ'))]
Encoder = Annotated[UserAccount, Depends(require_permission('LAB_RESULT_ENTER'))]


@router.post('/lab-order-items/{order_item_id}/result', response_model=s.ResultResponse, status_code=201)
def create_result(order_item_id: Identifier, payload: s.ResultCreate, request: Request, db: Db, actor: Encoder):
    return service.create_result(db, order_item_id, payload, actor.user_id, get_request_ip(request))


@router.get('/lab-orders/{order_id}/results', response_model=Page[s.ResultResponse])
def list_results(order_id: Identifier, db: Db, actor: Reader, paging: Paging):
    return service.list_results(db, order_id, **paging)


@router.get('/results/{result_item_id}', response_model=s.ResultResponse)
def get_result(result_item_id: Identifier, db: Db, actor: Reader):
    return service.result_detail(db, result_item_id)


@router.patch('/results/{result_item_id}', response_model=s.ResultResponse)
def update_result(result_item_id: Identifier, payload: s.ResultPatch, request: Request, db: Db, actor: Encoder):
    return service.update_result(db, result_item_id, payload, actor.user_id, get_request_ip(request))


@router.post('/results/{result_item_id}/review', response_model=s.ResultResponse)
def review_result(result_item_id: Identifier, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('LAB_RESULT_REVIEW'))]):
    return service.transition_result(db, result_item_id, 'REVIEW', actor.user_id, get_request_ip(request))


@router.post('/results/{result_item_id}/verify', response_model=s.ResultResponse)
def verify_result(result_item_id: Identifier, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('LAB_RESULT_VERIFY'))]):
    return service.transition_result(db, result_item_id, 'VERIFY', actor.user_id, get_request_ip(request))
