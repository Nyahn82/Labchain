"""Synthetic reporting API, snapshot integrity, privacy and atomicity regression."""
from datetime import date, datetime
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import reporting
from app.cli import bootstrap_permissions
from app.models import (
    AuditLog, FacilityProfile, LabOrder, LabOrderItem, LabReport, LabResultItem,
    PanelTest, Patient, Permission, ReferenceRange, ReportPatientSnapshot,
    ReportResultItem, ReportSignatory, ReportTemplate, ReportVerification,
    RolePermission, Signatory, Staff, StaffAccountLink, TestCatalog as Catalog, UserRole,
)
from app.services import reporting_service as service
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from app.services.report_formatting import full_years, printable_name, printable_range
from test_phase_3a_authentication_rbac import env, password_hash, login, count, PASSWORD
from test_phase_3c_laboratory import lab_api
from test_phase_4a_workflow import workflow_api, call, create, order
from test_phase_4b_results import results_api, finish, requested


@pytest.fixture
def reports_api(results_api):
    results_api.app.include_router(reporting.router, prefix='/api/v1')
    with results_api.factory.begin() as db:
        db.add_all(Staff(staff_id=i, staff_code=f'STAFF-{i}', first_name='Synthetic', last_name=f'Signer{i}',
                         is_active=i != 3) for i in (1, 2, 3))
        db.flush()
        db.add(StaffAccountLink(staff_id=1, user_id=1))
    return results_api


@pytest.fixture
def admin(reports_api):
    with reports_api.factory.begin() as db:
        db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
        db.add(FacilityProfile(facility_id=1, facility_name='Synthetic RHU'))
    assert login(reports_api).status_code == 200
    return reports_api


def completed(api, **kwargs):
    row = requested(api, **kwargs)
    for item in row['items']:
        finish(api, item['order_item_id'])
    return row


def generate(api, order_id=1, **values):
    return call(api, 'POST', f'/lab-orders/{order_id}/reports', values)


def generated(api, **values):
    completed(api)
    response = generate(api, **values)
    assert response.status_code == 201, response.text
    return response.json()


def report(api, report_id=1):
    response = call(api, 'GET', f'/reports/{report_id}')
    assert response.status_code == 200, response.text
    return response.json()


def assigned(api, staff_id=1, **values):
    profile = create(api, '/signatories', {'staff_id': staff_id, 'license_number_snapshot': 'SYNTH-LIC'})
    return create(api, '/reports/1/signatories', {'signatory_id': profile['signatory_id'],
        'signatory_type': 'MEDICAL_TECHNOLOGIST', **values})


def sign(api, assignment_id=1, report_id=1):
    return call(api, 'POST', f'/reports/{report_id}/sign', {'report_signatory_id': assignment_id})


def approve(api):
    return call(api, 'POST', '/reports/1/approve')


ENDPOINTS = [
    ('GET', '/facility-profile', None, 'FACILITY_PROFILE_READ'),
    ('POST', '/facility-profile', {'facility_name': 'Synthetic'}, 'FACILITY_PROFILE_MANAGE'),
    ('PATCH', '/facility-profile', {}, 'FACILITY_PROFILE_MANAGE'),
    ('POST', '/report-templates', {'template_code': 'T', 'template_name': 'Synthetic'}, 'REPORT_TEMPLATE_MANAGE'),
    ('GET', '/report-templates', None, 'REPORT_TEMPLATE_READ'),
    ('GET', '/report-templates/999', None, 'REPORT_TEMPLATE_READ'),
    ('PATCH', '/report-templates/999', {}, 'REPORT_TEMPLATE_MANAGE'),
    ('POST', '/signatories', {'staff_id': 1}, 'SIGNATORY_MANAGE'),
    ('GET', '/signatories', None, 'SIGNATORY_READ'),
    ('GET', '/signatories/999', None, 'SIGNATORY_READ'),
    ('PATCH', '/signatories/999', {}, 'SIGNATORY_MANAGE'),
    ('POST', '/lab-orders/999/reports', {}, 'REPORT_GENERATE'),
    ('GET', '/lab-orders/999/reports', None, 'REPORT_READ'),
    ('GET', '/reports', None, 'REPORT_READ'),
    ('GET', '/reports/999', None, 'REPORT_READ'),
    ('GET', '/reports/999/signatories', None, 'REPORT_READ'),
    ('POST', '/reports/999/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'}, 'SIGNATORY_MANAGE'),
    ('POST', '/reports/999/sign', {'report_signatory_id': 1}, 'REPORT_SIGN'),
    ('POST', '/reports/999/approve', None, 'REPORT_APPROVE'),
]


@pytest.mark.parametrize('method,path,body,permission', ENDPOINTS)
def test_auth_rbac_csrf_every_operation(reports_api, method, path, body, permission):
    assert reports_api.client.request(method, '/api/v1' + path, json=body).status_code == 401
    assert login(reports_api).status_code == 200
    assert call(reports_api, method, path, body).status_code == 403
    with reports_api.factory.begin() as db:
        pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == permission))
        db.add(RolePermission(role_id=1, permission_id=pid))
    if method != 'GET':
        for headers in ({}, {'X-CSRF-Token': 'wrong'}):
            assert reports_api.client.request(method, '/api/v1' + path, json=body, headers=headers).status_code == 403
    response = call(reports_api, method, path, body)
    assert response.status_code in (200, 201, 404), response.text
    assert response.headers['cache-control'] == 'no-store'


def test_facility_missing_first_setup_singleton_and_audit(admin):
    with admin.factory.begin() as db:
        db.execute(delete(FacilityProfile))
    assert call(admin, 'GET', '/facility-profile').status_code == 404
    assert call(admin, 'PATCH', '/facility-profile', {'facility_name': 'Missing'}).status_code == 404
    row = create(admin, '/facility-profile', {'facility_name': 'Synthetic new RHU', 'logo_path': '/metadata/logo.png'})
    assert row['facility_id'] == 1
    assert call(admin, 'POST', '/facility-profile', {'facility_name': 'Second'}).status_code == 409
    changed = call(admin, 'PATCH', '/facility-profile', {'contact_number': '123', 'logo_path': None})
    assert changed.status_code == 200 and changed.json()['updated_at'] and changed.json()['logo_path'] is None
    with admin.factory() as db:
        assert count(db, FacilityProfile) == 1
        assert set(db.scalars(select(AuditLog.action))) >= {'FACILITY_PROFILE_CREATE', 'FACILITY_PROFILE_UPDATE'}


@pytest.mark.parametrize('payload', [{'facility_id': 2}, {'facility_name': None}, {'facility_name': ''},
    {'facility_name': 'x' * 151}, {'email': 'bad'}, {'website': 'x' * 151}, {'logo_path': 'x' * 256}])
def test_facility_validation(admin, payload):
    assert call(admin, 'PATCH', '/facility-profile', payload).status_code == 422


def test_multiple_legacy_facilities_rejected(admin):
    with admin.factory.begin() as db:
        db.add(FacilityProfile(facility_name='Second legacy facility'))
    assert call(admin, 'GET', '/facility-profile').status_code == 409
    completed(admin)
    assert generate(admin).status_code == 409


def test_template_crud_filters_duplicate_and_optional_panel(admin):
    first = create(admin, '/report-templates', {'template_code': 'GENERAL', 'template_name': 'Synthetic general'})
    assert first['panel_id'] is None
    create(admin, '/report-templates', {'template_code': 'PANEL', 'template_name': 'Synthetic panel', 'panel_id': 1})
    assert call(admin, 'POST', '/report-templates', {'template_code': 'GENERAL', 'template_name': 'Duplicate'}).status_code == 409
    assert call(admin, 'POST', '/report-templates', {'template_code': 'BAD', 'template_name': 'Bad', 'panel_id': 999}).status_code == 422
    assert call(admin, 'PATCH', '/report-templates/1', {'panel_id': 999}).status_code == 422
    assert call(admin, 'GET', '/report-templates/1').json() == first
    assert call(admin, 'GET', '/report-templates?search=general&page_size=1').json()['total'] == 1
    assert call(admin, 'GET', '/report-templates?panel_id=1').json()['items'][0]['template_code'] == 'PANEL'
    assert call(admin, 'PATCH', '/report-templates/2', {'template_code': 'GENERAL'}).status_code == 409
    assert call(admin, 'PATCH', '/report-templates/1', {'is_active': False, 'header_title': 'New'}).status_code == 200
    assert call(admin, 'GET', '/report-templates?is_active=false').json()['total'] == 1


def test_signatory_crud_staff_validation_and_multiple_profiles(admin):
    assert call(admin, 'POST', '/signatories', {'staff_id': 999}).status_code == 422
    assert call(admin, 'POST', '/signatories', {'staff_id': 3}).status_code == 409
    inactive = create(admin, '/signatories', {'staff_id': 3, 'is_active': False})
    assert call(admin, 'PATCH', f'/signatories/{inactive["signatory_id"]}', {'is_active': True}).status_code == 409
    for _ in range(2):
        create(admin, '/signatories', {'staff_id': 1, 'license_number_snapshot': 'SYNTH'})
    assert call(admin, 'GET', '/signatories?staff_id=1&search=SYNTH&page_size=1&page=2').json()['total'] == 2
    assert call(admin, 'GET', '/signatories/1').json() == inactive
    assert call(admin, 'PATCH', '/signatories/2', {'license_number_snapshot': 'NEW', 'is_active': False}).status_code == 200
    assert call(admin, 'GET', '/signatories?is_active=false').json()['total'] == 2


@pytest.mark.parametrize('path,payload', [
    ('/report-templates', {'template_code': 'T', 'template_name': 'X', 'header_title': 'x' * 151}),
    ('/report-templates', {'template_code': '', 'template_name': 'X'}),
    ('/report-templates', {'template_code': 'T', 'template_name': 'X', 'template_id': 1}),
    ('/signatories', {'staff_id': None}), ('/signatories', {'staff_id': 1, 'signature_image_path': 'x' * 256}),
    ('/signatories', {'staff_id': 1, 'license_number_snapshot': 'x' * 51}),
])
def test_configuration_validation(admin, path, payload):
    assert call(admin, 'POST', path, payload).status_code == 422


@pytest.mark.parametrize('case', ['unknown', 'cancelled', 'requested', 'in_progress', 'draft', 'reviewed', 'missing_result',
    'duplicate_result', 'empty', 'item_incomplete', 'missing_facility', 'unknown_template', 'inactive_template', 'provenance'])
def test_generation_prerequisites(admin, case):
    if case == 'unknown':
        assert generate(admin, 999).status_code == 404
        return
    completed(admin)
    values = {}
    with admin.factory.begin() as db:
        if case in ('cancelled', 'requested', 'in_progress'):
            db.get(LabOrder, 1).status = case.upper()
        elif case in ('draft', 'reviewed'):
            db.get(LabResultItem, 1).status = case.upper()
        elif case == 'missing_result':
            db.execute(delete(LabResultItem))
        elif case == 'duplicate_result':
            db.add(LabResultItem(order_item_id=1, result_value='12', status='VERIFIED', encoded_by_user_id=1, encoded_at=utc_now()))
        elif case == 'empty':
            db.get(LabOrderItem, 1).status = 'CANCELLED'
        elif case == 'item_incomplete':
            db.get(LabOrderItem, 1).status = 'IN_PROGRESS'
        elif case == 'missing_facility':
            db.execute(delete(FacilityProfile))
        elif case == 'unknown_template':
            values['template_id'] = 999
        elif case == 'inactive_template':
            db.add(ReportTemplate(template_id=1, template_code='T', template_name='Inactive', is_active=False))
            values['template_id'] = 1
        elif case == 'provenance':
            db.get(LabResultItem, 1).verified_at = None
    response = generate(admin, **values)
    assert response.status_code == (404 if case == 'missing_facility' else 422 if case == 'unknown_template' else 409), response.text
    with admin.factory() as db:
        assert count(db, LabReport) == count(db, ReportPatientSnapshot) == count(db, ReportResultItem) == 0


def test_generation_snapshots_provenance_and_historical_reads(admin, monkeypatch):
    template = create(admin, '/report-templates', {'template_code': 'T', 'template_name': 'Template'})
    completed(admin)
    with admin.factory.begin() as db:
        p = db.get(Patient, 1)
        p.first_name, p.middle_name, p.last_name, p.suffix = 'Mary Ann', '  de  la ', 'CRUZ', 'Jr.'
        p.birth_date = date(2000, 9, 17)
        db.get(Catalog, 1).default_unit = 'fallback'
        db.get(ReferenceRange, 1).unit = 'selected'
        db.get(LabResultItem, 1).flag = 'HIGH'  # Copy stored flag; do not recompute.
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 9, 16, 12, 30))
    response = generate(admin, template_id=template['template_id'])
    assert response.status_code == 201, response.text
    row = response.json()
    assert row['report_code'].startswith('RPT-20260916-') and len(row['report_code']) <= 30
    assert row['version_no'] == 1 and row['supersedes_report_id'] is None and row['report_status'] == 'GENERATED'
    assert row['generated_by_user_id'] == 1 and row['generated_at'] == '2026-09-16T12:30:00'
    assert row['facility_id'] == row['facility']['facility_id'] == 1 and row['template'] == template
    p = row['patient_snapshot']
    assert p == dict(report_id=1, patient_code='P-SYNTH-1', patient_name='Mary Ann de la CRUZ Jr.', birth_date='2000-09-17',
                     age_at_report=25, sex='M', physician_name='Synthetic Physician')
    line = row['result_snapshots'][0]
    assert line['test_name_snapshot'] == 'Seed test 1' and line['result_value_snapshot'] == '12.60'
    assert line['unit_snapshot'] == 'selected' and line['reference_range_snapshot'] == '12 - 16' and line['flag_snapshot'] == 'HIGH'
    assert line['panel_id_snapshot'] is line['section_name_snapshot'] is None
    with admin.factory.begin() as db:
        db.get(Patient, 1).first_name = 'Changed'
        db.get(Catalog, 1).test_name = 'Changed'
        db.get(ReferenceRange, 1).normal_high = Decimal('999')
    assert report(admin) == row
    assert generate(admin).status_code == 409
    assert call(admin, 'PATCH', '/results/1', {'result_value': '13'}).status_code == 409


@pytest.mark.parametrize('birth,physician,expected', [(None, None, None), (date(2000, 1, 1), 1, 26)])
def test_optional_demographics(admin, birth, physician, expected, monkeypatch):
    completed(admin, physician_id=physician)
    with admin.factory.begin() as db:
        db.get(Patient, 1).birth_date = birth
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 9, 16))
    row = generate(admin).json()['patient_snapshot']
    assert row['age_at_report'] == expected
    assert row['physician_name'] == ('Synthetic Physician' if physician else None)


@pytest.mark.parametrize('low,high,kind,normal,expected', [
    ('13', '17', 'NUMERIC', None, '13 - 17'), ('12.5', '16.5', 'NUMERIC', None, '12.5 - 16.5'),
    (None, '200', 'NUMERIC', None, '<= 200'), ('5', None, 'NUMERIC', None, '>= 5'),
    ('0', '0.100', 'NUMERIC', None, '0 - 0.1'), (None, None, 'NUMERIC', None, None),
    (None, None, 'TEXT', 'Negative', 'Negative'), (None, None, 'POS_NEG', 'Non-reactive', 'Non-reactive'),
])
def test_range_formatting(low, high, kind, normal, expected):
    reference = SimpleNamespace(normal_low=Decimal(low) if low is not None else None,
                                normal_high=Decimal(high) if high is not None else None, qualitative_normal=normal)
    assert printable_range(reference, kind) == expected
    assert printable_range(None, kind) is None


@pytest.mark.parametrize('selected,default,has_range,expected', [('unit', 'fallback', True, 'unit'),
    (None, 'fallback', True, 'fallback'), (None, None, True, None), (None, 'fallback', False, 'fallback')])
def test_unit_precedence_missing_range(admin, selected, default, has_range, expected):
    completed(admin)
    with admin.factory.begin() as db:
        db.get(Catalog, 1).default_unit = default
        db.get(ReferenceRange, 1).unit = selected
        if not has_range:
            db.get(LabResultItem, 1).reference_range_id = None
            db.get(LabResultItem, 1).flag = None
    line = generate(admin).json()['result_snapshots'][0]
    assert line['unit_snapshot'] == expected
    if not has_range:
        assert line['reference_range_snapshot'] is line['flag_snapshot'] is None


def test_panel_section_fallback_order_and_cancelled_items(admin):
    row = order(admin)
    with admin.factory.begin() as db:
        db.get(LabOrderItem, row['items'][-1]['order_item_id']).status = 'CANCELLED'
    for item in row['items'][:-1]:
        finish(admin, item['order_item_id'])
    with admin.factory.begin() as db:
        for member in db.scalars(select(PanelTest).where(PanelTest.panel_id == 1)):
            member.section_id = 1
            member.sort_order = -member.test_id
        db.execute(delete(PanelTest).where(PanelTest.panel_id == 2))
    response = generate(admin)
    assert response.status_code == 201, response.text
    lines = response.json()['result_snapshots']
    assert len(lines) == 3 and [x['sort_order'] for x in lines] == [1, 2, 3]
    assert [x['result_item_id'] for x in lines] == [2, 1, 3]
    assert [x['panel_id_snapshot'] for x in lines] == [1, 1, 2]
    assert [x['section_name_snapshot'] for x in lines] == ['Seed section 1', 'Seed section 1', None]


def test_report_lists_search_filters_and_pagination(admin):
    first = generated(admin)
    second_order = completed(admin, physician_id=None)
    assert generate(admin, second_order['order_id']).status_code == 201
    assert call(admin, 'GET', '/reports?page=2&page_size=1').json()['items'][0]['report_id'] == 1
    assert call(admin, 'GET', '/reports?page=99').json()['items'] == []
    for search in [first['report_code'], first['patient_snapshot']['patient_code'], 'Synthetic1 Example1']:
        assert call(admin, 'GET', '/reports?search=' + search).json()['total'] >= 1
    for query, total in [('order_id=1', 1), ('status=APPROVED', 0), ('status=GENERATED', 2),
                          ('date_from=9999-01-01', 0), ('date_to=1900-01-01', 0)]:
        assert call(admin, 'GET', '/reports?' + query).json()['total'] == total
    assert call(admin, 'GET', '/lab-orders/1/reports').json()['total'] == 1
    assert call(admin, 'GET', '/lab-orders/999/reports').status_code == 404
    for query in ['page=0', 'page_size=101', 'status=BAD', 'date_from=2026-09-17&date_to=2026-09-16']:
        assert call(admin, 'GET', '/reports?' + query).status_code == 422


def test_signing_and_approval_lifecycle(admin):
    before = generated(admin)
    assert approve(admin).status_code == 409
    link = assigned(admin)
    assert link['signed_at'] is None
    assert approve(admin).status_code == 409
    assert call(admin, 'POST', '/reports/1/signatories', {'signatory_id': 1, 'signatory_type': 'MEDICAL_TECHNOLOGIST'}).status_code == 409
    signed = sign(admin)
    assert signed.status_code == 200 and signed.json()['signed_at']
    assert sign(admin).status_code == 409
    row = approve(admin)
    assert row.status_code == 200, row.text
    row = row.json()
    assert row['report_status'] == 'APPROVED' and row['approved_by_user_id'] == 1 and row['approved_at']
    assert row['patient_snapshot'] == before['patient_snapshot'] and row['result_snapshots'] == before['result_snapshots']
    assert all(row[key] is None for key in ['released_at', 'released_by_user_id', 'revoked_at', 'revoked_by_user_id', 'pdf_path'])
    assert approve(admin).status_code == sign(admin).status_code == 409
    assert call(admin, 'POST', '/reports/1/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'}).status_code == 409
    assert call(admin, 'GET', '/reports/1/signatories').json() == row['signatories']
    with admin.factory() as db:
        assert count(db, ReportVerification) == 0


@pytest.mark.parametrize('case', ['other_staff', 'unlinked', 'inactive_profile', 'inactive_staff', 'wrong_report', 'unknown_assignment'])
def test_identity_bound_signing(admin, case):
    generated(admin)
    assigned(admin, staff_id=2 if case == 'other_staff' else 1)
    with admin.factory.begin() as db:
        if case == 'unlinked':
            db.execute(delete(StaffAccountLink))
        elif case == 'inactive_profile':
            db.get(Signatory, 1).is_active = False
        elif case == 'inactive_staff':
            db.get(Staff, 1).is_active = False
    if case == 'wrong_report':
        row = completed(admin)
        generate(admin, row['order_id'])
    response = sign(admin, assignment_id=999 if case == 'unknown_assignment' else 1, report_id=2 if case == 'wrong_report' else 1)
    assert response.status_code == (403 if case in {'other_staff', 'unlinked'} else 404 if case in {'wrong_report', 'unknown_assignment'} else 409)
    assert report(admin)['signatories'][0]['signed_at'] is None


@pytest.mark.parametrize('case', ['unknown', 'inactive_profile', 'inactive_staff', 'invalid_type'])
def test_assignment_invalid_profile(admin, case):
    generated(admin)
    profile = create(admin, '/signatories', {'staff_id': 1})
    with admin.factory.begin() as db:
        if case == 'inactive_profile':
            db.get(Signatory, 1).is_active = False
        if case == 'inactive_staff':
            db.get(Staff, 1).is_active = False
    response = call(admin, 'POST', '/reports/1/signatories', {'signatory_id': 999 if case == 'unknown' else profile['signatory_id'],
        'signatory_type': 'DOCTOR' if case == 'invalid_type' else 'PATHOLOGIST'})
    assert response.status_code == (422 if case in {'unknown', 'invalid_type'} else 409)


def test_all_assigned_must_sign_and_approver_need_not_be_signatory(admin):
    generated(admin)
    assigned(admin)
    sign(admin)
    second = assigned(admin, signatory_type='PATHOLOGIST')
    assert approve(admin).status_code == 409
    assert sign(admin, second['report_signatory_id']).status_code == 200
    with admin.factory.begin() as db:
        db.execute(delete(StaffAccountLink))
    assert approve(admin).status_code == 200


@pytest.mark.parametrize('case', ['missing_patient', 'empty_lines', 'draft', 'reviewed', 'duplicate_line', 'wrong_source',
    'sort', 'age', 'value', 'flag', 'empty_name', 'missing_provenance', 'cancelled_order'])
def test_approval_rechecks_snapshot_integrity(admin, case):
    generated(admin)
    assigned(admin)
    sign(admin)
    with admin.factory.begin() as db:
        line = db.get(ReportResultItem, 1)
        if case == 'missing_patient':
            db.execute(delete(ReportPatientSnapshot))
        elif case == 'empty_lines':
            db.execute(delete(ReportResultItem))
        elif case in {'draft', 'reviewed'}:
            db.get(LabResultItem, 1).status = case.upper()
        elif case == 'duplicate_line':
            db.add(ReportResultItem(report_id=1, result_item_id=1, test_name_snapshot='Synthetic', result_value_snapshot='12.60', sort_order=2))
        elif case == 'wrong_source':
            db.add(LabResultItem(result_item_id=2, order_item_id=1, result_value='12', status='DRAFT', encoded_by_user_id=1, encoded_at=utc_now()))
            db.flush()
            line.result_item_id = 2
        elif case == 'sort':
            line.sort_order = 3
        elif case == 'age':
            db.get(ReportPatientSnapshot, 1).age_at_report = -1
        elif case == 'value':
            line.result_value_snapshot = '99'
        elif case == 'flag':
            line.flag_snapshot = 'HIGH'
        elif case == 'empty_name':
            line.test_name_snapshot = ''
        elif case == 'missing_provenance':
            db.get(LabResultItem, 1).verified_at = None
        elif case == 'cancelled_order':
            db.get(LabOrder, 1).status = 'CANCELLED'
    assert approve(admin).status_code == 409
    assert report(admin)['report_status'] == 'GENERATED'


def test_historical_configuration_guards_and_no_snapshot_crud(admin):
    create(admin, '/report-templates', {'template_code': 'T', 'template_name': 'Synthetic'})
    generated(admin, template_id=1)
    assigned(admin)
    sign(admin)
    # Signing already freezes identity and signature metadata, before approval.
    assert call(admin, 'PATCH', '/signatories/1', {'staff_id': 2}).status_code == 409
    assert approve(admin).status_code == 200
    for payload in [{'header_title': 'Rewrite'}, {'panel_id': 1}, {'template_code': 'Rewrite'}, {'clinical_note': 'Rewrite'}]:
        assert call(admin, 'PATCH', '/report-templates/1', payload).status_code == 409
    for payload in [{'staff_id': 2}, {'license_number_snapshot': 'Rewrite'}, {'signature_image_path': '/rewrite'}]:
        assert call(admin, 'PATCH', '/signatories/1', payload).status_code == 409
    for path in ['/signatories/1', '/report-templates/1']:
        assert call(admin, 'PATCH', path, {'is_active': False}).status_code == 200
        assert call(admin, 'DELETE', path).status_code == 405
    for path in ['/report-result-items/1', '/report-patient-snapshot/1']:
        assert call(admin, 'PATCH', path, {}).status_code == 404
    for path in ['/reports/1/release', '/reports/1/revoke']:
        assert call(admin, 'POST', path).status_code == 404


@pytest.mark.parametrize('action,target', [('generate', 'lab_report'), ('generate', 'report_patient_snapshot'),
    ('generate', 'report_result_item'), ('generate', 'audit_log'), ('generate', 'commit'),
    ('assign', 'audit_log'), ('assign', 'commit'), ('sign', 'audit_log'), ('sign', 'commit'),
    ('approve', 'audit_log'), ('approve', 'commit')])
def test_atomic_rollback(admin, action, target):
    completed(admin)
    if action != 'generate':
        assert generate(admin).status_code == 201
    if action in {'sign', 'approve'}:
        assigned(admin)
    if action == 'approve':
        sign(admin)
    if action == 'assign':
        create(admin, '/signatories', {'staff_id': 1})
    before = report(admin) if action != 'generate' else None
    with admin.factory() as db:
        audits = count(db, AuditLog)
    def fail(*args):
        if target == 'commit' or args[2].startswith('INSERT INTO ' + target + ' '):
            raise SQLAlchemyError('private laboratory content')
    host, hook = (admin.factory, 'before_commit') if target == 'commit' else (admin.engine, 'before_cursor_execute')
    event.listen(host, hook, fail)
    try:
        if action == 'generate':
            response = generate(admin)
        elif action == 'assign':
            response = call(admin, 'POST', '/reports/1/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'})
        else:
            response = sign(admin) if action == 'sign' else approve(admin)
        assert response.status_code == 503 and 'private' not in response.text
    finally:
        event.remove(host, hook, fail)
    if before:
        assert report(admin) == before
    with admin.factory() as db:
        assert count(db, AuditLog) == audits
        if action == 'generate':
            assert count(db, LabReport) == count(db, ReportPatientSnapshot) == count(db, ReportResultItem) == 0


def test_audit_actions_privacy_permissions_and_openapi(admin):
    call(admin, 'PATCH', '/facility-profile', {'address': 'Private address'})
    create(admin, '/report-templates', {'template_code': 'T', 'template_name': 'Private template'})
    call(admin, 'PATCH', '/report-templates/1', {'footer_note': 'Private footer'})
    generated(admin, template_id=1)
    assigned(admin)
    call(admin, 'PATCH', '/signatories/1', {'signature_image_path': '/private/signature'})
    sign(admin)
    approve(admin)
    bootstrap_permissions.main()
    bootstrap_permissions.main()
    with admin.factory() as db:
        assert ensure_permissions(db) == []
        logs = list(db.scalars(select(AuditLog)))
        assert {row.action for row in logs} >= {'FACILITY_PROFILE_UPDATE', 'REPORT_TEMPLATE_CREATE', 'REPORT_TEMPLATE_UPDATE',
            'SIGNATORY_CREATE', 'SIGNATORY_UPDATE', 'REPORT_GENERATE', 'REPORT_SIGNATORY_ASSIGN', 'REPORT_SIGN', 'REPORT_APPROVE'}
        content = json.dumps([{'old': row.old_value, 'new': row.new_value} for row in logs])
        for secret in ['Private address', 'Private footer', 'SYNTH-LIC', '/private/signature', '12.60', 'Synthetic1', PASSWORD,
                       *admin.client.cookies.values()]:
            assert secret not in content
    from app.main import app
    spec = app.openapi()
    operations = [(path, method) for path, methods in spec['paths'].items() for method, operation in methods.items()
                  if 'Official Reports' in operation.get('tags', [])]
    assert len(operations) == 19
    assert all(spec['paths'][path][method]['security'] for path, method in operations)
    assert 'password_hash' not in json.dumps(spec)


@pytest.mark.parametrize('field', ['report_code', 'facility_id', 'version_no', 'supersedes_report_id', 'report_status',
    'generated_by_user_id', 'generated_at', 'approved_at', 'released_at', 'pdf_path'])
def test_report_server_fields_not_writable(admin, field):
    assert generate(admin, **{field: 'private-input'}).status_code == 422


def test_name_and_full_years_helpers():
    assert printable_name(SimpleNamespace(first_name=' a  b ', middle_name='', last_name='McDONALD', suffix=None)) == 'a b McDONALD'
    assert full_years(date(2020, 2, 29), date(2021, 2, 28)) == 0
    assert full_years(date(2020, 2, 29), date(2021, 3, 1)) == 1
    assert full_years(None, date(2026, 1, 1)) is None


@pytest.mark.parametrize('case', ['panel', 'lifecycle', 'future_birth', 'range_other_test'])
def test_additional_structural_conflicts(admin, case):
    if case in {'future_birth', 'range_other_test'}:
        completed(admin)
        with admin.factory.begin() as db:
            if case == 'future_birth':
                db.get(Patient, 1).birth_date = date(9999, 1, 1)
            else:
                db.get(ReferenceRange, 1).test_id = 2
        assert generate(admin).status_code == 409
        with admin.factory() as db:
            assert count(db, LabReport) == 0
    else:
        generated(admin)
        assigned(admin)
        sign(admin)
        with admin.factory.begin() as db:
            if case == 'panel':
                db.get(ReportResultItem, 1).panel_id_snapshot = 1
            else:
                db.get(LabReport, 1).released_at = utc_now()
        assert approve(admin).status_code == 409


def test_report_code_unique_constraint_rolls_back_collision(admin, monkeypatch):
    monkeypatch.setattr(service, 'secrets', SimpleNamespace(token_hex=lambda size: '0123456789ABCDEF'))
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 9, 16))
    generated(admin)
    second = completed(admin)
    assert generate(admin, second['order_id']).status_code == 409
    with admin.factory() as db:
        assert count(db, LabReport) == count(db, ReportPatientSnapshot) == count(db, ReportResultItem) == 1


@pytest.mark.parametrize('state', ['APPROVED', 'RELEASED', 'REVOKED'])
def test_existing_non_generated_reports_reject_every_mutation(admin, state):
    generated(admin)
    assigned(admin)
    with admin.factory.begin() as db:
        db.get(LabReport, 1).report_status = state
    before = report(admin)
    assert approve(admin).status_code == sign(admin).status_code == generate(admin).status_code == 409
    assert call(admin, 'POST', '/reports/1/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'}).status_code == 409
    assert report(admin) == before


def test_approval_uses_historical_snapshots_after_live_master_edits(admin):
    generated(admin)
    assigned(admin)
    sign(admin)
    before = report(admin)
    with admin.factory.begin() as db:
        db.get(Patient, 1).first_name = 'Edited'
        db.get(Patient, 1).birth_date = None
        db.get(Catalog, 1).test_name = 'Edited'
        db.get(ReferenceRange, 1).normal_low = Decimal('1')
    response = approve(admin)
    assert response.status_code == 200, response.text
    assert response.json()['patient_snapshot'] == before['patient_snapshot']
    assert response.json()['result_snapshots'] == before['result_snapshots']
