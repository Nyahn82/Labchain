"""Phase 4A protected orders, append-only payments and specimen workflow."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.laboratory import Paging
from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import LabOrder, LabPayment, RejectionReason, Specimen, UserAccount
from app.schemas import workflow as s
from app.schemas.identity import Identifier, Page
from app.services import workflow_service as service
from app.services.identity_service import get_record, list_records
from app.services.laboratory_service import save_record

router = APIRouter(route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
OrderReader = Annotated[UserAccount, Depends(require_permission('LAB_ORDER_READ'))]
SpecimenReader = Annotated[UserAccount, Depends(require_permission('SPECIMEN_READ'))]
ReasonManager = Annotated[UserAccount, Depends(require_permission('REJECTION_REASON_MANAGE'))]


@router.post('/lab-orders', response_model=s.OrderDetail, status_code=201, tags=['Laboratory Orders'])
def create_order(payload: s.OrderCreate, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('LAB_ORDER_CREATE'))]):
    return service.create_order(db, payload, actor.user_id, get_request_ip(request))


@router.get('/lab-orders', response_model=Page[s.OrderListItem], tags=['Laboratory Orders'])
def list_orders(db: Db, actor: OrderReader, paging: Paging,
                search: str | None = Query(None, max_length=200),
                patient_id: Identifier | None = None, physician_id: Identifier | None = None,
                priority: s.Priority | None = None, status: s.OrderStatus | None = None,
                date_from: date | None = None, date_to: date | None = None):
    return service.list_orders(db, **paging, search=search, patient_id=patient_id, physician_id=physician_id,
                               priority=priority, status=status, date_from=date_from, date_to=date_to)


@router.get('/lab-orders/{order_id}', response_model=s.OrderDetail, tags=['Laboratory Orders'])
def get_order(order_id: Identifier, db: Db, actor: OrderReader):
    return service.order_detail(db, order_id)


@router.post('/lab-orders/{order_id}/cancel', response_model=s.OrderResponse, tags=['Laboratory Orders'])
def cancel_order(order_id: Identifier, payload: s.CancelRequest, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('LAB_ORDER_CANCEL'))]):
    return service.cancel_order(db, order_id, payload, actor.user_id, get_request_ip(request))


@router.post('/lab-orders/{order_id}/payments', response_model=s.PaymentResponse, status_code=201, tags=['Payments'])
def record_payment(order_id: Identifier, payload: s.PaymentCreate, request: Request, db: Db,
                   actor: Annotated[UserAccount, Depends(require_permission('PAYMENT_RECORD'))]):
    return service.record_payment(db, order_id, payload, actor.user_id, get_request_ip(request))


@router.get('/lab-orders/{order_id}/payments', response_model=Page[s.PaymentResponse], tags=['Payments'])
def list_payments(order_id: Identifier, db: Db, paging: Paging,
                  actor: Annotated[UserAccount, Depends(require_permission('PAYMENT_READ'))]):
    get_record(db, LabOrder, order_id)
    return list_records(db, LabPayment, **paging, filters={'order_id': order_id})


@router.post('/lab-orders/{order_id}/specimens', response_model=s.SpecimenResponse, status_code=201, tags=['Specimens'])
def register_specimen(order_id: Identifier, payload: s.SpecimenCreate, request: Request, db: Db,
                      actor: Annotated[UserAccount, Depends(require_permission('SPECIMEN_REGISTER'))]):
    return service.register_specimen(db, order_id, payload, actor.user_id, get_request_ip(request))


@router.get('/lab-orders/{order_id}/specimens', response_model=Page[s.SpecimenResponse], tags=['Specimens'])
def list_specimens(order_id: Identifier, db: Db, actor: SpecimenReader, paging: Paging):
    get_record(db, LabOrder, order_id)
    result = list_records(db, Specimen, **paging, filters={'order_id': order_id})
    result['items'] = service.specimen_views(db, result['items'])
    return result


@router.get('/specimens/{specimen_id}', response_model=s.SpecimenResponse, tags=['Specimens'])
def get_specimen(specimen_id: Identifier, db: Db, actor: SpecimenReader):
    return service.specimen_detail(db, specimen_id)


@router.post('/specimens/{specimen_id}/collect', response_model=s.SpecimenResponse, tags=['Specimens'])
def collect_specimen(specimen_id: Identifier, request: Request, db: Db,
                     actor: Annotated[UserAccount, Depends(require_permission('SPECIMEN_COLLECT'))]):
    return service.transition_specimen(db, specimen_id, 'COLLECT', actor.user_id, get_request_ip(request))


@router.post('/specimens/{specimen_id}/receive', response_model=s.SpecimenResponse, tags=['Specimens'])
def receive_specimen(specimen_id: Identifier, request: Request, db: Db,
                     actor: Annotated[UserAccount, Depends(require_permission('SPECIMEN_RECEIVE'))]):
    return service.transition_specimen(db, specimen_id, 'RECEIVE', actor.user_id, get_request_ip(request))


@router.post('/specimens/{specimen_id}/reject', response_model=s.SpecimenResponse, tags=['Specimens'])
def reject_specimen(specimen_id: Identifier, payload: s.RejectRequest, request: Request, db: Db,
                    actor: Annotated[UserAccount, Depends(require_permission('SPECIMEN_REJECT'))]):
    return service.transition_specimen(db, specimen_id, 'REJECT', actor.user_id, get_request_ip(request), payload)


@router.post('/lab/rejection-reasons', response_model=s.ReasonResponse, status_code=201, tags=['Specimens'])
def create_reason(payload: s.ReasonCreate, request: Request, db: Db, actor: ReasonManager):
    return save_record(db, RejectionReason, payload, s.ReasonResponse, actor.user_id,
                       get_request_ip(request), 'REJECTION_REASON_CREATE')


@router.get('/lab/rejection-reasons', response_model=Page[s.ReasonResponse], tags=['Specimens'])
def list_reasons(db: Db, actor: ReasonManager, paging: Paging,
                 search: str | None = Query(None, max_length=200), is_active: bool | None = None):
    return list_records(db, RejectionReason, **paging, search=search,
                        search_fields=('reason_code', 'reason_name'), filters={'is_active': is_active})


@router.patch('/lab/rejection-reasons/{rejection_reason_id}', response_model=s.ReasonResponse, tags=['Specimens'])
def patch_reason(rejection_reason_id: Identifier, payload: s.ReasonPatch, request: Request, db: Db, actor: ReasonManager):
    return save_record(db, RejectionReason, payload, s.ReasonResponse, actor.user_id,
                       get_request_ip(request), 'REJECTION_REASON_UPDATE', record_id=rejection_reason_id)
