"""Physicians HTTP API using existing session, CSRF and permission dependencies."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import RequestingPhysician, UserAccount
from app.schemas.identity import PhysicianCreate, PhysicianPatch, PhysicianResponse, Page, Identifier
from app.services.identity_service import create_record, get_record, list_records, patch_record

router = APIRouter(prefix='/physicians', tags=['Physicians'], route_class=PrivateRoute)


@router.post('', response_model=PhysicianResponse, status_code=201)
def create(payload: PhysicianCreate, request: Request,
           actor: UserAccount = Depends(require_permission('PHYSICIAN_CREATE')),
           db: Session = Depends(get_db)):
    return create_record(db, RequestingPhysician, payload, PhysicianResponse, actor.user_id,
                         get_request_ip(request), 'PHYSICIAN_CREATE')


@router.get('', response_model=Page[PhysicianResponse])
def list_all(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    referring_facility_id: Identifier | None = None,
    is_active: bool | None = None,
    actor: UserAccount = Depends(require_permission('PHYSICIAN_READ')),
    db: Session = Depends(get_db),
):
    return list_records(db, RequestingPhysician, page=page, page_size=page_size, search=search,
                        search_fields=('first_name', 'middle_name', 'last_name', 'license_number'), filters={'referring_facility_id': referring_facility_id, 'is_active': is_active})


@router.get('/{physician_id}', response_model=PhysicianResponse)
def detail(physician_id: Identifier,
           actor: UserAccount = Depends(require_permission('PHYSICIAN_READ')),
           db: Session = Depends(get_db)):
    return get_record(db, RequestingPhysician, physician_id)


@router.patch('/{physician_id}', response_model=PhysicianResponse)
def patch(physician_id: Identifier, payload: PhysicianPatch, request: Request,
          actor: UserAccount = Depends(require_permission('PHYSICIAN_UPDATE')),
          db: Session = Depends(get_db)):
    return patch_record(db, RequestingPhysician, physician_id, payload, PhysicianResponse,
                        actor.user_id, get_request_ip(request), 'PHYSICIAN_UPDATE')
