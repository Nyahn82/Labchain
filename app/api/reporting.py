"""Phase 5A authenticated reporting endpoints; no release or snapshot edit routes."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.laboratory import Paging
from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import LabOrder, LabReport, ReportTemplate, Signatory, UserAccount
from app.schemas import reporting as s
from app.schemas.identity import Identifier, Page
from app.services import reporting_service as service
from app.services.identity_service import get_record, list_records

router = APIRouter(tags=['Official Reports'], route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
FacilityReader = Annotated[UserAccount, Depends(require_permission('FACILITY_PROFILE_READ'))]
FacilityManager = Annotated[UserAccount, Depends(require_permission('FACILITY_PROFILE_MANAGE'))]
TemplateReader = Annotated[UserAccount, Depends(require_permission('REPORT_TEMPLATE_READ'))]
TemplateManager = Annotated[UserAccount, Depends(require_permission('REPORT_TEMPLATE_MANAGE'))]
SignatoryReader = Annotated[UserAccount, Depends(require_permission('SIGNATORY_READ'))]
SignatoryManager = Annotated[UserAccount, Depends(require_permission('SIGNATORY_MANAGE'))]
ReportReader = Annotated[UserAccount, Depends(require_permission('REPORT_READ'))]
Search = Annotated[str | None, Query(max_length=200)]


@router.get('/facility-profile', response_model=s.FacilityResponse)
def get_facility(db: Db, actor: FacilityReader):
    return service.facility(db)


@router.post('/facility-profile', response_model=s.FacilityResponse, status_code=201)
def create_facility(payload: s.FacilityCreate, request: Request, db: Db, actor: FacilityManager):
    return service.save_facility(db, payload, actor.user_id, get_request_ip(request), create=True)


@router.patch('/facility-profile', response_model=s.FacilityResponse)
def patch_facility(payload: s.FacilityPatch, request: Request, db: Db, actor: FacilityManager):
    return service.save_facility(db, payload, actor.user_id, get_request_ip(request))


@router.post('/report-templates', response_model=s.TemplateResponse, status_code=201)
def create_template(payload: s.TemplateCreate, request: Request, db: Db, actor: TemplateManager):
    return service.save_configuration(db, ReportTemplate, payload, actor.user_id, get_request_ip(request))


@router.get('/report-templates', response_model=Page[s.TemplateResponse])
def list_templates(db: Db, actor: TemplateReader, paging: Paging, search: Search = None,
                   panel_id: Identifier | None = None, is_active: bool | None = None):
    return list_records(db, ReportTemplate, **paging, search=search,
                        search_fields=('template_code', 'template_name'), filters={'panel_id': panel_id, 'is_active': is_active})


@router.get('/report-templates/{template_id}', response_model=s.TemplateResponse)
def get_template(template_id: Identifier, db: Db, actor: TemplateReader):
    return get_record(db, ReportTemplate, template_id)


@router.patch('/report-templates/{template_id}', response_model=s.TemplateResponse)
def patch_template(template_id: Identifier, payload: s.TemplatePatch, request: Request, db: Db, actor: TemplateManager):
    return service.save_configuration(db, ReportTemplate, payload, actor.user_id, get_request_ip(request), record_id=template_id)


@router.post('/signatories', response_model=s.SignatoryResponse, status_code=201)
def create_signatory(payload: s.SignatoryCreate, request: Request, db: Db, actor: SignatoryManager):
    return service.save_configuration(db, Signatory, payload, actor.user_id, get_request_ip(request))


@router.get('/signatories', response_model=Page[s.SignatoryResponse])
def list_signatories(db: Db, actor: SignatoryReader, paging: Paging, search: Search = None,
                     staff_id: Identifier | None = None, is_active: bool | None = None):
    return list_records(db, Signatory, **paging, search=search, search_fields=('license_number_snapshot',),
                        filters={'staff_id': staff_id, 'is_active': is_active})


@router.get('/signatories/{signatory_id}', response_model=s.SignatoryResponse)
def get_signatory(signatory_id: Identifier, db: Db, actor: SignatoryReader):
    return get_record(db, Signatory, signatory_id)


@router.patch('/signatories/{signatory_id}', response_model=s.SignatoryResponse)
def patch_signatory(signatory_id: Identifier, payload: s.SignatoryPatch, request: Request, db: Db, actor: SignatoryManager):
    return service.save_configuration(db, Signatory, payload, actor.user_id, get_request_ip(request), record_id=signatory_id)


@router.post('/lab-orders/{order_id}/reports', response_model=s.ReportDetail, status_code=201)
def generate_report(order_id: Identifier, payload: s.GenerateRequest, request: Request, db: Db,
                    actor: Annotated[UserAccount, Depends(require_permission('REPORT_GENERATE'))]):
    return service.generate_report(db, order_id, payload, actor.user_id, get_request_ip(request))


@router.get('/reports', response_model=Page[s.ReportResponse])
def list_reports(db: Db, actor: ReportReader, paging: Paging, search: Search = None,
                 order_id: Identifier | None = None, status: s.ReportStatus | None = None,
                 date_from: date | None = None, date_to: date | None = None):
    return service.list_reports(db, **paging, search=search, order_id=order_id, status=status,
                                date_from=date_from, date_to=date_to)


@router.get('/reports/{report_id}', response_model=s.ReportDetail)
def get_report(report_id: Identifier, db: Db, actor: ReportReader):
    return service.report_detail(db, report_id)


@router.get('/lab-orders/{order_id}/reports', response_model=Page[s.ReportResponse])
def order_reports(order_id: Identifier, db: Db, actor: ReportReader, paging: Paging):
    get_record(db, LabOrder, order_id)
    return service.list_reports(db, **paging, order_id=order_id)


@router.get('/reports/{report_id}/signatories', response_model=list[s.ReportSignatoryResponse])
def get_report_signatories(report_id: Identifier, db: Db, actor: ReportReader):
    get_record(db, LabReport, report_id)
    return service.report_signatories(db, report_id)


@router.post('/reports/{report_id}/signatories', response_model=s.ReportSignatoryResponse, status_code=201)
def assign_signatory(report_id: Identifier, payload: s.AssignRequest, request: Request, db: Db, actor: SignatoryManager):
    return service.assign_signatory(db, report_id, payload, actor.user_id, get_request_ip(request))


@router.post('/reports/{report_id}/sign', response_model=s.ReportSignatoryResponse)
def sign_report(report_id: Identifier, payload: s.SignRequest, request: Request, db: Db,
                actor: Annotated[UserAccount, Depends(require_permission('REPORT_SIGN'))]):
    return service.sign_report(db, report_id, payload, actor.user_id, get_request_ip(request))


@router.post('/reports/{report_id}/approve', response_model=s.ReportDetail)
def approve_report(report_id: Identifier, request: Request, db: Db,
                   actor: Annotated[UserAccount, Depends(require_permission('REPORT_APPROVE'))]):
    return service.approve_report(db, report_id, actor.user_id, get_request_ip(request))
