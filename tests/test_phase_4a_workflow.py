"""Synthetic authenticated workflow, provenance, atomicity and privacy checks."""

from datetime import datetime
import json
import re

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import workflow
from app.cli import bootstrap_permissions
from app.models import (
    AuditLog, CodeSequence, LabOrder, LabOrderItem, OrderPanel, PanelTest, Patient,
    Permission, RejectionReason, RequestingPhysician, RolePermission, SampleType,
    Specimen, SpecimenOrderItem, SpecimenRejection, TestCatalog as Catalog,
    TestPanel as Panel, TestSampleType as SampleLink, UserRole,
)
from app.services import workflow_service as service
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from test_phase_3a_authentication_rbac import env, password_hash, login, csrf, count, PASSWORD
from test_phase_3c_laboratory import lab_api

BASE = '/api/v1'
ORDER = {'patient_id': 1, 'physician_id': 1, 'priority': 'ROUTINE', 'panel_ids': [1, 2], 'test_ids': [1]}
REASON = {'reason_code': 'CLOTTED', 'reason_name': 'Synthetic clotted specimen'}
REJECT = {'rejection_reason_id': 1, 'details': 'Synthetic details', 'recollection_required': True}


@pytest.fixture
def workflow_api(lab_api):
    lab_api.app.include_router(workflow.router, prefix=BASE)
    with lab_api.factory.begin() as db:
        if db.get(CodeSequence, 'REJECTION_REASON') is None:
            db.add(CodeSequence(sequence_key='REJECTION_REASON', prefix='REJ', current_value=0, padding=3))
        db.add_all(Patient(patient_id=i, patient_code=f'P-SYNTH-{i}', first_name=f'Synthetic{i}',
                           last_name=f'Example{i}', address='unrelated-address', email='private@example.invalid') for i in (1, 2))
        db.add_all(RequestingPhysician(physician_id=i, first_name='Synthetic', last_name='Physician', is_active=i == 1)
                   for i in (1, 2))
        db.add(SampleType(sample_type_id=3, sample_name='Inactive sample', is_active=False))
        db.add(Catalog(test_id=3, test_code='INACTIVE', test_name='Inactive test', department_id=1,
                       result_type='NUMERIC', is_active=False))
        db.add(Panel(panel_id=3, panel_code='INACTIVE', panel_name='Inactive panel', is_active=False))
        db.add(Panel(panel_id=4, panel_code='EMPTY', panel_name='Empty panel'))
        db.add(RejectionReason(rejection_reason_id=1, **REASON))
        db.add(RejectionReason(rejection_reason_id=2, reason_code='INACTIVE', reason_name='Inactive', is_active=False))
        db.flush()
        db.add_all(PanelTest(panel_id=p, test_id=t, sort_order=t, is_required=t == 1)
                   for p, t in ((1, 1), (1, 2), (2, 1)))
        db.add_all(SampleLink(test_id=t, sample_type_id=1, is_default=True) for t in (1, 2))
        db.add(SampleLink(test_id=1, sample_type_id=2, is_default=False))
    return lab_api


@pytest.fixture
def admin(workflow_api):
    with workflow_api.factory.begin() as db:
        db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    assert login(workflow_api).status_code == 200
    return workflow_api


def call(api, method, path, body=None):
    return api.client.request(method, BASE + path, json=body, headers=csrf(api))


def create(api, path, body):
    result = call(api, 'POST', path, body)
    assert result.status_code == 201, result.text
    return result.json()


def order(api, **changes):
    return create(api, '/lab-orders', {**ORDER, **changes})


def specimen(api, requested=None, **changes):
    requested = requested or order(api)
    return create(api, f'/lab-orders/{requested["order_id"]}/specimens', {
        'sample_type_id': 1, 'order_item_ids': [item['order_item_id'] for item in requested['items']], **changes})


def detail(api, identifier=1):
    response = call(api, 'GET', f'/lab-orders/{identifier}')
    assert response.status_code == 200
    return response.json()


def transition(api, action, identifier=1, body=None):
    return call(api, 'POST', f'/specimens/{identifier}/{action}', body)


ENDPOINTS = [
    ('POST', '/lab-orders', ORDER, 'LAB_ORDER_CREATE'),
    ('GET', '/lab-orders', None, 'LAB_ORDER_READ'),
    ('GET', '/lab-orders/999', None, 'LAB_ORDER_READ'),
    ('POST', '/lab-orders/999/cancel', {'reason': 'Synthetic withdrawal'}, 'LAB_ORDER_CANCEL'),
    ('POST', '/lab-orders/999/specimens', {'sample_type_id': 1, 'order_item_ids': [1]}, 'SPECIMEN_REGISTER'),
    ('GET', '/lab-orders/999/specimens', None, 'SPECIMEN_READ'),
    ('GET', '/specimens/999', None, 'SPECIMEN_READ'),
    ('POST', '/specimens/999/collect', None, 'SPECIMEN_COLLECT'),
    ('POST', '/specimens/999/receive', None, 'SPECIMEN_RECEIVE'),
    ('POST', '/specimens/999/reject', REJECT, 'SPECIMEN_REJECT'),
    ('POST', '/lab/rejection-reasons', {'reason_name': 'Synthetic'}, 'REJECTION_REASON_MANAGE'),
    ('GET', '/lab/rejection-reasons', None, 'REJECTION_REASON_MANAGE'),
    ('PATCH', '/lab/rejection-reasons/999', {}, 'REJECTION_REASON_MANAGE'),
]


@pytest.mark.parametrize('method,path,body,permission', ENDPOINTS)
def test_every_route_auth_permission_csrf(workflow_api, method, path, body, permission):
    assert workflow_api.client.request(method, BASE + path, json=body).status_code == 401
    assert login(workflow_api).status_code == 200
    assert call(workflow_api, method, path, body).status_code == 403
    with workflow_api.factory.begin() as db:
        pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == permission))
        db.add(RolePermission(role_id=1, permission_id=pid))
    if method != 'GET':
        for headers in ({}, {'X-CSRF-Token': 'invalid'}):
            assert workflow_api.client.request(method, BASE + path, json=body, headers=headers).status_code == 403
    response = call(workflow_api, method, path, body)
    assert response.status_code in {200, 201, 404}, response.text
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('changes,status', [
    ({'patient_id': 999}, 422), ({'physician_id': 999}, 422), ({'physician_id': 2}, 409),
    ({'panel_ids': [], 'test_ids': []}, 422), ({'panel_ids': [1, 1]}, 422), ({'test_ids': [1, 1]}, 422),
    ({'panel_ids': [999]}, 422), ({'test_ids': [999]}, 422), ({'panel_ids': [3]}, 409),
    ({'test_ids': [3]}, 409), ({'panel_ids': [4]}, 409), ({'priority': 'routine'}, 422),
    ({'priority': 'STAT '}, 422), ({'patient_id': None}, 422), ({'priority': None}, 422),
    ({'order_id': 99}, 422), ({'order_code': 'CLIENT'}, 422), ({'ordered_by_user_id': 2}, 422),
    ({'order_date': '2000-01-01'}, 422), ({'status': 'COMPLETED'}, 422),
    ({'created_at': '2000-01-01'}, 422), ({'updated_at': '2000-01-01'}, 422),
    ({'request_reason': 'x' * 151}, 422), ({'clinical_notes': 'x' * 16001}, 422),
])
def test_order_validation_atomic(admin, changes, status):
    result = call(admin, 'POST', '/lab-orders', {**ORDER, **changes})
    assert result.status_code == status
    with admin.factory() as db:
        for model in (LabOrder, OrderPanel, LabOrderItem):
            assert count(db, model) == 0
        assert count(db, AuditLog) == 1  # login only


@pytest.mark.parametrize('payload', [{}, {'patient_id': 1, 'test_ids': [1]}, {'priority': 'STAT', 'test_ids': [1]}])
def test_order_required_fields(admin, payload):
    assert call(admin, 'POST', '/lab-orders', payload).status_code == 422


@pytest.mark.parametrize('priority', ['ROUTINE', 'STAT', 'URGENT'])
def test_order_expansion_provenance_and_safe_detail(admin, priority):
    row = order(admin, priority=priority, diagnosis='Clinician supplied synthetic diagnosis', clinical_notes='Synthetic note')
    assert re.fullmatch(r'LAB-\d{6}-[0-9A-F]{18}', row['order_code']) and len(row['order_code']) == 29
    assert row['ordered_by_user_id'] == 1 and row['status'] == 'REQUESTED'
    assert row['order_date'] == row['created_at'] and row['updated_at'] is None
    assert row['physician']['physician_id'] == 1 and row['patient']['patient_id'] == 1
    assert len(row['panels']) == 2 and len(row['items']) == 2
    panels = {p['panel_id']: p['order_panel_id'] for p in row['panels']}
    assert [(i['test_id'], i['order_panel_id']) for i in row['items']] == [
        (1, panels[1]), (2, panels[1])]
    assert {p['order_panel_id'] for p in row['items'][0]['definition_snapshot']['panels']} == set(panels.values())
    assert row['items'][0]['definition_snapshot']['selected_individually']
    assert all(i['status'] == 'REQUESTED' and i['created_at'] for i in row['items'])
    assert all(p['status'] == 'REQUESTED' for p in row['panels'])
    assert 'payments' not in row and row['specimens'] == []
    assert detail(admin) == row
    rendered = json.dumps(row)
    for private in ('password', 'session', 'unrelated-address', 'private@example', 'result_value', '_sa_instance_state'):
        assert private not in rendered


def test_panel_configuration_snapshot_and_inactive_component(admin):
    with admin.factory.begin() as db:
        db.get(Catalog, 2).is_active = False
    response = call(admin, 'POST', '/lab-orders', ORDER)
    assert response.status_code == 409 and 'Panel configuration' in response.text
    with admin.factory.begin() as db:
        assert count(db, LabOrder) == 0
        db.get(Catalog, 2).is_active = True
    original = order(admin)
    with admin.factory.begin() as db:
        db.delete(db.scalar(select(PanelTest).where(PanelTest.panel_id == 1, PanelTest.test_id == 2)))
    newer = order(admin)
    assert len(newer['items']) == 1
    assert detail(admin, original['order_id'])['items'] == original['items']


def test_individual_and_panel_only_requests(admin):
    one = order(admin, panel_ids=[], test_ids=[2], physician_id=None)
    assert one['physician'] is None and one['items'][0]['order_panel_id'] is None
    assert one['diagnosis'] is None
    two = order(admin, panel_ids=[1], test_ids=[])
    assert len(two['items']) == 2 and all(i['order_panel_id'] for i in two['items'])


def test_list_pagination_filters_search_and_dates(admin):
    a = order(admin)
    b = order(admin, patient_id=2, physician_id=None, priority='STAT')
    with admin.factory.begin() as db:
        db.get(LabOrder, a['order_id']).order_date = datetime(2026, 9, 15, 23, 59, 59)
        db.get(LabOrder, b['order_id']).order_date = datetime(2026, 9, 15, 23, 59, 59)
    for query, expected in [('', 2), ('patient_id=1', 1), ('physician_id=1', 1), ('priority=STAT', 1),
                            ('status=REQUESTED', 2), ('status=IN_PROGRESS', 0), ('search=' + a['order_code'], 1),
                            ('search=P-SYNTH-2', 1), ('search=Synthetic1', 1), ('search=Example2', 1),
                            ('search=%25', 0), ('date_from=2026-09-15&date_to=2026-09-15', 2),
                            ('date_from=2026-09-16', 0), ('date_to=2026-09-14', 0)]:
        assert call(admin, 'GET', '/lab-orders?' + query).json()['total'] == expected
    page = call(admin, 'GET', '/lab-orders?page_size=1').json()
    assert page['total'] == 2 and page['page_size'] == 1 and page['page'] == 1
    assert page['items'][0]['order_id'] == b['order_id']
    assert call(admin, 'GET', '/lab-orders?page_size=1&page=2').json()['items'][0]['order_id'] == a['order_id']
    assert call(admin, 'GET', '/lab-orders?page=999').json()['items'] == []
    for query in ('page=0', 'page_size=0', 'page_size=101', 'priority=stat', 'status=PAID',
                  'date_from=bad', 'date_from=2026-09-16&date_to=2026-09-15', 'patient_id=-1'):
        assert call(admin, 'GET', '/lab-orders?' + query).status_code == 422


@pytest.mark.parametrize('started', [False, True])
def test_cancel_preserves_completed_children_specimens_and_history(admin, started):
    row = order(admin)
    if started:
        specimen(admin, row)
    with admin.factory.begin() as db:
        db.get(LabOrderItem, row['items'][0]['order_item_id']).status = 'COMPLETED'
        db.get(OrderPanel, row['panels'][0]['order_panel_id']).status = 'COMPLETED'
    response = call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Patient withdrew request'})
    assert response.status_code == 200 and response.json()['status'] == 'CANCELLED'
    final = detail(admin)
    assert final['items'][0]['status'] == final['panels'][0]['status'] == 'COMPLETED'
    assert all(i['status'] == 'CANCELLED' for i in final['items'][1:])
    assert final['panels'][1]['status'] == 'CANCELLED'
    assert len(final['specimens']) == int(started)
    if started:
        assert len(final['specimens'][0]['mappings']) == 2
    assert call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Again'}).status_code == 409
    with admin.factory() as db:
        log = db.scalar(select(AuditLog).where(AuditLog.action == 'LAB_ORDER_CANCEL'))
        assert log.old_value['status'] == ('IN_PROGRESS' if started else 'REQUESTED')
        assert log.new_value['reason'] == 'Patient withdrew request'


def test_completed_order_cannot_cancel_or_register(admin):
    row = order(admin)
    with admin.factory.begin() as db:
        db.get(LabOrder, row['order_id']).status = 'COMPLETED'
    assert call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Synthetic'}).status_code == 409
    assert call(admin, 'POST', '/lab-orders/1/specimens', {'sample_type_id': 1, 'order_item_ids': [1]}).status_code == 409
    assert detail(admin)['status'] == 'COMPLETED'


@pytest.mark.parametrize('changes,status', [
    ({'sample_type_id': 999}, 422), ({'sample_type_id': 3}, 409), ({'order_item_ids': []}, 422),
    ({'order_item_ids': [1, 1]}, 422), ({'order_item_ids': [1, 999]}, 422),
    ({'sample_type_id': 2}, 409), ({'specimen_code': 'CLIENT'}, 422), ({'specimen_id': 2}, 422),
    ({'collected_by_user_id': 2}, 422), ({'collected_at': '2000-01-01'}, 422),
    ({'received_by_user_id': 2}, 422), ({'received_at': '2000-01-01'}, 422),
    ({'specimen_status': 'COLLECTED'}, 422), ({'created_at': '2000-01-01'}, 422),
    ({'remarks': 'x' * 16001}, 422),
])
def test_specimen_invalid_atomic(admin, changes, status):
    order(admin)
    response = call(admin, 'POST', '/lab-orders/1/specimens', {'sample_type_id': 1, 'order_item_ids': [1, 2], **changes})
    assert response.status_code == status
    with admin.factory() as db:
        assert count(db, Specimen) == count(db, SpecimenOrderItem) == 0
    assert detail(admin)['status'] == 'REQUESTED'
    assert all(i['status'] == 'REQUESTED' for i in detail(admin)['items'])


@pytest.mark.parametrize('case', ['cross_order', 'cancelled_order', 'cancelled_item', 'completed_item'])
def test_specimen_membership_and_lifecycle_guards(admin, case):
    row = order(admin)
    ids = [1]
    if case == 'cross_order':
        other = order(admin)
        ids += [other['items'][0]['order_item_id']]
    else:
        with admin.factory.begin() as db:
            model = LabOrder if case == 'cancelled_order' else LabOrderItem
            db.get(model, 1).status = 'COMPLETED' if case == 'completed_item' else 'CANCELLED'
    response = call(admin, 'POST', f'/lab-orders/{row["order_id"]}/specimens', {'sample_type_id': 1, 'order_item_ids': ids})
    assert response.status_code == (422 if case == 'cross_order' else 409)
    with admin.factory() as db:
        assert count(db, Specimen) == count(db, SpecimenOrderItem) == 0


def test_register_mapping_and_selective_processing_without_payment(admin):
    row = order(admin)
    first = specimen(admin, row, order_item_ids=[row['items'][0]['order_item_id']])
    assert re.fullmatch(r'SP-\d{6}-[0-9A-F]{18}', first['specimen_code']) and len(first['specimen_code']) <= 30
    assert first['specimen_status'] == 'PENDING'
    assert first['collected_at'] is first['collected_by_user_id'] is first['received_at'] is first['received_by_user_id'] is None
    assert first['sample_type']['sample_type_id'] == 1
    assert [m['order_item_id'] for m in first['mappings']] == [row['items'][0]['order_item_id']]
    after = detail(admin)
    assert after['status'] == 'IN_PROGRESS' and after['updated_at']
    assert [i['status'] for i in after['items']] == ['IN_PROGRESS', 'REQUESTED']
    assert [p['status'] for p in after['panels']] == ['IN_PROGRESS', 'IN_PROGRESS']
    assert 'payments' not in after
    assert transition(admin, 'collect').status_code == 200
    second = specimen(admin, row, sample_type_id=2, order_item_ids=[row['items'][0]['order_item_id']])
    assert second['specimen_code'] != first['specimen_code']
    page = call(admin, 'GET', '/lab-orders/1/specimens?page_size=1&page=2').json()
    assert page['items'] == [second] and page['total'] == 2
    assert call(admin, 'GET', '/specimens/2').json() == second


@pytest.mark.parametrize('initial,action,expected', [
    ('PENDING', 'collect', 200), ('COLLECTED', 'collect', 409), ('RECEIVED', 'collect', 409),
    ('REJECTED', 'collect', 409), ('PROCESSED', 'collect', 409),
    ('PENDING', 'receive', 409), ('COLLECTED', 'receive', 200), ('RECEIVED', 'receive', 409),
    ('REJECTED', 'receive', 409), ('PROCESSED', 'receive', 409),
    ('PENDING', 'reject', 409), ('COLLECTED', 'reject', 200), ('RECEIVED', 'reject', 200),
    ('REJECTED', 'reject', 409), ('PROCESSED', 'reject', 409),
])
def test_transition_matrix(admin, initial, action, expected):
    specimen(admin)
    with admin.factory.begin() as db:
        db.get(Specimen, 1).specimen_status = initial
    response = transition(admin, action, body=REJECT if action == 'reject' else None)
    assert response.status_code == expected
    row = call(admin, 'GET', '/specimens/1').json()
    if expected == 409:
        assert row['specimen_status'] == initial
        return
    target, prefix = {'collect': ('COLLECTED', 'collected'), 'receive': ('RECEIVED', 'received'),
                      'reject': ('REJECTED', 'rejected')}[action]
    assert row['specimen_status'] == target
    provenance = row['rejections'][0] if action == 'reject' else row
    assert provenance[prefix + '_by_user_id'] == 1 and provenance[prefix + '_at']
    assert len(row['mappings']) == 2
    assert transition(admin, action, body=REJECT if action == 'reject' else None).status_code == 409
    assert detail(admin)['status'] == 'IN_PROGRESS'


@pytest.mark.parametrize('action', ['collect', 'receive'])
def test_cancel_blocks_further_processing(admin, action):
    specimen(admin)
    if action == 'receive':
        assert transition(admin, 'collect').status_code == 200
    call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Synthetic withdrawal'})
    assert transition(admin, action).status_code == 409


@pytest.mark.parametrize('changes,status', [({'rejection_reason_id': 999}, 422), ({'rejection_reason_id': 2}, 409),
    ({'rejected_by_user_id': 2}, 422), ({'rejected_at': '2000-01-01'}, 422), ({'specimen_id': 2}, 422)])
def test_reject_validation(admin, changes, status):
    specimen(admin)
    transition(admin, 'collect')
    assert transition(admin, 'reject', body={**REJECT, **changes}).status_code == status
    with admin.factory() as db:
        assert count(db, SpecimenRejection) == 0 and db.get(Specimen, 1).specimen_status == 'COLLECTED'


def test_rejection_and_recollection_preserve_history(admin):
    row = order(admin)
    first = specimen(admin, row)
    transition(admin, 'collect')
    transition(admin, 'receive')
    rejected = transition(admin, 'reject', body=REJECT).json()
    assert rejected['rejections'][0]['recollection_required'] is True
    assert rejected['rejections'][0]['details'] == REJECT['details']
    assert rejected['mappings'] == first['mappings']
    second = specimen(admin, row)
    assert second['specimen_id'] != first['specimen_id'] and second['specimen_code'] != first['specimen_code']
    assert [m['order_item_id'] for m in second['mappings']] == [m['order_item_id'] for m in first['mappings']]
    assert transition(admin, 'collect', second['specimen_id']).status_code == 200
    assert transition(admin, 'receive', second['specimen_id']).status_code == 200
    assert call(admin, 'GET', '/specimens/1').json() == rejected
    assert len(detail(admin)['specimens']) == 2


def test_cancelled_order_can_record_rejection_of_existing_collected_specimen(admin):
    specimen(admin)
    transition(admin, 'collect')
    call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Synthetic withdrawal'})
    assert transition(admin, 'reject', body={**REJECT, 'recollection_required': False}).status_code == 200
    assert detail(admin)['status'] == 'CANCELLED'


def test_rejection_reasons_crud_paging_generated_codes(admin):
    payload = {'reason_name': 'New synthetic', 'description': 'Description'}
    new = create(admin, '/lab/rejection-reasons', payload)
    second = create(admin, '/lab/rejection-reasons', payload)
    assert re.fullmatch(r'REJ-[0-9]{3,}', new['reason_code'])
    assert re.fullmatch(r'REJ-[0-9]{3,}', second['reason_code'])
    assert new['reason_code'] != second['reason_code']
    path = f'/lab/rejection-reasons/{new["rejection_reason_id"]}'
    assert call(admin, 'POST', '/lab/rejection-reasons', {**payload, 'reason_code': 'MANUAL'}).status_code == 422
    assert call(admin, 'PATCH', path, {'reason_code': 'CLOTTED', 'description': 'Must rollback'}).status_code == 422
    unchanged = call(admin, 'GET', '/lab/rejection-reasons?search=' + new['reason_code']).json()
    assert unchanged['items'] == [new]
    page = call(admin, 'GET', '/lab/rejection-reasons?search=New&page_size=1&page=2').json()
    assert page['total'] == 2 and page['page'] == 2 and page['page_size'] == 1
    assert page['items'] == [second]
    changed = call(admin, 'PATCH', path, {'description': None, 'is_active': False}).json()
    assert changed['description'] is None and changed['is_active'] is False
    assert changed['reason_code'] == new['reason_code']
    assert call(admin, 'GET', '/lab/rejection-reasons?search=NEW&is_active=false&page_size=1').json()['items'] == [changed]
    for field in ('reason_code', 'reason_name', 'is_active'):
        assert call(admin, 'PATCH', path, {field: None}).status_code == 422
    assert call(admin, 'PATCH', path, {'rejection_reason_id': 5}).status_code == 422
    assert call(admin, 'PATCH', path, {'reason_code': 'x' * 41}).status_code == 422
    assert call(admin, 'DELETE', path).status_code == 405
    with admin.factory() as db:
        assert db.get(RejectionReason, 1).reason_code == 'CLOTTED'
        assert db.get(RejectionReason, 2).reason_code == 'INACTIVE'
        assert db.get(CodeSequence, 'REJECTION_REASON').current_value == 2
        logs = list(db.scalars(select(AuditLog).where(AuditLog.entity_type == 'rejection_reason')
                               .order_by(AuditLog.audit_id)))
        assert [log.action for log in logs] == ['REJECTION_REASON_CREATE', 'REJECTION_REASON_CREATE', 'REJECTION_REASON_UPDATE']
        assert 'reason_code' in logs[0].new_value['changed_fields']
        assert logs[-1].new_value == {'changed_fields': ['description', 'is_active']}


@pytest.mark.parametrize('failure', ['collision', 'audit_log', 'commit'])
def test_rejection_reason_creation_rolls_back_code_record_and_audit(admin, failure):
    payload = {'reason_name': 'Synthetic reason'}
    first = create(admin, '/lab/rejection-reasons', payload)
    assert first['reason_code'] == 'REJ-001'
    with admin.factory.begin() as db:
        if failure == 'collision':
            # Simulate a stale counter while preserving the existing record.
            db.get(CodeSequence, 'REJECTION_REASON').current_value = 0
        before_value = db.get(CodeSequence, 'REJECTION_REASON').current_value
        before_audits, before_records = count(db, AuditLog), count(db, RejectionReason)

    def fail(*args):
        if failure == 'commit' or args[2].startswith('INSERT INTO audit_log '):
            raise SQLAlchemyError('private failure')

    host, hook = (admin.factory, 'before_commit') if failure == 'commit' else (admin.engine, 'before_cursor_execute')
    if failure != 'collision':
        event.listen(host, hook, fail)
    try:
        response = call(admin, 'POST', '/lab/rejection-reasons', payload)
        assert response.status_code == (409 if failure == 'collision' else 503), response.text
        assert 'private' not in response.text
    finally:
        if failure != 'collision':
            event.remove(host, hook, fail)
    with admin.factory.begin() as db:
        sequence = db.get(CodeSequence, 'REJECTION_REASON')
        assert sequence.current_value == before_value
        assert count(db, RejectionReason) == before_records
        assert count(db, AuditLog) == before_audits
        assert db.get(RejectionReason, first['rejection_reason_id']).reason_code == first['reason_code']
        if failure == 'collision':
            sequence.current_value = 1
    recovered = create(admin, '/lab/rejection-reasons', payload)
    assert recovered['reason_code'] == 'REJ-002'


@pytest.mark.parametrize('target', ['lab_order', 'order_panel', 'lab_order_item', 'audit_log', 'commit'])
def test_order_failure_rollback(admin, target):
    def fail(*args):
        if target == 'commit' or args[2].startswith('INSERT INTO ' + target + ' '):
            raise SQLAlchemyError('private failure')
    host, hook = (admin.factory, 'before_commit') if target == 'commit' else (admin.engine, 'before_cursor_execute')
    event.listen(host, hook, fail)
    try:
        response = call(admin, 'POST', '/lab-orders', ORDER)
        assert response.status_code == 503 and 'private' not in response.text
    finally:
        event.remove(host, hook, fail)
    with admin.factory() as db:
        assert count(db, LabOrder) == count(db, OrderPanel) == count(db, LabOrderItem) == 0
        assert count(db, AuditLog) == 1


@pytest.mark.parametrize('action,target', [
    ('register', 'specimen'), ('register', 'specimen_order_item'), ('register', 'audit_log'),
    ('collect', 'audit_log'), ('receive', 'audit_log'), ('reject', 'specimen_rejection'), ('reject', 'audit_log'),
    ('cancel', 'audit_log'),
])
def test_workflow_failure_rollback(admin, action, target):
    order(admin)
    if action in {'collect', 'receive', 'reject', 'cancel'}:
        specimen(admin, detail(admin))
    if action in {'receive', 'reject'}:
        transition(admin, 'collect')
    before = detail(admin)
    with admin.factory() as db:
        before_audits = count(db, AuditLog)
    def fail(connection, cursor, statement, params, context, executemany):
        if statement.startswith('INSERT INTO ' + target + ' '):
            raise SQLAlchemyError('private failure')
    event.listen(admin.engine, 'before_cursor_execute', fail)
    try:
        if action == 'register':
            response = call(admin, 'POST', '/lab-orders/1/specimens', {'sample_type_id': 1, 'order_item_ids': [1, 2]})
        elif action == 'cancel':
            response = call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Synthetic'})
        else:
            response = transition(admin, action, body=REJECT if action == 'reject' else None)
        assert response.status_code == 503 and 'private' not in response.text
    finally:
        event.remove(admin.engine, 'before_cursor_execute', fail)
    assert detail(admin) == before
    with admin.factory() as db:
        assert count(db, AuditLog) == before_audits


@pytest.mark.parametrize('kind', ['order', 'specimen'])
@pytest.mark.parametrize('exhausted', [False, True])
def test_code_collision_retry_whole_transaction(admin, monkeypatch, kind, exhausted):
    row = order(admin)
    if kind == 'specimen':
        original = specimen(admin, row)
        path, payload = '/lab-orders/1/specimens', {'sample_type_id': 1, 'order_item_ids': [1, 2]}
        existing = original['specimen_code']
    else:
        path, payload, existing = '/lab-orders', ORDER, row['order_code']
    values = iter([existing] * 3 if exhausted else [existing, 'UNIQUE-SYNTHETIC-CODE'])
    monkeypatch.setattr(service, 'generated_code', lambda prefix: next(values))
    response = call(admin, 'POST', path, payload)
    assert response.status_code == (409 if exhausted else 201), response.text
    with admin.factory() as db:
        assert count(db, LabOrder if kind == 'order' else Specimen) == (1 if exhausted else 2)
        assert count(db, LabOrderItem) == (4 if kind == 'order' and not exhausted else 2)
        assert count(db, SpecimenOrderItem) == (4 if kind == 'specimen' and not exhausted else 2 if kind == 'specimen' else 0)


def test_all_audits_bootstrap_and_privacy(admin, caplog):
    row = order(admin, clinical_notes='private-clinical-note', diagnosis='private-clinician-diagnosis', request_reason='private-request')
    specimen(admin, row, remarks='private-remarks')
    transition(admin, 'collect')
    transition(admin, 'receive')
    transition(admin, 'reject', body={**REJECT, 'details': 'private-details'})
    create(admin, '/lab/rejection-reasons', {'reason_name': 'Private reason', 'description': 'private-description'})
    call(admin, 'PATCH', '/lab/rejection-reasons/1', {'is_active': False})
    call(admin, 'POST', '/lab-orders/1/cancel', {'reason': 'Synthetic withdrawal'})
    bootstrap_permissions.main()
    bootstrap_permissions.main()
    with admin.factory() as db:
        assert ensure_permissions(db) == []
        assert set(db.scalars(select(Permission.permission_code))) >= {endpoint[3] for endpoint in ENDPOINTS}
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action != 'AUTH_LOGIN')))
        assert {log.action for log in logs} == {
            'LAB_ORDER_CREATE', 'LAB_ORDER_CANCEL', 'SPECIMEN_REGISTER', 'SPECIMEN_COLLECT',
            'SPECIMEN_RECEIVE', 'SPECIMEN_REJECT', 'REJECTION_REASON_CREATE', 'REJECTION_REASON_UPDATE'}
        assert len(logs) == 8 and all(log.record_id and log.user_id == 1 and log.created_at for log in logs)
        serialized = json.dumps([{'old': log.old_value, 'new': log.new_value} for log in logs])
    assert 'private-' not in serialized + caplog.text
    assert 'P-SYNTH' not in serialized and 'Synthetic1' not in serialized
    for secret in [PASSWORD, *admin.client.cookies.values()]:
        assert secret not in serialized + caplog.text


def test_openapi_phase4a_contract():
    from app.main import app
    paths = app.openapi()['paths']
    # Order results and reports belong to Phase 4B and Phase 5A respectively.
    phase = {path: methods for path, methods in paths.items() if path.startswith((
        BASE + '/lab-orders', BASE + '/specimens', BASE + '/lab/rejection-reasons'))
        and not path.endswith(('/results', '/reports'))}
    assert sum(len(methods) for methods in phase.values()) == 14
    assert not any('result' in path for path in phase)
    for methods in phase.values():
        assert 'delete' not in methods and 'put' not in methods
        for operation in methods.values():
            assert operation['security'] and operation['tags']


def test_retired_payment_routes_and_archived_records(admin):
    from app.models import LabPayment
    row = order(admin)
    with admin.factory.begin() as db:
        db.add_all(LabPayment(order_id=row['order_id'], payment_status=status,
                             amount='12.25', reference_number='archived-reference', recorded_at=utc_now())
                   for status in ('PENDING', 'PAID'))
    with admin.factory() as db:
        before = list(db.execute(select(LabPayment.__table__)))
    for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
        assert call(admin, method, '/lab-orders/1/payments', {'payment_status': 'PAID'}).status_code == 404
    # Ordering and specimen processing must not even read archived financial data.
    def no_financial_queries(connection, cursor, statement, *args):
        assert 'lab_payment' not in statement.lower()
    event.listen(admin.engine, 'before_cursor_execute', no_financial_queries)
    try:
        assert 'payments' not in detail(admin)
        specimen(admin, row)
        assert transition(admin, 'collect').status_code == 200
        assert transition(admin, 'receive').status_code == 200
        assert 'payments' not in order(admin)
    finally:
        event.remove(admin.engine, 'before_cursor_execute', no_financial_queries)
    with admin.factory() as db:
        assert list(db.execute(select(LabPayment.__table__))) == before


def test_archived_permissions_not_exposed_or_effective(admin):
    from app.api import administration
    from app.services.rbac_service import get_user_permissions, user_has_permission
    from app.services.administration_service import role_permissions
    admin.app.include_router(administration.router, prefix=BASE)
    with admin.factory.begin() as db:
        for code in ('PAYMENT_READ', 'PAYMENT_RECORD'):
            permission = Permission(permission_code=code, permission_name='Archived capability')
            db.add(permission); db.flush()
            db.add(RolePermission(role_id=2, permission_id=permission.permission_id))
    with admin.factory() as db:
        assert not any(p.startswith('PAYMENT_') for p in get_user_permissions(db, 1))
        assert not any(p.startswith('PAYMENT_') for p in role_permissions(db, [2]))
        assert not user_has_permission(db, 1, 'PAYMENT_RECORD')
        assert user_has_permission(db, 1, 'LAB_ORDER_CREATE')
        assert len(list(db.scalars(select(Permission).where(Permission.permission_code.like('PAYMENT_%'))))) == 2
    response = call(admin, 'GET', '/permissions')
    assert response.status_code == 200
    assert not any(p['permission_code'].startswith('PAYMENT_') for p in response.json())
