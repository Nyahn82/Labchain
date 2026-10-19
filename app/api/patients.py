"""Patients HTTP API using existing session, CSRF and permission dependencies."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import Patient, UserAccount
from app.schemas.identity import PatientCreate, PatientPatch, PatientResponse, PatientDirectoryResponse, Page, Identifier, Sex
from app.services.identity_service import create_record, get_record, list_records, patch_record

from app.services.patient_activation_service import activation_states, can_read_status, patient_directory

router = APIRouter(prefix='/patients', tags=['Patients'], route_class=PrivateRoute)


@router.post('', response_model=PatientResponse, status_code=201)
def create(payload: PatientCreate, request: Request,
           actor: UserAccount = Depends(require_permission('PATIENT_CREATE')),
           db: Session = Depends(get_db)):
    return create_record(db, Patient, payload, PatientResponse, actor.user_id,
                         get_request_ip(request), 'PATIENT_CREATE')


@router.get('', response_model=Page[PatientDirectoryResponse], response_model_exclude_unset=True)
def list_all(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    patient_code: str | None = None,
    sex: Sex | None = None,
    activation_group: Literal['ACTIVATED', 'NOT_ACTIVATED'] | None = None,
    activation_state: Literal['NOT_ACTIVATED', 'TOKEN_ACTIVE', 'TOKEN_EXPIRED', 'TOKEN_REVOKED', 'ACTIVATED', 'REVIEW_REQUIRED'] | None = None,
    sort_by: Literal['patient_id', 'patient_code', 'name', 'activation'] = 'patient_id',
    sort_direction: Literal['asc', 'desc'] = 'asc',
    actor: UserAccount = Depends(require_permission('PATIENT_READ')),
    db: Session = Depends(get_db),
):
    if (activation_group or activation_state or sort_by == 'activation') and not can_read_status(db, actor.user_id):
        raise HTTPException(403, 'Activation status access required.')
    result = patient_directory(db, page=page, page_size=page_size, search=search,
        patient_code=patient_code, sex=sex, activation_group=activation_group,
        activation_state=activation_state, sort_by=sort_by, sort_direction=sort_direction)
    result['items'] = directory_items(db, result['items'], actor.user_id)
    return result


@router.get('/{patient_id}', response_model=PatientDirectoryResponse, response_model_exclude_unset=True)
def detail(patient_id: Identifier,
           actor: UserAccount = Depends(require_permission('PATIENT_READ')),
           db: Session = Depends(get_db)):
    return directory_items(db, [get_record(db, Patient, patient_id)], actor.user_id)[0]


@router.patch('/{patient_id}', response_model=PatientResponse)
def patch(patient_id: Identifier, payload: PatientPatch, request: Request,
          actor: UserAccount = Depends(require_permission('PATIENT_UPDATE')),
          db: Session = Depends(get_db)):
    return patch_record(db, Patient, patient_id, payload, PatientResponse,
                        actor.user_id, get_request_ip(request), 'PATIENT_UPDATE')


def directory_items(db, items, actor_id):
    states = activation_states(db, [item.patient_id for item in items]) if can_read_status(db, actor_id) else {}
    results = []
    for item in items:
        response = PatientDirectoryResponse.model_validate(item)
        if item.patient_id in states:
            response.activation_status = states[item.patient_id]
        results.append(response)
    return results
