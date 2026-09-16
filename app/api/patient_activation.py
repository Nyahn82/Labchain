"""Controlled staff issuance and unauthenticated one-time activation."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import UserAccount
from app.schemas import patient_portal as s
from app.schemas.identity import Identifier
from app.services import patient_activation_service as service

router = APIRouter(tags=['Patient Activation'], route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
Issuer = Annotated[UserAccount, Depends(require_permission('PATIENT_ACCOUNT_ACTIVATE'))]
StatusReader = Annotated[UserAccount, Depends(require_permission('PATIENT_ACCOUNT_ACTIVATE', 'ACCOUNT_READ'))]


@router.post('/patients/{patient_id}/activation-token', response_model=s.TokenIssued, status_code=201)
def issue_activation_token(patient_id: Identifier, request: Request, db: Db, actor: Issuer):
    return service.issue_token(db, patient_id, actor.user_id, get_request_ip(request))


@router.get('/patients/{patient_id}/activation-status', response_model=s.ActivationStatus)
def activation_status(patient_id: Identifier, db: Db, actor: StatusReader):
    return service.activation_status(db, patient_id)


@router.post('/patient/activate', response_model=s.ActivatedAccount, status_code=201)
def activate_patient(payload: s.ActivationRequest, request: Request, db: Db):
    return service.activate(db, payload, get_request_ip(request))
