"""Phase 3C protected laboratory master-data endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import (
    LabDepartment, SampleType, TestCatalog, TestPanel, PanelSection,
    ReferenceRange, TestInterpretationRule, UserAccount,
)
from app.schemas import laboratory as s
from app.schemas.identity import Identifier, Page
from app.services import laboratory_service as service
from app.services.identity_service import get_record, list_records

router = APIRouter(prefix='/lab', tags=['Laboratory Master Data'], route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
Reader = Annotated[UserAccount, Depends(require_permission('LAB_MASTER_READ'))]


def pagination(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return {'page': page, 'page_size': page_size}


Paging = Annotated[dict, Depends(pagination)]


@router.post('/departments', response_model=s.DepartmentResponse, status_code=201)
def create_department(payload: s.DepartmentCreate, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('LAB_DEPARTMENT_MANAGE'))]):
    return service.save_record(db, LabDepartment, payload, s.DepartmentResponse, actor.user_id,
                               get_request_ip(request), 'LAB_DEPARTMENT_CREATE')


@router.get('/departments', response_model=Page[s.DepartmentResponse])
def list_departments(db: Db, actor: Reader, paging: Paging,
                  search: str | None = Query(None, max_length=200),
                  is_active: bool | None = None):
    return list_records(db, LabDepartment, **paging, search=search,
                        search_fields=('department_code', 'department_name'),
                        filters={'is_active': is_active})


@router.get('/departments/{department_id}', response_model=s.DepartmentResponse)
def get_department(department_id: Identifier, db: Db, actor: Reader):
    return get_record(db, LabDepartment, department_id)


@router.patch('/departments/{department_id}', response_model=s.DepartmentResponse)
def patch_department(department_id: Identifier, payload: s.DepartmentPatch, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('LAB_DEPARTMENT_MANAGE'))]):
    return service.save_record(db, LabDepartment, payload, s.DepartmentResponse, actor.user_id,
                               get_request_ip(request), 'LAB_DEPARTMENT_UPDATE', record_id=department_id)


@router.post('/sample-types', response_model=s.SampleTypeResponse, status_code=201)
def create_sample_type(payload: s.SampleTypeCreate, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('SAMPLE_TYPE_MANAGE'))]):
    return service.save_record(db, SampleType, payload, s.SampleTypeResponse, actor.user_id,
                               get_request_ip(request), 'SAMPLE_TYPE_CREATE')


@router.get('/sample-types', response_model=Page[s.SampleTypeResponse])
def list_sample_types(db: Db, actor: Reader, paging: Paging,
                  search: str | None = Query(None, max_length=200),
                  is_active: bool | None = None):
    return list_records(db, SampleType, **paging, search=search,
                        search_fields=('sample_name',),
                        filters={'is_active': is_active})


@router.get('/sample-types/{sample_type_id}', response_model=s.SampleTypeResponse)
def get_sample_type(sample_type_id: Identifier, db: Db, actor: Reader):
    return get_record(db, SampleType, sample_type_id)


@router.patch('/sample-types/{sample_type_id}', response_model=s.SampleTypeResponse)
def patch_sample_type(sample_type_id: Identifier, payload: s.SampleTypePatch, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('SAMPLE_TYPE_MANAGE'))]):
    return service.save_record(db, SampleType, payload, s.SampleTypeResponse, actor.user_id,
                               get_request_ip(request), 'SAMPLE_TYPE_UPDATE', record_id=sample_type_id)


@router.post('/tests', response_model=s.TestResponse, status_code=201)
def create_test(payload: s.TestCreate, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('TEST_CATALOG_MANAGE'))]):
    return service.save_record(db, TestCatalog, payload, s.TestResponse, actor.user_id,
                               get_request_ip(request), 'TEST_CREATE')


@router.get('/tests', response_model=Page[s.TestResponse])
def list_tests(db: Db, actor: Reader, paging: Paging,
                  search: str | None = Query(None, max_length=200),
                  is_active: bool | None = None,
                  department_id: Identifier | None = None,
                  result_type: s.ResultType | None = None):
    return list_records(db, TestCatalog, **paging, search=search,
                        search_fields=('test_code', 'test_name'),
                        filters={'is_active': is_active, 'department_id': department_id, 'result_type': result_type})


@router.get('/tests/{test_id}', response_model=s.TestDetail)
def get_test(test_id: Identifier, db: Db, actor: Reader):
    return service.test_detail(db, test_id)


@router.patch('/tests/{test_id}', response_model=s.TestResponse)
def patch_test(test_id: Identifier, payload: s.TestPatch, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('TEST_CATALOG_MANAGE'))]):
    return service.save_record(db, TestCatalog, payload, s.TestResponse, actor.user_id,
                               get_request_ip(request), 'TEST_UPDATE', record_id=test_id)


@router.post('/panels', response_model=s.PanelResponse, status_code=201)
def create_panel(payload: s.PanelCreate, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('TEST_PANEL_MANAGE'))]):
    return service.save_record(db, TestPanel, payload, s.PanelResponse, actor.user_id,
                               get_request_ip(request), 'PANEL_CREATE')


@router.get('/panels', response_model=Page[s.PanelResponse])
def list_panels(db: Db, actor: Reader, paging: Paging,
                  search: str | None = Query(None, max_length=200),
                  is_active: bool | None = None,
                  department_id: Identifier | None = None):
    return list_records(db, TestPanel, **paging, search=search,
                        search_fields=('panel_code', 'panel_name'),
                        filters={'is_active': is_active, 'department_id': department_id})


@router.get('/panels/{panel_id}', response_model=s.PanelDetail)
def get_panel(panel_id: Identifier, db: Db, actor: Reader):
    return service.panel_detail(db, panel_id)


@router.patch('/panels/{panel_id}', response_model=s.PanelResponse)
def patch_panel(panel_id: Identifier, payload: s.PanelPatch, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('TEST_PANEL_MANAGE'))]):
    return service.save_record(db, TestPanel, payload, s.PanelResponse, actor.user_id,
                               get_request_ip(request), 'PANEL_UPDATE', record_id=panel_id)


@router.get('/tests/{test_id}/sample-types', response_model=list[s.SampleAssignmentResponse])
def get_sample_assignments(test_id: Identifier, db: Db, actor: Reader):
    get_record(db, TestCatalog, test_id)
    return service.sample_assignments(db, test_id)


@router.put('/tests/{test_id}/sample-types', response_model=list[s.SampleAssignmentResponse])
def replace_sample_assignments(test_id: Identifier, payload: s.SampleReplacement, request: Request, db: Db,
                               actor: Annotated[UserAccount, Depends(require_permission('TEST_CATALOG_MANAGE'))]):
    return service.replace_sample_types(db, test_id, payload, actor.user_id, get_request_ip(request))


@router.get('/panels/{panel_id}/sections', response_model=list[s.SectionResponse])
def get_sections(panel_id: Identifier, db: Db, actor: Reader):
    get_record(db, TestPanel, panel_id)
    return service.sections(db, panel_id)


@router.post('/panels/{panel_id}/sections', response_model=s.SectionResponse, status_code=201)
def create_section(panel_id: Identifier, payload: s.SectionCreate, request: Request, db: Db,
                   actor: Annotated[UserAccount, Depends(require_permission('TEST_PANEL_MANAGE'))]):
    return service.save_record(db, PanelSection, payload, s.SectionResponse, actor.user_id,
                               get_request_ip(request), 'PANEL_SECTION_CREATE', parent_id=panel_id)


@router.patch('/panels/{panel_id}/sections/{section_id}', response_model=s.SectionResponse)
def patch_section(panel_id: Identifier, section_id: Identifier, payload: s.SectionPatch, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('TEST_PANEL_MANAGE'))]):
    return service.save_record(db, PanelSection, payload, s.SectionResponse, actor.user_id,
                               get_request_ip(request), 'PANEL_SECTION_UPDATE', parent_id=panel_id, record_id=section_id)


@router.get('/panels/{panel_id}/tests', response_model=list[s.PanelAssignmentResponse])
def get_panel_assignments(panel_id: Identifier, db: Db, actor: Reader):
    get_record(db, TestPanel, panel_id)
    return service.panel_assignments(db, panel_id)


@router.put('/panels/{panel_id}/tests', response_model=list[s.PanelAssignmentResponse])
def replace_panel_assignments(panel_id: Identifier, payload: s.PanelReplacement, request: Request, db: Db,
                              actor: Annotated[UserAccount, Depends(require_permission('TEST_PANEL_MANAGE'))]):
    return service.replace_panel_tests(db, panel_id, payload, actor.user_id, get_request_ip(request))


@router.post('/tests/{test_id}/reference-ranges', response_model=s.RangeResponse, status_code=201)
def create_range(test_id: Identifier, payload: s.RangeCreate, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('REFERENCE_RANGE_MANAGE'))]):
    return service.save_record(db, ReferenceRange, payload, s.RangeResponse, actor.user_id,
                               get_request_ip(request), 'REFERENCE_RANGE_CREATE', parent_id=test_id)


@router.get('/tests/{test_id}/reference-ranges', response_model=Page[s.RangeResponse])
def list_ranges(test_id: Identifier, db: Db, actor: Reader, paging: Paging, is_active: bool | None = None):
    get_record(db, TestCatalog, test_id)
    return list_records(db, ReferenceRange, **paging, filters={'test_id': test_id, 'is_active': is_active})


@router.get('/reference-ranges/{range_id}', response_model=s.RangeResponse)
def get_range(range_id: Identifier, db: Db, actor: Reader):
    return get_record(db, ReferenceRange, range_id)


@router.patch('/reference-ranges/{range_id}', response_model=s.RangeResponse)
def patch_range(range_id: Identifier, payload: s.RangePatch, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('REFERENCE_RANGE_MANAGE'))]):
    return service.save_record(db, ReferenceRange, payload, s.RangeResponse, actor.user_id,
                               get_request_ip(request), 'REFERENCE_RANGE_UPDATE', record_id=range_id)


@router.post('/tests/{test_id}/interpretation-rules', response_model=s.RuleResponse, status_code=201)
def create_rule(test_id: Identifier, payload: s.RuleCreate, request: Request, db: Db,
                  actor: Annotated[UserAccount, Depends(require_permission('INTERPRETATION_RULE_MANAGE'))]):
    return service.save_record(db, TestInterpretationRule, payload, s.RuleResponse, actor.user_id,
                               get_request_ip(request), 'INTERPRETATION_RULE_CREATE', parent_id=test_id)


@router.get('/tests/{test_id}/interpretation-rules', response_model=Page[s.RuleResponse])
def list_rules(test_id: Identifier, db: Db, actor: Reader, paging: Paging, is_active: bool | None = None):
    get_record(db, TestCatalog, test_id)
    return list_records(db, TestInterpretationRule, **paging, filters={'test_id': test_id, 'is_active': is_active})


@router.get('/interpretation-rules/{rule_id}', response_model=s.RuleResponse)
def get_rule(rule_id: Identifier, db: Db, actor: Reader):
    return get_record(db, TestInterpretationRule, rule_id)


@router.patch('/interpretation-rules/{rule_id}', response_model=s.RuleResponse)
def patch_rule(rule_id: Identifier, payload: s.RulePatch, request: Request, db: Db,
                 actor: Annotated[UserAccount, Depends(require_permission('INTERPRETATION_RULE_MANAGE'))]):
    return service.save_record(db, TestInterpretationRule, payload, s.RuleResponse, actor.user_id,
                               get_request_ip(request), 'INTERPRETATION_RULE_UPDATE', record_id=rule_id)


@router.get('/tests/{test_id}/reference-range', response_model=s.RangeResponse)
def resolve_range(test_id: Identifier, db: Db, actor: Reader, query: Annotated[s.ResolverQuery, Query()]):
    result = service.resolve_reference_range(db, test_id, query.sex, query.age_years, query.as_of_date)
    if result is None:
        raise HTTPException(404, 'No applicable reference range.')
    return result
