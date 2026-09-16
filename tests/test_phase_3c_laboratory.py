"""Synthetic HTTPS API, resolver, audit and rollback checks for Phase 3C."""

from datetime import date
from decimal import Decimal
import json

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from app.api import laboratory
from app.cli import bootstrap_permissions
from app.models import (
    AuditLog, LabDepartment, PanelSection, Permission, ReferenceRange,
    Role, RolePermission, SampleType, TestCatalog as Catalog,
    TestPanel as Panel, UserRole,
)
from app.services import laboratory_service as service
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from test_phase_3a_authentication_rbac import env, password_hash, login, csrf

BASE = '/api/v1/lab'


@pytest.fixture
def lab_api(env, monkeypatch):
    env.app.include_router(laboratory.router, prefix='/api/v1')
    monkeypatch.setattr(bootstrap_permissions, 'SessionLocal', env.factory)
    with env.factory.begin() as db:
        ensure_permissions(db)
        db.add(Role(role_id=2, role_code='SYSTEM_ADMIN', role_name='Administrator', is_active=True))
        db.add(LabDepartment(department_id=1, department_code='SEED', department_name='Synthetic department'))
        db.add_all(SampleType(sample_type_id=i, sample_name=f'Seed specimen {i}') for i in (1, 2))
        db.flush()
        db.add_all(Catalog(test_id=i, test_code=f'SEED{i}', test_name=f'Seed test {i}',
                           department_id=1, result_type='NUMERIC') for i in (1, 2))
        db.add_all(Panel(panel_id=i, panel_code=f'SEED{i}', panel_name=f'Seed panel {i}') for i in (1, 2))
        db.flush()
        db.add_all(PanelSection(section_id=i, panel_id=i, section_name=f'Seed section {i}', sort_order=5) for i in (1, 2))
    return env


@pytest.fixture
def lab_admin(lab_api):
    with lab_api.factory.begin() as db:
        db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    assert login(lab_api).status_code == 200
    return lab_api


def call(api, method, path, body=None):
    return api.client.request(method, BASE + path, json=body, headers=csrf(api))


def create(api, path, body):
    result = call(api, 'POST', path, body)
    assert result.status_code == 201, result.text
    return result.json()


RESOURCES = [
    ('departments', 'department_id', 'department_code', 'department_name', 'LAB_DEPARTMENT',
     {'department_code': 'SYNTH', 'department_name': ' Synthetic item '}),
    ('sample-types', 'sample_type_id', 'sample_name', 'sample_name', 'SAMPLE_TYPE',
     {'sample_name': ' Synthetic specimen '}),
    ('tests', 'test_id', 'test_code', 'test_name', 'TEST',
     {'test_code': 'SYNTH', 'test_name': ' Synthetic item ', 'department_id': 1, 'result_type': 'NUMERIC'}),
    ('panels', 'panel_id', 'panel_code', 'panel_name', 'PANEL',
     {'panel_code': 'SYNTH', 'panel_name': ' Synthetic item '}),
]
PERMISSIONS = ['LAB_DEPARTMENT_MANAGE', 'SAMPLE_TYPE_MANAGE', 'TEST_CATALOG_MANAGE', 'TEST_PANEL_MANAGE']
ENDPOINTS = []
for (path, key, code, name, action, body), permission in zip(RESOURCES, PERMISSIONS):
    ENDPOINTS += [('POST', '/' + path, body, permission), ('GET', '/' + path, None, 'LAB_MASTER_READ'),
                  ('GET', f'/{path}/999', None, 'LAB_MASTER_READ'), ('PATCH', f'/{path}/999', {}, permission)]
ENDPOINTS += [
    ('GET', '/tests/1/sample-types', None, 'LAB_MASTER_READ'),
    ('PUT', '/tests/1/sample-types', {'sample_types': []}, 'TEST_CATALOG_MANAGE'),
    ('GET', '/panels/1/tests', None, 'LAB_MASTER_READ'),
    ('PUT', '/panels/1/tests', {'tests': []}, 'TEST_PANEL_MANAGE'),
    ('GET', '/panels/1/sections', None, 'LAB_MASTER_READ'),
    ('POST', '/panels/1/sections', {'section_name': 'Synthetic', 'sort_order': 1}, 'TEST_PANEL_MANAGE'),
    ('PATCH', '/panels/1/sections/1', {}, 'TEST_PANEL_MANAGE'),
    ('GET', '/tests/1/reference-range?sex=M&age_years=32&as_of_date=2026-09-15', None, 'LAB_MASTER_READ'),
]
for path, body, permission in [('reference-ranges', {'sex': 'ANY'}, 'REFERENCE_RANGE_MANAGE'),
                              ('interpretation-rules', {'flag': 'NORMAL'}, 'INTERPRETATION_RULE_MANAGE')]:
    ENDPOINTS += [('POST', '/tests/1/' + path, body, permission),
                  ('GET', '/tests/1/' + path, None, 'LAB_MASTER_READ'),
                  ('GET', '/' + path + '/999', None, 'LAB_MASTER_READ'),
                  ('PATCH', '/' + path + '/999', {}, permission)]


@pytest.mark.parametrize('method,path,body,permission', ENDPOINTS)
def test_all_routes_session_permission_csrf(lab_api, method, path, body, permission):
    assert lab_api.client.request(method, BASE + path, json=body).status_code == 401
    assert login(lab_api).status_code == 200
    assert call(lab_api, method, path, body).status_code == 403
    with lab_api.factory.begin() as db:
        pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == permission))
        db.add(RolePermission(role_id=1, permission_id=pid))
    if method != 'GET':
        assert lab_api.client.request(method, BASE + path, json=body).status_code == 403
    response = call(lab_api, method, path, body)
    assert response.status_code in {200, 201, 404}, response.text
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('path,key,code,name,action,body', RESOURCES)
def test_master_lifecycle_duplicate_pagination_search_audit(lab_admin, path, key, code, name, action, body):
    first = create(lab_admin, '/' + path, body)
    assert first[name] == body[name].strip()
    identifier = first[key]
    assert call(lab_admin, 'GET', f'/{path}/{identifier}').json()[name] == first[name]
    assert call(lab_admin, 'POST', '/' + path, body).status_code == 409
    second = create(lab_admin, '/' + path, {**body, code: 'SYNTH-SECOND'})
    assert call(lab_admin, 'PATCH', f'/{path}/{second[key]}', {code: first[code]}).status_code == 409
    result = call(lab_admin, 'GET', f'/{path}?search=synth&page_size=1&page=2').json()
    # The department seed's name also includes Synthetic; use code-specific search below.
    assert result['total'] >= 2 and result['page'] == 2 and result['page_size'] == 1
    assert len(result['items']) == 1
    assert call(lab_admin, 'GET', f'/{path}?search=SYNTH-SECOND').json()['total'] == 1
    assert call(lab_admin, 'GET', f'/{path}?search=%25').json()['total'] == 0
    assert call(lab_admin, 'GET', f'/{path}?page=999').json()['items'] == []
    for query in ('page=0', 'page_size=101', 'page_size=0', 'is_active=bad'):
        assert call(lab_admin, 'GET', f'/{path}?{query}').status_code == 422
    response = call(lab_admin, 'PATCH', f'/{path}/{identifier}', {name: 'Revised synthetic', 'is_active': False})
    assert response.status_code == 200 and response.json()['is_active'] is False
    assert call(lab_admin, 'GET', f'/{path}?is_active=false').json()['total'] == 1
    assert call(lab_admin, 'PATCH', f'/{path}/{identifier}', {}).json()['is_active'] is False
    assert call(lab_admin, 'DELETE', f'/{path}/{identifier}').status_code == 405
    assert call(lab_admin, 'GET', f'/{path}/999').status_code == 404
    with lab_admin.factory() as db:
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action.in_([action + '_CREATE', action + '_UPDATE']))))
        assert len(logs) == 4
        assert logs[-2].new_value == {'changed_fields': sorted([name, 'is_active'])}
        assert all(row.user_id == 1 and row.ip_address == '192.0.2.10' and row.created_at for row in logs)
        assert 'Revised synthetic' not in json.dumps([row.new_value for row in logs])


@pytest.mark.parametrize('path,key,code,name,action,body', RESOURCES)
def test_allowlists_required_fields_lengths(lab_admin, path, key, code, name, action, body):
    for field in (key, 'password', 'age', 'created_at'):
        assert call(lab_admin, 'POST', '/' + path, {**body, field: 'secret'}).status_code == 422
        response = call(lab_admin, 'PATCH', f'/{path}/1', {field: 'secret'})
        assert response.status_code == 422 and 'secret' not in response.text
    for field in (code, name, 'is_active'):
        assert call(lab_admin, 'PATCH', f'/{path}/1', {field: None}).status_code == 422
    assert call(lab_admin, 'POST', '/' + path, {**body, name: ' '}).status_code == 422
    assert call(lab_admin, 'POST', '/' + path, {**body, name: 'x' * 151}).status_code == 422
    assert call(lab_admin, 'PATCH', f'/{path}/0', {}).status_code == 422


@pytest.mark.parametrize('result_type', ['NUMERIC', 'TEXT', 'POS_NEG', 'numeric', 'TEXT ', 'POSITIVE', ''])
def test_result_type_exact_and_test_filters(lab_admin, result_type):
    response = call(lab_admin, 'POST', '/tests', {'test_code': 'T', 'test_name': 'Synthetic',
                    'department_id': 1, 'result_type': result_type})
    if result_type not in {'NUMERIC', 'TEXT', 'POS_NEG'}:
        assert response.status_code == 422
    else:
        assert response.status_code == 201
        result = call(lab_admin, 'GET', f'/tests?result_type={result_type}&department_id=1&search=T&is_active=true').json()
        assert any(row['test_id'] == response.json()['test_id'] for row in result['items'])
        assert call(lab_admin, 'GET', '/tests?department_id=999').json()['total'] == 0
    assert call(lab_admin, 'GET', '/tests?result_type=numeric').status_code == 422


def test_department_relationships_and_nullable_patch(lab_admin):
    body = {'test_code': 'NEW', 'test_name': 'Synthetic', 'department_id': 999, 'result_type': 'TEXT'}
    assert call(lab_admin, 'POST', '/tests', body).status_code == 422
    assert call(lab_admin, 'PATCH', '/tests/1', {'department_id': 999}).status_code == 422
    assert call(lab_admin, 'POST', '/panels', {'panel_code': 'NEW', 'panel_name': 'Synthetic', 'department_id': 999}).status_code == 422
    assert call(lab_admin, 'PATCH', '/panels/1', {'department_id': 999}).status_code == 422
    assert call(lab_admin, 'PATCH', '/panels/1', {'department_id': 1}).status_code == 200
    assert call(lab_admin, 'GET', '/panels?department_id=1').json()['total'] == 1
    assert call(lab_admin, 'PATCH', '/panels/1', {'department_id': None}).json()['department_id'] is None
    assert call(lab_admin, 'PATCH', '/departments/1', {'is_active': False}).status_code == 200
    assert call(lab_admin, 'POST', '/tests', {**body, 'department_id': 1}).status_code == 409
    inactive = create(lab_admin, '/tests', {**body, 'department_id': 1, 'is_active': False})
    assert call(lab_admin, 'PATCH', f'/tests/{inactive["test_id"]}', {'is_active': True}).status_code == 409
    assert call(lab_admin, 'PATCH', '/tests/1', {'test_name': 'Updated retired department test'}).status_code == 200
    assert call(lab_admin, 'PATCH', '/tests/1', {'default_unit': None, 'is_active': False}).status_code == 200


def test_sample_replacement_and_detail(lab_admin):
    path = '/tests/1/sample-types'
    one = [{'sample_type_id': 1, 'is_default': True}]
    assert call(lab_admin, 'PUT', path, {'sample_types': one}).status_code == 200
    multiple = one + [{'sample_type_id': 2, 'is_default': False}]
    response = call(lab_admin, 'PUT', path, {'sample_types': multiple})
    assert response.status_code == 200 and len(response.json()) == 2
    assert call(lab_admin, 'GET', path).json() == response.json()
    detail = call(lab_admin, 'GET', '/tests/1').json()
    assert detail['department']['department_id'] == 1
    assert detail['sample_types'] == response.json()
    assert '_sa_instance_state' not in json.dumps(detail)
    for invalid in [one * 2, [dict(item, is_default=True) for item in multiple],
                    one + [{'sample_type_id': 999, 'is_default': False}]]:
        assert call(lab_admin, 'PUT', path, {'sample_types': invalid}).status_code == 422
        assert call(lab_admin, 'GET', path).json() == response.json()
    assert call(lab_admin, 'PUT', '/tests/999/sample-types', {'sample_types': []}).status_code == 404
    assert call(lab_admin, 'PUT', path, {'sample_types': []}).json() == []
    assert call(lab_admin, 'GET', path).json() == []


def test_panel_sections_composition_order_and_cross_panel(lab_admin):
    a = create(lab_admin, '/panels/1/sections', {'section_name': 'Synthetic A', 'sort_order': 1})
    b = create(lab_admin, '/panels/1/sections', {'section_name': 'Synthetic B', 'sort_order': 1})
    assert call(lab_admin, 'PATCH', f'/panels/2/sections/{a["section_id"]}', {'section_name': 'Corrupt'}).status_code == 404
    assert call(lab_admin, 'PATCH', '/panels/1/sections/999', {}).status_code == 404
    assert call(lab_admin, 'POST', '/panels/999/sections', {'section_name': 'X', 'sort_order': 1}).status_code == 404
    ordered = call(lab_admin, 'GET', '/panels/1/sections').json()
    assert [row['section_id'] for row in ordered] == [a['section_id'], b['section_id'], 1]
    tests = [{'test_id': 1, 'section_id': 1, 'sort_order': -1, 'is_required': True},
             {'test_id': 2, 'section_id': a['section_id'], 'sort_order': 99, 'is_required': False}]
    response = call(lab_admin, 'PUT', '/panels/1/tests', {'tests': tests})
    assert response.status_code == 200 and [row['test_id'] for row in response.json()] == [2, 1]
    assert call(lab_admin, 'GET', '/panels/1').json()['tests'] == response.json()
    assert call(lab_admin, 'GET', '/panels/1').json()['sections'] == ordered
    for invalid in [tests + tests[:1], [dict(tests[0], test_id=999)],
                    [dict(tests[0], section_id=2)], [dict(tests[0], section_id=999)]]:
        assert call(lab_admin, 'PUT', '/panels/1/tests', {'tests': invalid}).status_code == 422
        assert call(lab_admin, 'GET', '/panels/1/tests').json() == response.json()
    tests[0]['section_id'] = None
    assert [row['test_id'] for row in call(lab_admin, 'PUT', '/panels/1/tests', {'tests': tests}).json()] == [1, 2]
    assert call(lab_admin, 'PATCH', f'/panels/1/sections/{a["section_id"]}', {'is_active': False, 'sort_order': -5}).status_code == 200
    assert call(lab_admin, 'GET', '/panels/1/sections').json()[0]['is_active'] is False
    assert call(lab_admin, 'DELETE', '/panels/1/sections/1').status_code == 405
    assert call(lab_admin, 'PUT', '/panels/1/tests', {'tests': []}).json() == []


@pytest.mark.parametrize('path,body,table', [
    ('/tests/1/sample-types', {'sample_types': [{'sample_type_id': 1, 'is_default': True}]}, 'test_sample_type'),
    ('/panels/1/tests', {'tests': [{'test_id': 1, 'section_id': None, 'sort_order': 1, 'is_required': True}]}, 'panel_test'),
])
@pytest.mark.parametrize('failure_at', ['insert', 'audit'])
def test_replacements_rollback_after_deletion(lab_admin, path, body, table, failure_at):
    first = call(lab_admin, 'PUT', path, body)
    assert first.status_code == 200
    target = table if failure_at == 'insert' else 'audit_log'
    def fail(connection, cursor, statement, params, context, executemany):
        if statement.startswith('INSERT INTO ' + target + ' '):
            raise SQLAlchemyError('private database failure')
    event.listen(lab_admin.engine, 'before_cursor_execute', fail)
    try:
        response = call(lab_admin, 'PUT', path, body)
        assert response.status_code == 503 and 'private' not in response.text
    finally:
        event.remove(lab_admin.engine, 'before_cursor_execute', fail)
    assert call(lab_admin, 'GET', path).json() == first.json()
    with lab_admin.factory() as db:
        action = 'TEST_SAMPLE_TYPES_UPDATE' if table == 'test_sample_type' else 'PANEL_TESTS_UPDATE'
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == action)))) == 1


RANGE = {'sex': 'ANY', 'age_min': '0.00', 'age_max': '99.99',
         'normal_low': '1.123', 'normal_high': '9.987', 'critical_low': '-1.001', 'critical_high': '12.345',
         'unit': 'synthetic-unit', 'effective_from': '2026-01-01', 'effective_to': '2026-12-31'}


@pytest.mark.parametrize('change', [
    {'sex': 'Other'}, {'sex': 'm'}, {'sex': 'ANY '}, {'age_min': '-0.01'}, {'age_max': '-1'},
    {'age_min': '30', 'age_max': '20'}, {'normal_low': '11'}, {'critical_low': '2'},
    {'critical_high': '5'}, {'effective_to': '2025-01-01'}, {'normal_low': '1.1234'},
    {'normal_low': '1000000000'}, {'normal_low': 'NaN'}, {'normal_high': 'Infinity'},
    {'age_max': '10000'}, {'age_min': '0.001'}, {'unit': 'x' * 51}, {'qualitative_normal': 'x' * 81},
])
def test_range_invalid_input(lab_admin, change):
    assert call(lab_admin, 'POST', '/tests/1/reference-ranges', {**RANGE, **change}).status_code == 422


def test_range_decimal_crud_merged_patch(lab_admin):
    row = create(lab_admin, '/tests/1/reference-ranges', RANGE)
    path = f'/reference-ranges/{row["range_id"]}'
    assert row['normal_low'] == '1.123' and row['critical_low'] == '-1.001'
    with lab_admin.factory() as db:
        value = db.get(ReferenceRange, row['range_id']).normal_high
        assert isinstance(value, Decimal) and value == Decimal('9.987')
    assert call(lab_admin, 'GET', path).json() == row
    assert call(lab_admin, 'GET', '/tests/1/reference-ranges?page_size=1').json()['items'] == [row]
    for change in [{'age_min': '100'}, {'normal_low': '11'}, {'critical_low': '2'},
                   {'effective_from': '2027-01-01'}, {'test_id': 2}, {'range_id': 2}, {'sex': None}]:
        assert call(lab_admin, 'PATCH', path, change).status_code == 422
        assert call(lab_admin, 'GET', path).json() == row
    assert call(lab_admin, 'PATCH', path, {'age_min': None, 'unit': None, 'is_active': False}).status_code == 200
    assert call(lab_admin, 'GET', '/tests/1/reference-ranges?is_active=true').json()['total'] == 0
    assert call(lab_admin, 'GET', '/tests/1/reference-ranges?is_active=false').json()['total'] == 1
    assert call(lab_admin, 'DELETE', path).status_code == 405


@pytest.mark.parametrize('kind', ['NUMERIC', 'TEXT', 'POS_NEG'])
def test_numeric_and_qualitative_fields_optional(lab_admin, kind):
    assert call(lab_admin, 'PATCH', '/tests/1', {'result_type': kind}).status_code == 200
    body = {'sex': 'ANY'} if kind == 'NUMERIC' else {'sex': 'ANY', 'qualitative_normal': 'Synthetic expected value'}
    assert create(lab_admin, '/tests/1/reference-ranges', body)['normal_low'] is None


@pytest.mark.parametrize('change,expected', [
    ({}, 409), ({'age_min': '99.99', 'age_max': None}, 409),
    ({'age_min': '100.00', 'age_max': None}, 201),
    ({'effective_from': '2026-12-31', 'effective_to': None}, 409),
    ({'effective_from': '2027-01-01', 'effective_to': None}, 201),
    ({'age_min': None, 'age_max': None, 'effective_from': None, 'effective_to': None}, 409),
    ({'sex': 'M'}, 201), ({'sex': 'F'}, 201), ({'is_active': False}, 201),
])
def test_overlap_policy_inclusive_same_sex(lab_admin, change, expected):
    create(lab_admin, '/tests/1/reference-ranges', RANGE)
    assert call(lab_admin, 'POST', '/tests/1/reference-ranges', {**RANGE, **change}).status_code == expected
    assert call(lab_admin, 'POST', '/tests/2/reference-ranges', RANGE).status_code == 201


def test_overlap_patch_activation_and_sex_change(lab_admin):
    first = create(lab_admin, '/tests/1/reference-ranges', RANGE)
    inactive = create(lab_admin, '/tests/1/reference-ranges', {**RANGE, 'is_active': False})
    path = f'/reference-ranges/{inactive["range_id"]}'
    assert call(lab_admin, 'PATCH', path, {'is_active': True}).status_code == 409
    assert call(lab_admin, 'PATCH', path, {'normal_low': '1.124'}).status_code == 200
    male = create(lab_admin, '/tests/1/reference-ranges', {**RANGE, 'sex': 'M'})
    assert call(lab_admin, 'PATCH', f'/reference-ranges/{male["range_id"]}', {'sex': 'ANY'}).status_code == 409
    assert call(lab_admin, 'PATCH', f'/reference-ranges/{first["range_id"]}', {'normal_low': '1.125'}).status_code == 200
    later = create(lab_admin, '/tests/1/reference-ranges', {**RANGE, 'effective_from': '2027-01-01', 'effective_to': None})
    assert call(lab_admin, 'PATCH', f'/reference-ranges/{later["range_id"]}', {'effective_from': '2026-01-01'}).status_code == 409


def resolve(api, sex='M', age='32', day='2026-09-15', test_id=1):
    return call(api, 'GET', f'/tests/{test_id}/reference-range?sex={sex}&age_years={age}&as_of_date={day}')


@pytest.mark.parametrize('sex,expected', [('M', 'M'), ('F', 'F'), ('Other', 'ANY')])
def test_resolver_exact_precedence(lab_admin, sex, expected):
    for category in ('ANY', 'M', 'F'):
        create(lab_admin, '/tests/1/reference-ranges', {**RANGE, 'sex': category})
    assert resolve(lab_admin, sex).json()['sex'] == expected


@pytest.mark.parametrize('bounds,age,day,match', [
    ({}, '0', '2026-01-01', True), ({}, '99.99', '2026-12-31', True),
    ({}, '99.991', '2026-09-15', False), ({}, '32', '2025-12-31', False),
    ({}, '32', '2027-01-01', False),
    ({'age_min': None, 'age_max': '10'}, '0', '2026-09-15', True),
    ({'age_min': '100', 'age_max': None}, '200', '2026-09-15', True),
    ({'effective_from': None}, '32', '1900-01-01', True),
    ({'effective_to': None}, '32', '2100-01-01', True),
    ({'age_min': None, 'age_max': None, 'effective_from': None, 'effective_to': None}, '32.123456', '2026-09-15', True),
    ({'is_active': False}, '32', '2026-09-15', False),
])
def test_resolver_boundaries_nulls_fallback(lab_admin, bounds, age, day, match):
    row = create(lab_admin, '/tests/1/reference-ranges', {**RANGE, **bounds})
    response = resolve(lab_admin, age=age, day=day)
    assert response.status_code == (200 if match else 404)
    if match:
        assert response.json()['range_id'] == row['range_id']
    assert resolve(lab_admin, test_id=2).status_code == 404


def test_resolver_ignores_inapplicable_exact_and_no_patient_data(lab_admin):
    any_range = create(lab_admin, '/tests/1/reference-ranges', {'sex': 'ANY'})
    create(lab_admin, '/tests/1/reference-ranges', {**RANGE, 'sex': 'M', 'age_max': '1'})
    assert resolve(lab_admin).json()['range_id'] == any_range['range_id']
    assert resolve(lab_admin, sex='Other').json()['range_id'] == any_range['range_id']
    assert resolve(lab_admin, test_id=999).status_code == 404
    for kwargs in [{'sex': 'm'}, {'sex': 'ANY'}, {'age': '-1'}, {'age': 'NaN'}, {'day': 'bad'}]:
        assert resolve(lab_admin, **kwargs).status_code == 422
    with lab_admin.factory() as db:
        selected = service.resolve_reference_range(db, 1, 'Other', Decimal('32'), date(2026, 9, 15))
        assert selected.range_id == any_range['range_id']
        with pytest.raises(HTTPException) as exc:
            service.resolve_reference_range(db, 1, 'Unknown', Decimal('32'), date(2026, 9, 15))
        assert exc.value.status_code == 422
    assert 'patient' not in resolve(lab_admin).text
    assert call(lab_admin, 'GET', '/tests/1/reference-range?sex=M&age_years=32&as_of_date=2026-09-15&patient_id=1').status_code == 422


@pytest.mark.parametrize('sex', ['M', 'F', 'ANY'])
def test_resolver_legacy_ambiguity_controlled_and_logged(lab_admin, caplog, sex):
    with lab_admin.factory.begin() as db:
        # Existing ambiguous records can predate the new service invariant.
        db.add_all(ReferenceRange(test_id=1, sex=sex, is_active=True) for _ in range(2))
    response = resolve(lab_admin, sex='Other' if sex == 'ANY' else sex)
    assert response.status_code == 409
    assert 'Ambiguous reference range configuration' in caplog.text
    assert 'age_years' not in caplog.text and '2026-09-15' not in caplog.text
    with lab_admin.factory() as db:
        with pytest.raises(service.ReferenceRangeAmbiguityError):
            service.resolve_reference_range(db, 1, 'Other' if sex == 'ANY' else sex, Decimal('32'), date(2026, 9, 15))


def test_exact_range_outranks_ambiguous_legacy_fallback(lab_admin):
    with lab_admin.factory.begin() as db:
        db.add_all(ReferenceRange(test_id=1, sex='ANY', is_active=True) for _ in range(2))
    exact = create(lab_admin, '/tests/1/reference-ranges', {'sex': 'M'})
    assert resolve(lab_admin).json()['range_id'] == exact['range_id']


@pytest.mark.parametrize('flag', ['NORMAL', 'LOW', 'HIGH', 'CRITICAL_LOW', 'CRITICAL_HIGH', 'ABNORMAL', 'normal', 'HIGH ', 'DIAGNOSIS'])
def test_interpretation_rules(lab_admin, flag):
    body = {'flag': flag, 'interpretation_text': 'Synthetic approved general explanation.',
            'possible_causes': 'Synthetic reviewed context.', 'recommendation': 'Consult the laboratory for configuration questions.'}
    response = call(lab_admin, 'POST', '/tests/1/interpretation-rules', body)
    if flag not in {'NORMAL', 'LOW', 'HIGH', 'CRITICAL_LOW', 'CRITICAL_HIGH', 'ABNORMAL'}:
        assert response.status_code == 422
        return
    assert response.status_code == 201
    row = response.json()
    path = f'/interpretation-rules/{row["rule_id"]}'
    assert call(lab_admin, 'GET', path).json() == row
    assert call(lab_admin, 'POST', '/tests/1/interpretation-rules', body).status_code == 409
    assert call(lab_admin, 'GET', '/tests/1/interpretation-rules?page_size=1').json()['items'] == [row]
    assert call(lab_admin, 'PATCH', path, {'is_active': False, 'possible_causes': None}).json()['possible_causes'] is None
    assert call(lab_admin, 'POST', '/tests/1/interpretation-rules', body).status_code == 409
    assert call(lab_admin, 'GET', '/tests/1/interpretation-rules?is_active=false').json()['total'] == 1
    assert call(lab_admin, 'DELETE', path).status_code == 405
    for change in ({'flag': None}, {'test_id': 2}, {'diagnosis': 'secret'}, {'flag': 'low'}):
        assert call(lab_admin, 'PATCH', path, change).status_code == 422


def test_rule_patch_duplicate_and_parent_validation(lab_admin):
    create(lab_admin, '/tests/1/interpretation-rules', {'flag': 'LOW'})
    other = create(lab_admin, '/tests/1/interpretation-rules', {'flag': 'HIGH'})
    assert call(lab_admin, 'PATCH', f'/interpretation-rules/{other["rule_id"]}', {'flag': 'LOW'}).status_code == 409
    assert call(lab_admin, 'POST', '/tests/999/interpretation-rules', {'flag': 'NORMAL'}).status_code == 404
    assert call(lab_admin, 'POST', '/tests/999/reference-ranges', {'sex': 'ANY'}).status_code == 404
    for path in ['/tests/999/interpretation-rules', '/tests/999/reference-ranges', '/tests/999/sample-types',
                 '/panels/999/sections', '/panels/999/tests']:
        assert call(lab_admin, 'GET', path).status_code == 404


def test_all_audit_actions_and_idempotent_bootstrap(lab_admin):
    for path, key, code, name, action, body in RESOURCES:
        row = create(lab_admin, '/' + path, body)
        assert call(lab_admin, 'PATCH', f'/{path}/{row[key]}', {'is_active': False}).status_code == 200
    section = create(lab_admin, '/panels/1/sections', {'section_name': 'Synthetic section', 'sort_order': 1})
    call(lab_admin, 'PATCH', f'/panels/1/sections/{section["section_id"]}', {'is_active': False})
    call(lab_admin, 'PUT', '/panels/1/tests', {'tests': []})
    call(lab_admin, 'PUT', '/tests/1/sample-types', {'sample_types': []})
    for path, key, body in [('reference-ranges', 'range_id', {'sex': 'ANY'}),
                             ('interpretation-rules', 'rule_id', {'flag': 'NORMAL'})]:
        row = create(lab_admin, '/tests/1/' + path, body)
        call(lab_admin, 'PATCH', f'/{path}/{row[key]}', {'is_active': False})
    with lab_admin.factory() as db:
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action != 'AUTH_LOGIN')))
        actions = {row.action for row in logs}
        expected = {f'{prefix}_{suffix}' for prefix in ['LAB_DEPARTMENT', 'SAMPLE_TYPE', 'TEST', 'PANEL',
                    'PANEL_SECTION', 'REFERENCE_RANGE', 'INTERPRETATION_RULE'] for suffix in ['CREATE', 'UPDATE']}
        assert actions == expected | {'TEST_SAMPLE_TYPES_UPDATE', 'PANEL_TESTS_UPDATE'}
        assert all(row.record_id and row.user_id == 1 and row.created_at and row.old_value is None for row in logs)
        assert len(logs) == 16
    bootstrap_permissions.main()
    bootstrap_permissions.main()
    with lab_admin.factory.begin() as db:
        assert ensure_permissions(db) == []
        assert len(list(db.scalars(select(Permission).where(Permission.permission_code.in_(PERMISSIONS + [
            'LAB_MASTER_READ', 'REFERENCE_RANGE_MANAGE', 'INTERPRETATION_RULE_MANAGE']))))) == 7


def test_openapi_complete_and_scope():
    from app.main import app
    paths = app.openapi()['paths']
    # Phase 4A adds rejection reasons under /lab and a separate /lab-orders prefix.
    lab_paths = {path: methods for path, methods in paths.items()
                 if path.startswith(BASE + '/') and not path.startswith(BASE + '/rejection-reasons')}
    assert sum(len(methods) for methods in lab_paths.values()) == 32
    for path, methods in lab_paths.items():
        assert 'delete' not in methods
        assert not any(word in path for word in ('patients', 'orders', 'results', 'diagnosis', 'prescription'))
        for operation in methods.values():
            assert operation['security'] and operation['responses']['200' if '200' in operation['responses'] else '201']
    params = paths[BASE + '/tests/{test_id}/reference-range']['get']['parameters']
    assert {p['name'] for p in params} == {'test_id', 'sex', 'age_years', 'as_of_date'}
