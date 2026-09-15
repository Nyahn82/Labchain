"""Staff HTTP API using existing session, CSRF and permission dependencies."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import Staff, UserAccount
from app.schemas.identity import StaffCreate, StaffPatch, StaffResponse, Page, Identifier
from app.services.identity_service import create_record, get_record, list_records, patch_record

router = APIRouter(prefix='/staff', tags=['Staff'], route_class=PrivateRoute)


@router.post('', response_model=StaffResponse, status_code=201)
def create(payload: StaffCreate, request: Request,
           actor: UserAccount = Depends(require_permission('STAFF_CREATE')),
           db: Session = Depends(get_db)):
    return create_record(db, Staff, payload, StaffResponse, actor.user_id,
                         get_request_ip(request), 'STAFF_CREATE')


@router.get('', response_model=Page[StaffResponse])
def list_all(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    staff_code: str | None = None,
    is_active: bool | None = None,
    actor: UserAccount = Depends(require_permission('STAFF_READ')),
    db: Session = Depends(get_db),
):
    return list_records(db, Staff, page=page, page_size=page_size, search=search,
                        search_fields=('staff_code', 'first_name', 'middle_name', 'last_name'), filters={'staff_code': staff_code, 'is_active': is_active})


@router.get('/{staff_id}', response_model=StaffResponse)
def detail(staff_id: Identifier,
           actor: UserAccount = Depends(require_permission('STAFF_READ')),
           db: Session = Depends(get_db)):
    return get_record(db, Staff, staff_id)


@router.patch('/{staff_id}', response_model=StaffResponse)
def patch(staff_id: Identifier, payload: StaffPatch, request: Request,
          actor: UserAccount = Depends(require_permission('STAFF_UPDATE')),
          db: Session = Depends(get_db)):
    return patch_record(db, Staff, staff_id, payload, StaffResponse,
                        actor.user_id, get_request_ip(request), 'STAFF_UPDATE')
