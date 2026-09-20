"""Authenticated PATIENT routes use account-link identity, never caller patient IDs."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip
from app.dependencies.patient import PatientContext, require_patient_mfa
from app.schemas import patient_portal as s
from app.schemas.identity import Identifier, Page
from app.services import patient_portal_service as service

router = APIRouter(prefix='/patient', tags=['Patient Portal'], route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
CurrentPatient = Annotated[PatientContext, Depends(require_patient_mfa)]


@router.get('/me', response_model=s.PatientProfile)
def current_profile(patient: CurrentPatient):
    return s.PatientProfile.model_validate(patient.patient)


@router.get('/reports', response_model=Page[s.ReportSummary])
def list_reports(db: Db, patient: CurrentPatient, filters: Annotated[s.ReportFilters, Query()]):
    return service.report_list(db, patient, filters)


@router.get('/reports/{report_id}', response_model=s.ReportDetail)
def report_detail(report_id: Identifier, request: Request, db: Db, patient: CurrentPatient):
    return service.report_detail(db, patient, report_id, get_request_ip(request))


@router.get('/reports/{report_id}/pdf', response_class=StreamingResponse,
            responses={200: {'content': {'application/pdf': {}}}})
def report_pdf(report_id: Identifier, request: Request, db: Db, patient: CurrentPatient):
    return service.report_pdf(db, patient, report_id, get_request_ip(request))


@router.get('/access-history', response_model=Page[s.AccessEvent])
def access_history(db: Db, patient: CurrentPatient, paging: Annotated[s.Pagination, Query()]):
    return service.access_history(db, patient, paging)
