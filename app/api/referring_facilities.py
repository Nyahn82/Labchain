"""Referring Facilities HTTP API using existing session, CSRF and permission dependencies."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import ReferringFacility, UserAccount
from app.schemas.identity import FacilityCreate, FacilityPatch, FacilityResponse, Page, Identifier
from app.services.identity_service import create_record, get_record, list_records, patch_record

router = APIRouter(prefix='/referring-facilities', tags=['Referring Facilities'], route_class=PrivateRoute)


@router.post('', response_model=FacilityResponse, status_code=201)
def create(payload: FacilityCreate, request: Request,
           actor: UserAccount = Depends(require_permission('REFERRING_FACILITY_CREATE')),
           db: Session = Depends(get_db)):
    return create_record(db, ReferringFacility, payload, FacilityResponse, actor.user_id,
                         get_request_ip(request), 'REFERRING_FACILITY_CREATE')


@router.get('', response_model=Page[FacilityResponse])
def list_all(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    actor: UserAccount = Depends(require_permission('REFERRING_FACILITY_READ')),
    db: Session = Depends(get_db),
):
    return list_records(db, ReferringFacility, page=page, page_size=page_size, search=search,
                        search_fields=('facility_name',), filters={})


@router.get('/{referring_facility_id}', response_model=FacilityResponse)
def detail(referring_facility_id: Identifier,
           actor: UserAccount = Depends(require_permission('REFERRING_FACILITY_READ')),
           db: Session = Depends(get_db)):
    return get_record(db, ReferringFacility, referring_facility_id)


@router.patch('/{referring_facility_id}', response_model=FacilityResponse)
def patch(referring_facility_id: Identifier, payload: FacilityPatch, request: Request,
          actor: UserAccount = Depends(require_permission('REFERRING_FACILITY_UPDATE')),
          db: Session = Depends(get_db)):
    return patch_record(db, ReferringFacility, referring_facility_id, payload, FacilityResponse,
                        actor.user_id, get_request_ip(request), 'REFERRING_FACILITY_UPDATE')
