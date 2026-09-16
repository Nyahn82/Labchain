"""Synthetic Phase 4B API, Decimal/range, integrity and atomic completion checks."""

from datetime import date, datetime
from decimal import Decimal, localcontext
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import results
from app.cli import bootstrap_permissions
from app.models import (
    AuditLog, LabOrder, LabOrderItem, LabResultItem, OrderPanel, Patient, Permission,
    ReferenceRange, RolePermission, Specimen, SpecimenOrderItem, TestCatalog as Catalog,
    UserRole,
)
from app.services import result_service as service
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from app.services.result_calculations import age_at_date, calculate_result_flag, parse_numeric_value
from test_phase_3a_authentication_rbac import env, password_hash, login, csrf, count, PASSWORD
from test_phase_3c_laboratory import lab_api
from test_phase_4a_workflow import workflow_api, call, create, order, specimen, transition, detail

BOUNDS = {'normal_low': Decimal('12'), 'normal_high': Decimal('16'),
          'critical_low': Decimal('10'), 'critical_high': Decimal('20')}


@pytest.fixture
def results_api(workflow_api):
    workflow_api.app.include_router(results.router, prefix='/api/v1')
    with workflow_api.factory.begin() as db:
        patient = db.get(Patient, 1)
        patient.sex, patient.birth_date = 'M', date(2000, 1, 1)
        db.add(ReferenceRange(range_id=1, test_id=1, sex='ANY', **BOUNDS))
    return workflow_api


@pytest.fixture
def admin(results_api):
    with results_api.factory.begin() as db:
        db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    assert login(results_api).status_code == 200
    return results_api


def requested(api, **changes):
    return order(api, panel_ids=[], test_ids=[1], **changes)


def enter(api, item_id=1, **values):
    return call(api, 'POST', f'/lab-order-items/{item_id}/result', {'result_value': '12.60', **values})


def result(api, item_id=1, **values):
    response = enter(api, item_id, **values)
    assert response.status_code == 201, response.text
    return response.json()


def read(api, result_id=1):
    response = call(api, 'GET', f'/results/{result_id}')
    assert response.status_code == 200, response.text
    return response.json()


def advance(api, action, result_id=1):
    return call(api, 'POST', f'/results/{result_id}/{action}')


def finish(api, item_id):
    row = result(api, item_id)
    assert advance(api, 'review', row['result_item_id']).status_code == 200
    assert advance(api, 'verify', row['result_item_id']).status_code == 200
    return row['result_item_id']


def received(api, requested_order=None):
    sample = specimen(api, requested_order)
    sid = sample['specimen_id']
    assert transition(api, 'collect', sid).status_code == 200
    assert transition(api, 'receive', sid).status_code == 200
    return sid


ENDPOINTS = [
    ('POST', '/lab-order-items/999/result', {'result_value': '12.60'}, 'LAB_RESULT_ENTER'),
    ('GET', '/lab-orders/999/results', None, 'LAB_RESULT_READ'),
    ('GET', '/results/999', None, 'LAB_RESULT_READ'),
    ('PATCH', '/results/999', {'result_value': '12.61'}, 'LAB_RESULT_ENTER'),
    ('POST', '/results/999/review', None, 'LAB_RESULT_REVIEW'),
    ('POST', '/results/999/verify', None, 'LAB_RESULT_VERIFY'),
]


@pytest.mark.parametrize('method,path,body,permission', ENDPOINTS)
def test_every_route_auth_permission_csrf(results_api, method, path, body, permission):
    assert results_api.client.request(method, '/api/v1' + path, json=body).status_code == 401
    assert login(results_api).status_code == 200
    assert call(results_api, method, path, body).status_code == 403
    with results_api.factory.begin() as db:
        pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == permission))
        db.add(RolePermission(role_id=1, permission_id=pid))
    if method != 'GET':
        for headers in ({}, {'X-CSRF-Token': 'wrong'}):
            assert results_api.client.request(method, '/api/v1' + path, json=body, headers=headers).status_code == 403
    response = call(results_api, method, path, body)
    assert response.status_code == 404 and response.headers['cache-control'] == 'no-store'


def test_entry_initial_state_duplicate_safe_reads_and_progress(admin):
    requested(admin)
    row = result(admin, result_value=' 12.60 ', remarks='Synthetic remarks')
    assert row['result_value'] == '12.60' and row['numeric_value'] == '12.600'
    assert row['reference_range_id'] == 1 and row['flag'] == 'NORMAL' and row['status'] == 'DRAFT'
    assert row['encoded_by_user_id'] == 1 and row['encoded_at']
    assert row['encoded_by'] == {'user_id': 1, 'username': 'tester'}
    assert row['reviewed_by'] is row['reviewed_at'] is row['reviewed_by_user_id'] is None
    assert row['verified_by'] is row['verified_at'] is row['verified_by_user_id'] is None
    assert row['specimen'] is row['specimen_id'] is None
    assert row['test']['test_id'] == row['reference_range']['test_id'] == 1
    assert read(admin) == row
    assert enter(admin).status_code == 409
    with admin.factory() as db:
        stored = db.get(LabResultItem, row['result_item_id'])
        assert isinstance(stored.numeric_value, Decimal) and stored.numeric_value == Decimal('12.600')
    parent = detail(admin)
    assert parent['status'] == parent['items'][0]['status'] == 'IN_PROGRESS'
    assert parent['diagnosis'] is None
    for secret in ('password', 'session', 'account_status', 'private@example', 'unrelated-address', 'interpretation'):
        assert secret not in json.dumps(row)
    assert 'results' not in parent  # Separate LAB_RESULT_READ permission boundary.


@pytest.mark.parametrize('model', [LabOrder, LabOrderItem])
@pytest.mark.parametrize('action', ['create', 'patch', 'review', 'verify'])
def test_cancelled_parent_or_item_blocks_mutation(admin, model, action):
    requested(admin)
    if action != 'create':
        result(admin)
    if action == 'verify':
        advance(admin, 'review')
    with admin.factory.begin() as db:
        db.get(model, 1).status = 'CANCELLED'
    if action == 'create':
        response = enter(admin)
    elif action == 'patch':
        response = call(admin, 'PATCH', '/results/1', {'result_value': '15'})
    else:
        response = advance(admin, action)
    assert response.status_code == 409
    with admin.factory() as db:
        assert db.get(model, 1).status == 'CANCELLED'
        assert count(db, LabResultItem) == int(action != 'create')


SERVER_FIELDS = ['result_item_id', 'order_item_id', 'reference_range_id', 'numeric_value', 'flag', 'status',
                 'encoded_by_user_id', 'encoded_at', 'reviewed_by_user_id', 'reviewed_at', 'verified_by_user_id', 'verified_at']


@pytest.mark.parametrize('field', SERVER_FIELDS)
def test_server_fields_forbidden_create_patch(admin, field):
    requested(admin)
    response = enter(admin, **{field: 'private-value'})
    assert response.status_code == 422 and 'private-value' not in response.text
    result(admin)
    assert call(admin, 'PATCH', '/results/1', {field: 'private-value'}).status_code == 422


@pytest.mark.parametrize('value', ['', ' ', 'abc', '12 mg', 'positive', 'NaN', 'Infinity', '-Infinity', '1_000',
    '1,000', '１２', '0.0001', '999999999.9991', '1000000000', '-1000000000', '1e1000000', '1e-1000000',
    'x' * 101, None, 12.6, True, ['12'], {'number': '12'}])
def test_invalid_numeric_values_leave_no_result_or_progress(admin, value):
    requested(admin)
    assert enter(admin, result_value=value).status_code == 422
    assert detail(admin)['status'] == 'REQUESTED'
    with admin.factory() as db:
        assert count(db, LabResultItem) == 0


@pytest.mark.parametrize('display,expected', [
    ('12.60', '12.600'), ('-999999999.999', '-999999999.999'), ('999999999.999', '999999999.999'),
    ('0', '0.000'), ('+0.123', '0.123'), ('.5', '0.500'), ('1.2300', '1.230'), ('1.26e1', '12.600'),
])
def test_decimal_exactness_and_display_preservation(admin, display, expected):
    requested(admin)
    row = result(admin, result_value=' ' + display + ' ')
    assert row['result_value'] == display and row['numeric_value'] == expected


@pytest.mark.parametrize('kind', ['TEXT', 'POS_NEG'])
@pytest.mark.parametrize('value,normal,flag', [
    ('Negative', 'Negative', 'NORMAL'), (' negative ', ' Negative ', 'NORMAL'),
    ('Positive', 'Negative', 'ABNORMAL'), ('Detected', 'Not detected', 'ABNORMAL'),
    ('Non-reactive', 'NON-REACTIVE', 'NORMAL'), ('Anything approved', None, None),
])
def test_qualitative_types_and_flags(admin, kind, value, normal, flag):
    requested(admin)
    with admin.factory.begin() as db:
        db.get(Catalog, 1).result_type = kind
        db.get(ReferenceRange, 1).qualitative_normal = normal
    row = result(admin, result_value=value)
    assert row['numeric_value'] is None and row['flag'] == flag and row['result_value'] == value.strip()
    assert row['reference_range_id'] == 1
    assert advance(admin, 'review').status_code == 200
    assert advance(admin, 'verify').status_code == 200


@pytest.mark.parametrize('kind', ['TEXT', 'POS_NEG'])
@pytest.mark.parametrize('value', ['', ' ', None])
def test_qualitative_requires_nonblank_text(admin, kind, value):
    requested(admin)
    with admin.factory.begin() as db:
        db.get(Catalog, 1).result_type = kind
    assert enter(admin, result_value=value).status_code == 422


@pytest.mark.parametrize('value,flag', [
    ('9.999', 'CRITICAL_LOW'), ('10', 'LOW'), ('11.999', 'LOW'), ('12', 'NORMAL'),
    ('14', 'NORMAL'), ('16', 'NORMAL'), ('16.001', 'HIGH'), ('20', 'HIGH'), ('20.001', 'CRITICAL_HIGH'),
])
def test_numeric_flag_boundaries(admin, value, flag):
    requested(admin)
    assert result(admin, result_value=value)['flag'] == flag


@pytest.mark.parametrize('bounds,value,expected', [
    ({}, '10', None), ({'normal_low': Decimal('0')}, '0', 'NORMAL'),
    ({'normal_high': Decimal('0')}, '0.001', 'HIGH'),
    ({'critical_low': Decimal('0')}, '-0.001', 'CRITICAL_LOW'),
    ({'critical_high': Decimal('0')}, '0.001', 'CRITICAL_HIGH'),
    ({'critical_low': Decimal('0'), 'critical_high': Decimal('20')}, '10', None),
])
def test_partial_or_missing_numeric_thresholds(bounds, value, expected):
    reference = SimpleNamespace(**{**dict.fromkeys(BOUNDS), **bounds})
    assert calculate_result_flag('NUMERIC', value, Decimal(value), reference) == expected
    assert calculate_result_flag('NUMERIC', value, Decimal(value), None) is None


@pytest.mark.parametrize('sex,expected', [('M', 2), ('F', 3), ('Other', 1), (None, 1)])
def test_range_sex_precedence(admin, sex, expected):
    requested(admin)
    with admin.factory.begin() as db:
        db.get(Patient, 1).sex = sex
        db.add_all(ReferenceRange(range_id=i, test_id=1, sex=s, **BOUNDS) for i, s in ((2, 'M'), (3, 'F')))
    assert result(admin)['reference_range_id'] == expected


def test_range_historical_age_and_effective_date(admin):
    requested(admin)
    with admin.factory.begin() as db:
        db.get(LabOrder, 1).order_date = datetime(2010, 1, 1, 23, 59)
        db.add(ReferenceRange(range_id=2, test_id=1, sex='M', age_min=Decimal('9.99'), age_max=Decimal('10.01'),
                              effective_from=date(2010, 1, 1), effective_to=date(2010, 1, 1), **BOUNDS))
        db.add(ReferenceRange(range_id=3, test_id=1, sex='M', age_min=Decimal('20'), age_max=Decimal('40'),
                              effective_from=date(2020, 1, 1), **BOUNDS))
    assert result(admin)['reference_range_id'] == 2


def test_fractional_age_utility_does_not_round_to_range_scale():
    birth, day = date(2020, 2, 29), date(2021, 2, 28)
    with localcontext() as context:
        context.prec = 40
        assert age_at_date(birth, day) == Decimal('365') / Decimal('365.2425')
    assert age_at_date(birth, birth) == Decimal(0)
    assert age_at_date(None, day) is None
    with pytest.raises(HTTPException) as exc:
        age_at_date(day, birth)
    assert exc.value.status_code == 422
    age = age_at_date(date(2026, 1, 1), date(2026, 1, 5))
    assert Decimal('0.01') < age < Decimal('0.02')


def test_fractional_age_not_prematurely_rounded_in_selection(admin):
    requested(admin)
    with admin.factory.begin() as db:
        db.get(Patient, 1).birth_date = date(2026, 1, 1)
        db.get(LabOrder, 1).order_date = datetime(2026, 1, 5)
        db.add(ReferenceRange(range_id=2, test_id=1, sex='M', age_max=Decimal('0.01'), **BOUNDS))
    assert result(admin)['reference_range_id'] == 1  # 4 days is greater than 0.01 years.


@pytest.mark.parametrize('bounds', [{'age_min': Decimal(0)}, {'age_max': Decimal(100)},
                                   {'age_min': Decimal(0), 'age_max': Decimal(100)}])
def test_missing_birth_date_only_uses_unbounded_age(admin, bounds):
    requested(admin)
    with admin.factory.begin() as db:
        db.get(Patient, 1).birth_date = None
        db.add(ReferenceRange(range_id=2, test_id=1, sex='M', **bounds, **BOUNDS))
    assert result(admin)['reference_range_id'] == 1


@pytest.mark.parametrize('case', ['inactive', 'other_test', 'expired', 'future', 'bounded_unknown_age', 'none'])
def test_no_applicable_range_is_allowed(admin, case):
    requested(admin)
    with admin.factory.begin() as db:
        reference = db.get(ReferenceRange, 1)
        if case == 'inactive':
            reference.is_active = False
        elif case == 'other_test':
            reference.test_id = 2
        elif case == 'expired':
            reference.effective_to = date(1900, 1, 1)
        elif case == 'future':
            reference.effective_from = date(9999, 1, 1)
        elif case == 'bounded_unknown_age':
            reference.age_min = Decimal(0)
            db.get(Patient, 1).birth_date = None
        else:
            db.delete(reference)
    row = result(admin)
    assert row['reference_range_id'] is row['flag'] is row['reference_range'] is None
    assert advance(admin, 'review').status_code == 200
    assert advance(admin, 'verify').status_code == 200


def test_ambiguous_configuration_rolls_back_and_future_birth_rejected(admin):
    requested(admin)
    with admin.factory.begin() as db:
        db.add(ReferenceRange(test_id=1, sex='ANY', **BOUNDS))
    assert enter(admin).status_code == 409
    with admin.factory.begin() as db:
        assert count(db, LabResultItem) == 0
        db.get(Patient, 1).birth_date = date(9999, 1, 1)
    assert enter(admin).status_code == 422
    assert detail(admin)['status'] == 'REQUESTED'


@pytest.mark.parametrize('state,expected', [('PENDING', 409), ('COLLECTED', 409), ('RECEIVED', 201),
                                           ('REJECTED', 409), ('PROCESSED', 201)])
def test_specimen_status_validation_and_processing(admin, state, expected):
    row = requested(admin)
    sample = specimen(admin, row)
    with admin.factory.begin() as db:
        db.get(Specimen, sample['specimen_id']).specimen_status = state
    response = enter(admin, specimen_id=sample['specimen_id'])
    assert response.status_code == expected
    if expected == 201:
        assert response.json()['specimen']['specimen_status'] == 'PROCESSED'
    with admin.factory() as db:
        assert db.get(Specimen, sample['specimen_id']).specimen_status == ('PROCESSED' if expected == 201 else state)


@pytest.mark.parametrize('case', ['unknown', 'cross_order', 'unmapped'])
def test_specimen_identity_mapping_validation(admin, case):
    row = order(admin)
    specimen_id = 999
    if case == 'cross_order':
        specimen_id = received(admin, requested(admin))
    elif case == 'unmapped':
        sample = specimen(admin, row, order_item_ids=[row['items'][1]['order_item_id']])
        specimen_id = sample['specimen_id']
        transition(admin, 'collect', specimen_id)
        transition(admin, 'receive', specimen_id)
    assert enter(admin, specimen_id=specimen_id).status_code == 422
    with admin.factory() as db:
        assert count(db, LabResultItem) == 0


def test_shared_processed_specimen_accepts_more_results(admin):
    row = order(admin)
    sid = received(admin, row)
    for item in row['items']:
        assert result(admin, item['order_item_id'], specimen_id=sid)['specimen']['specimen_status'] == 'PROCESSED'
    assert detail(admin)['status'] == 'IN_PROGRESS'


def test_draft_patch_rederives_only_changed_value_and_preserves_encoder(admin):
    row = requested(admin)
    original = result(admin)
    with admin.factory.begin() as db:
        db.get(ReferenceRange, 1).is_active = False
        db.add(ReferenceRange(range_id=2, test_id=1, sex='M', normal_low=Decimal('20'), normal_high=Decimal('30')))
    changed = call(admin, 'PATCH', '/results/1', {'result_value': ' 15.50 ', 'remarks': 'Edited'}).json()
    assert changed['numeric_value'] == '15.500' and changed['flag'] == 'LOW' and changed['reference_range_id'] == 2
    assert changed['encoded_at'] == original['encoded_at'] and changed['encoded_by_user_id'] == original['encoded_by_user_id']
    assert changed['status'] == 'DRAFT'
    sid = received(admin, row)
    attached = call(admin, 'PATCH', '/results/1', {'specimen_id': sid, 'remarks': None}).json()
    assert attached['specimen']['specimen_status'] == 'PROCESSED' and attached['remarks'] is None
    assert attached['reference_range_id'] == 2 and attached['flag'] == 'LOW'
    cleared = call(admin, 'PATCH', '/results/1', {'specimen_id': None}).json()
    assert cleared['specimen_id'] is cleared['specimen'] is None
    assert call(admin, 'PATCH', '/results/1', {}).json() == cleared
    for invalid in ({'result_value': 'abc'}, {'result_value': None}, {'specimen_id': 999}, {'remarks': 'x' * 16001}):
        assert call(admin, 'PATCH', '/results/1', invalid).status_code == 422
        assert read(admin) == cleared


@pytest.mark.parametrize('case', ['cross_order', 'unmapped', 'rejected'])
def test_patch_specimen_revalidation(admin, case):
    row = order(admin)
    before = result(admin)
    if case == 'cross_order':
        sid = received(admin, requested(admin))
    else:
        item_ids = [2] if case == 'unmapped' else [1]
        sample = specimen(admin, row, order_item_ids=item_ids)
        sid = sample['specimen_id']
        transition(admin, 'collect', sid)
        transition(admin, 'receive', sid)
        if case == 'rejected':
            transition(admin, 'reject', sid, {'rejection_reason_id': 1, 'recollection_required': True})
    response = call(admin, 'PATCH', '/results/1', {'specimen_id': sid})
    assert response.status_code == (409 if case == 'rejected' else 422)
    assert read(admin) == before


def test_review_verify_provenance_and_immutability_same_actor_allowed(admin):
    requested(admin)
    original = result(admin)
    assert advance(admin, 'verify').status_code == 409
    reviewed = advance(admin, 'review').json()
    assert reviewed['status'] == 'REVIEWED' and reviewed['reviewed_by_user_id'] == 1 and reviewed['reviewed_at']
    assert reviewed['encoded_at'] == original['encoded_at']
    assert detail(admin)['items'][0]['status'] == 'IN_PROGRESS'
    assert advance(admin, 'review').status_code == 409
    assert call(admin, 'PATCH', '/results/1', {'remarks': 'Cannot edit'}).status_code == 409
    verified = advance(admin, 'verify').json()
    assert verified['status'] == 'VERIFIED' and verified['verified_by_user_id'] == 1 and verified['verified_at']
    assert verified['encoded_at'] == original['encoded_at'] and verified['reviewed_at'] == reviewed['reviewed_at']
    assert verified['reviewed_by'] == verified['verified_by'] == original['encoded_by']
    assert detail(admin)['items'][0]['status'] == detail(admin)['status'] == 'COMPLETED'
    assert detail(admin)['payments'] == []
    for action in ('review', 'verify'):
        assert advance(admin, action).status_code == 409
    assert call(admin, 'PATCH', '/results/1', {'result_value': '14'}).status_code == 409
    assert read(admin) == verified
    assert call(admin, 'DELETE', '/results/1').status_code == 405


@pytest.mark.parametrize('action', ['review', 'verify'])
@pytest.mark.parametrize('case', ['mapping_removed', 'rejected', 'cross_order', 'numeric_corrupt', 'range_other_test', 'duplicate'])
def test_review_verify_recheck_integrity(admin, action, case):
    row = requested(admin)
    sid = received(admin, row)
    result(admin, specimen_id=sid)
    if action == 'verify':
        advance(admin, 'review')
    with admin.factory.begin() as db:
        if case == 'mapping_removed':
            db.execute(delete(SpecimenOrderItem).where(SpecimenOrderItem.specimen_id == sid))
        elif case == 'rejected':
            db.get(Specimen, sid).specimen_status = 'REJECTED'
        elif case == 'cross_order':
            other = LabOrder(order_code='SYNTH-OTHER', patient_id=1, priority='ROUTINE', status='REQUESTED', order_date=utc_now())
            db.add(other)
            db.flush()
            db.get(Specimen, sid).order_id = other.order_id
        elif case == 'numeric_corrupt':
            db.get(LabResultItem, 1).numeric_value = Decimal('1')
        elif case == 'range_other_test':
            db.get(ReferenceRange, 1).test_id = 2
        else:
            db.add(LabResultItem(order_item_id=1, result_value='12', numeric_value=Decimal('12'),
                                 status='DRAFT', encoded_by_user_id=1, encoded_at=utc_now()))
    response = advance(admin, action)
    assert response.status_code in {409, 422}
    assert read(admin)['status'] == ('DRAFT' if action == 'review' else 'REVIEWED')
    assert detail(admin)['status'] == 'IN_PROGRESS'


def test_review_and_verify_do_not_recalculate_stored_flags_from_mutable_master(admin):
    requested(admin)
    original = result(admin)
    with admin.factory.begin() as db:
        db.get(ReferenceRange, 1).normal_low = Decimal('13')
    assert advance(admin, 'review').json()['flag'] == original['flag']
    with admin.factory.begin() as db:
        db.get(ReferenceRange, 1).is_active = False
        db.get(Patient, 1).birth_date = None
    assert advance(admin, 'verify').json()['flag'] == original['flag']
    assert read(admin)['reference_range']['is_active'] is False


@pytest.mark.parametrize('panels,tests', [([], [1]), ([1], []), ([1], [2]), ([1, 2], [1])])
def test_individual_panel_mixed_overlapping_completion(admin, panels, tests):
    row = order(admin, panel_ids=panels, test_ids=tests)
    for index, item in enumerate(row['items']):
        finish(admin, item['order_item_id'])
        after = detail(admin)
        assert after['status'] == ('COMPLETED' if index == len(row['items']) - 1 else 'IN_PROGRESS')
        assert [i['status'] for i in after['items']] == ['COMPLETED'] * (index + 1) + ['REQUESTED'] * (len(row['items']) - index - 1)
        for panel in after['panels']:
            members = [i for i in after['items'] if i['order_panel_id'] == panel['order_panel_id']]
            expected = 'COMPLETED' if all(i['status'] == 'COMPLETED' for i in members) else (
                'IN_PROGRESS' if any(i['status'] == 'COMPLETED' for i in members) else 'REQUESTED')
            assert panel['status'] == expected
    assert detail(admin)['payments'] == []


def test_cancelled_items_ignored_and_cancelled_panel_preserved(admin):
    row = order(admin, panel_ids=[1, 2], test_ids=[])
    with admin.factory.begin() as db:
        db.get(LabOrderItem, row['items'][1]['order_item_id']).status = 'CANCELLED'
        db.get(OrderPanel, row['panels'][1]['order_panel_id']).status = 'CANCELLED'
    finish(admin, row['items'][0]['order_item_id'])
    assert detail(admin)['panels'][0]['status'] == 'COMPLETED'
    finish(admin, row['items'][2]['order_item_id'])
    after = detail(admin)
    assert after['status'] == 'COMPLETED' and after['panels'][1]['status'] == 'CANCELLED'
    assert after['items'][1]['status'] == 'CANCELLED'


def test_completion_helpers_never_complete_empty_sets_or_reactivate_cancelled(admin):
    row = order(admin, panel_ids=[1], test_ids=[])
    with admin.factory.begin() as db:
        for item in db.scalars(select(LabOrderItem)):
            item.status = 'CANCELLED'
        db.flush()
        service.recalculate_panel(db, row['panels'][0]['order_panel_id'])
        service.recalculate_order(db, db.get(LabOrder, 1))
        db.flush()
        assert db.get(LabOrder, 1).status == db.get(OrderPanel, 1).status == 'REQUESTED'
        db.get(LabOrder, 1).status = db.get(OrderPanel, 1).status = 'CANCELLED'
        db.flush()
        service.recalculate_panel(db, 1)
        service.recalculate_order(db, db.get(LabOrder, 1))
    assert detail(admin)['status'] == detail(admin)['panels'][0]['status'] == 'CANCELLED'
    assert service.progress_status([]) == 'REQUESTED'


def test_order_results_pagination_and_no_unrelated_results(admin):
    row = order(admin)
    rows = [result(admin, item['order_item_id']) for item in row['items']]
    other = requested(admin)
    result(admin, other['items'][0]['order_item_id'])
    page = call(admin, 'GET', '/lab-orders/1/results?page=2&page_size=2').json()
    assert page == {'items': rows[2:], 'page': 2, 'page_size': 2, 'total': 4}
    assert call(admin, 'GET', '/lab-orders/1/results?page=999').json()['items'] == []
    for query in ('page=0', 'page_size=0', 'page_size=101'):
        assert call(admin, 'GET', '/lab-orders/1/results?' + query).status_code == 422


@pytest.mark.parametrize('action,target', [
    ('create', 'lab_result_item'), ('create', 'audit_log'), ('create', 'commit'),
    ('patch', 'lab_result_item'), ('patch', 'audit_log'), ('patch', 'commit'),
    ('review', 'audit_log'), ('review', 'commit'),
    ('verify', 'lab_order_item'), ('verify', 'order_panel'), ('verify', 'lab_order'),
    ('verify', 'audit_log'), ('verify', 'commit'),
])
def test_result_transactions_rollback_all_rows_and_audits(admin, action, target):
    row = order(admin, panel_ids=[2], test_ids=[])
    sid = received(admin, row)
    if action != 'create':
        result(admin, specimen_id=sid)
    if action == 'verify':
        advance(admin, 'review')
    before = detail(admin)
    previous = read(admin) if action != 'create' else None
    with admin.factory() as db:
        audits = count(db, AuditLog)
    def fail(*args):
        if target == 'commit' or args[2].startswith(('INSERT INTO ' + target + ' ', 'UPDATE ' + target + ' ')):
            raise SQLAlchemyError('private laboratory value')
    host, hook = (admin.factory, 'before_commit') if target == 'commit' else (admin.engine, 'before_cursor_execute')
    event.listen(host, hook, fail)
    try:
        if action == 'create':
            response = enter(admin, specimen_id=sid)
        elif action == 'patch':
            response = call(admin, 'PATCH', '/results/1', {'result_value': '22'})
        else:
            response = advance(admin, action)
        assert response.status_code == 503 and 'private' not in response.text
    finally:
        event.remove(host, hook, fail)
    assert detail(admin) == before
    if previous:
        assert read(admin) == previous
    with admin.factory() as db:
        assert count(db, AuditLog) == audits and count(db, LabResultItem) == int(previous is not None)


def test_audit_privacy_and_permissions_bootstrap(admin, caplog):
    requested(admin)
    row = result(admin, result_value='123456.789', remarks='private-laboratory-remarks')
    call(admin, 'PATCH', '/results/1', {'result_value': '123457.890', 'remarks': 'private-correction'})
    advance(admin, 'review')
    advance(admin, 'verify')
    bootstrap_permissions.main()
    bootstrap_permissions.main()
    with admin.factory() as db:
        assert ensure_permissions(db) == []
        assert set(db.scalars(select(Permission.permission_code))) >= {entry[3] for entry in ENDPOINTS}
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action.like('LAB_RESULT_%')).order_by(AuditLog.audit_id)))
        assert [log.action for log in logs] == ['LAB_RESULT_CREATE', 'LAB_RESULT_UPDATE', 'LAB_RESULT_REVIEW', 'LAB_RESULT_VERIFY']
        assert all(log.record_id == row['result_item_id'] and log.user_id == 1 and log.created_at for log in logs)
        assert logs[1].new_value['changed_fields'] == ['remarks', 'result_value']
        content = json.dumps([{'old': log.old_value, 'new': log.new_value} for log in logs]) + caplog.text
    for sensitive in ['123456.789', '123457.890', 'private-', PASSWORD, *admin.client.cookies.values()]:
        assert sensitive not in content
    assert detail(admin)['diagnosis'] is None


def test_openapi_results_scope_and_no_schema_change():
    from app.main import app
    paths = app.openapi()['paths']
    operations = [(path, method) for path, methods in paths.items() for method, operation in methods.items()
                  if 'Laboratory Results' in operation.get('tags', [])]
    assert len(operations) == 6
    assert not any(method == 'delete' or 'report' in path for path, method in operations)
    assert 'password_hash' not in json.dumps(app.openapi())
    for path, method in operations:
        assert paths[path][method]['security']
    assert not any(tuple(c.columns.keys()) == ('order_item_id',) for c in LabResultItem.__table__.constraints
                   if c.__class__.__name__ == 'UniqueConstraint')


@pytest.mark.parametrize('field,value', [
    ('reviewed_by_user_id', None), ('reviewed_at', None),
    ('verified_by_user_id', 1), ('verified_at', datetime(2026, 1, 1)),
])
def test_inconsistent_review_provenance_cannot_be_verified(admin, field, value):
    requested(admin)
    result(admin)
    advance(admin, 'review')
    with admin.factory.begin() as db:
        setattr(db.get(LabResultItem, 1), field, value)
    assert advance(admin, 'verify').status_code == 409
    assert detail(admin)['status'] == 'IN_PROGRESS'
    assert read(admin)['status'] == 'REVIEWED'
