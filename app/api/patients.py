"""Patients HTTP API using existing session, CSRF and permission dependencies."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import Patient, UserAccount
from app.schemas.identity import PatientCreate, PatientPatch, PatientResponse, Page, Identifier, Sex
from app.services.identity_service import create_record, get_record, list_records, patch_record

router = APIRouter(prefix='/patients', tags=['Patients'], route_class=PrivateRoute)


@router.post('', response_model=PatientResponse, status_code=201)
def create(payload: PatientCreate, request: Request,
           actor: UserAccount = Depends(require_permission('PATIENT_CREATE')),
           db: Session = Depends(get_db)):
    return create_record(db, Patient, payload, PatientResponse, actor.user_id,
                         get_request_ip(request), 'PATIENT_CREATE')


@router.get('', response_model=Page[PatientResponse])
def list_all(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    patient_code: str | None = None,
    sex: Sex | None = None,
    actor: UserAccount = Depends(require_permission('PATIENT_READ')),
    db: Session = Depends(get_db),
):
    return list_records(db, Patient, page=page, page_size=page_size, search=search,
                        search_fields=('patient_code', 'first_name', 'middle_name', 'last_name'), filters={'patient_code': patient_code, 'sex': sex})


@router.get('/{patient_id}', response_model=PatientResponse)
def detail(patient_id: Identifier,
           actor: UserAccount = Depends(require_permission('PATIENT_READ')),
           db: Session = Depends(get_db)):
    return get_record(db, Patient, patient_id)


@router.patch('/{patient_id}', response_model=PatientResponse)
def patch(patient_id: Identifier, payload: PatientPatch, request: Request,
          actor: UserAccount = Depends(require_permission('PATIENT_UPDATE')),
          db: Session = Depends(get_db)):
    return patch_record(db, Patient, patient_id, payload, PatientResponse,
                        actor.user_id, get_request_ip(request), 'PATIENT_UPDATE')
