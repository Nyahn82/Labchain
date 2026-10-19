"""Focused corrections tested through authenticated APIs against synthetic SQLite."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.api import dashboard
from app.models import (AuthSession, LabOrderItem, LabResultItem, LoginLog, Patient,
    PatientAccountLink, PatientActivationToken, Permission, RejectionReason, ReportSignatory,
    Role, RolePermission, Staff, StaffAccountLink, UserAccount, UserRole)
from app.models.service_observation import ServiceObservation
from app.services import dashboard_service, patient_activation_service
from app.services.activity_observation_service import record_worker
from app.services.auth_service import utc_now
from test_starter_catalog import (env, password_hash, lab_api, workflow_api, results_api,
    reports_api, admin, api, call, create, order)
from test_phase_3a_authentication_rbac import login
from test_phase_5a_reports import generated, assigned, sign


def overview(api):
    api.app.include_router(dashboard.router, prefix='/api/v1')
    response = call(api, 'GET', '/dashboard/overview')
    assert response.status_code == 200, response.text
    return response.json()


def restrict(api, *codes):
    with api.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.user_id == 1, UserRole.role_id == 2))
        db.execute(delete(RolePermission).where(RolePermission.role_id == 1))
        for code in codes:
            identifier = db.scalar(select(Permission.permission_id).where(Permission.permission_code == code))
            assert identifier is not None
            db.add(RolePermission(role_id=1, permission_id=identifier))


def test_activity_is_observed_throttled_and_does_not_extend_session(api):
    with api.factory() as db:
        before = db.scalar(select(AuthSession))
        assert before.last_activity_at is None
        expiry = before.expires_at
    assert call(api, 'GET', '/auth/me').status_code == 200
    with api.factory() as db:
        first = db.scalar(select(AuthSession)).last_activity_at
        assert first is not None
    assert call(api, 'GET', '/auth/me').status_code == 200
    with api.factory() as db:
        current = db.scalar(select(AuthSession))
        assert current.last_activity_at == first and current.expires_at == expiry
    with api.factory.begin() as db:
        db.scalar(select(AuthSession)).last_activity_at -= timedelta(minutes=2)
    assert call(api, 'GET', '/auth/me').status_code == 200
    with api.factory() as db:
        assert db.scalar(select(AuthSession)).last_activity_at >= first


def test_invalid_csrf_does_not_record_activity(api):
    response = api.client.post('/api/v1/facility-profile', json={'facility_name': 'Must not write'})
    assert response.status_code == 403
    with api.factory() as db:
        assert db.scalar(select(AuthSession)).last_activity_at is None


@pytest.mark.parametrize('defect', ['stale', 'expired', 'revoked', 'disabled', 'inactive_staff', 'patient_link', 'patient_role', 'future'])
def test_presence_excludes_ineligible_sessions_and_deduplicates(api, defect):
    now = utc_now()
    with api.factory.begin() as db:
        session = db.scalar(select(AuthSession))
        session.last_activity_at = now
        db.add(AuthSession(user_id=1, token_hash='f'*64, csrf_token_hash='e'*64,
            created_at=now, expires_at=now+timedelta(hours=1), last_activity_at=now))
    with api.factory() as db:
        assert dashboard_service.overview(db, 1)['presence']['recently_active'] == 1
    with api.factory.begin() as db:
        for session in db.scalars(select(AuthSession)):
            if defect == 'stale': session.last_activity_at = now-timedelta(minutes=6)
            if defect == 'expired': session.expires_at = now-timedelta(seconds=1)
            if defect == 'revoked': session.revoked_at = now
            if defect == 'future': session.last_activity_at = now+timedelta(minutes=1)
        if defect == 'disabled': db.get(UserAccount, 1).account_status = 'DISABLED'
        if defect == 'inactive_staff': db.get(Staff, 1).is_active = False
        if defect == 'patient_link': db.add(PatientAccountLink(patient_id=1, user_id=1))
        if defect == 'patient_role':
            db.add(Role(role_id=99, role_code='PATIENT', role_name='Patient', is_active=True))
            db.flush()
            db.add(UserRole(user_id=1, role_id=99, assigned_at=now))
    with api.factory() as db:
        assert dashboard_service.overview(db, 1)['presence']['recently_active'] == 0


def test_failed_logins_are_windowed_include_unknown_accounts_and_do_not_count_audits(api):
    now = utc_now()
    with api.factory.begin() as db:
        for hours, status, user in [(1, 'FAILED', None), (2, 'FAILED', 1), (25, 'FAILED', None), (-1, 'FAILED', 1), (1, 'SUCCESS', 1)]:
            db.add(LoginLog(user_id=user, username_attempted='synthetic', login_time=now-timedelta(hours=hours), status=status))
    body = overview(api)
    assert body['failed_logins']['count'] == 2
    assert body['accounts'] == {'active': 1, 'suspended': 0}
    assert body['presence']['recently_active'] == 1
    restrict(api, 'PATIENT_READ')
    body = call(api, 'GET', '/dashboard/overview').json()
    assert set(body) == {'generated_at', 'patients'}


def test_signing_stages_partition_reports_and_drilldown(api):
    generated(api)
    assert overview(api)['signing'] == {'unassigned': 1, 'awaiting_signature': 0, 'awaiting_approval': 0}
    assigned(api)
    assigned(api, staff_id=2)
    assert call(api, 'GET', '/dashboard/overview').json()['signing']['awaiting_signature'] == 1
    assert sign(api).status_code == 200
    assert call(api, 'GET', '/dashboard/overview').json()['signing']['awaiting_signature'] == 1
    with api.factory.begin() as db:
        for assignment in db.scalars(select(ReportSignatory)):
            assignment.signed_at = utc_now()  # synthetic aggregate fixture, not a signing bypass in application
    assert call(api, 'GET', '/dashboard/overview').json()['signing'] == {'unassigned': 0, 'awaiting_signature': 0, 'awaiting_approval': 1}
    assert call(api, 'GET', '/reports?signing_stage=awaiting_approval').json()['total'] == 1
    assert call(api, 'GET', '/reports?signing_stage=awaiting_signature').json()['total'] == 0
    assert call(api, 'GET', '/reports?signing_stage=unassigned').json()['total'] == 0
    assert call(api, 'GET', '/reports?signing_stage=invalid').status_code == 422


def test_worker_unknown_fresh_stale_stopped_and_unhealthy(api):
    assert overview(api)['services'][-1]['status'] == 'UNKNOWN'
    for status in ['HEALTHY', 'STOPPED', 'UNHEALTHY']:
        record_worker(api.factory, status)
        assert call(api, 'GET', '/dashboard/overview').json()['services'][-1]['status'] == status
    with api.factory.begin() as db:
        db.get(ServiceObservation, 'blockchain_worker').checked_at -= timedelta(minutes=6)
    assert call(api, 'GET', '/dashboard/overview').json()['services'][-1]['status'] == 'STALE'
    with api.factory.begin() as db:
        db.get(ServiceObservation, 'blockchain_worker').checked_at = utc_now()+timedelta(minutes=1)
    assert call(api, 'GET', '/dashboard/overview').json()['services'][-1]['status'] == 'UNKNOWN'


def test_activation_sql_matches_all_states_and_filters_before_paging(api):
    from app.api import patients
    api.app.include_router(patients.router, prefix='/api/v1')
    now = utc_now()
    with api.factory.begin() as db:
        for i in range(10, 36):
            db.add(Patient(patient_id=i, patient_code=f'SYN-{i:03}', first_name='Same', last_name='Name'))
        db.flush()
        # Active invitation, expired boundary, revoked, consumed anomaly, linked wins over consumed.
        for i in range(11, 16):
            db.add(PatientActivationToken(patient_id=i, token_hash=str(i)*32, created_at=now, issued_by_user_id=1,
                expires_at=now if i == 12 else now+timedelta(hours=1),
                revoked_at=now if i == 13 else None, used_at=now if i in {14, 15} else None))
        db.add(PatientAccountLink(patient_id=15, user_id=1))
    # Use a distinct non-patient administrator for directory access.
    with api.factory.begin() as db:
        db.add(UserAccount(user_id=10, username='synthetic-portal', password_hash='not-a-login', account_status='ACTIVE'))
        db.flush()
        db.get(PatientAccountLink, 15).user_id = 10
    with api.factory() as db:
        expected = patient_activation_service.activation_states(db, range(10, 36))
    assert set(expected.values()) == {'NOT_ACTIVATED', 'TOKEN_ACTIVE', 'TOKEN_EXPIRED', 'TOKEN_REVOKED', 'REVIEW_REQUIRED', 'ACTIVATED'}
    for state in set(expected.values()):
        response = call(api, 'GET', f'/patients?activation_state={state}&search=SYN-&page_size=100')
        assert response.status_code == 200, response.text
        rows = response.json()
        assert {r['patient_id'] for r in rows['items']} == {i for i, s in expected.items() if s == state}
        assert rows['total'] == len(rows['items'])
    path = '/patients?activation_group=NOT_ACTIVATED&search=Same&sort_by=name&sort_direction=desc&page_size=10'
    first = call(api, 'GET', path).json()
    second = call(api, 'GET', path+'&page=2').json()
    assert first['total'] == second['total'] == 25
    assert [r['patient_id'] for r in first['items']] == list(range(10, 15))+list(range(16, 21))
    assert not {r['patient_id'] for r in first['items']} & {r['patient_id'] for r in second['items']}
    assert overview(api)['activation'] == {'not_activated': 27, 'review_required': 1}
    restrict(api, 'PATIENT_READ')
    for suffix in ['activation_group=NOT_ACTIVATED', 'activation_state=ACTIVATED', 'sort_by=activation']:
        assert call(api, 'GET', '/patients?'+suffix).status_code == 403
    assert call(api, 'GET', '/patients?sort_by=name%3BDROP').status_code == 422
    assert call(api, 'GET', '/patients?sort_direction=bad').status_code == 422


def test_reject_permission_can_only_read_active_reasons_without_management(api):
    with api.factory.begin() as db:
        db.add(RejectionReason(rejection_reason_id=90, reason_code='SYN-INACTIVE', reason_name='Inactive synthetic', is_active=False))
    restrict(api, 'SPECIMEN_REJECT')
    for suffix in ['', '?is_active=false', '?is_active=true']:
        response = call(api, 'GET', '/lab/rejection-reasons'+suffix)
        assert response.status_code == 200
        assert all(r['is_active'] for r in response.json()['items'])
        assert 'SYN-INACTIVE' not in response.text
    assert call(api, 'POST', '/lab/rejection-reasons', {'reason_name': 'Unauthorized', 'reason_code': 'NO'}).status_code == 403
    assert call(api, 'PATCH', '/lab/rejection-reasons/90', {'is_active': True}).status_code == 403


def test_result_occupancy_spans_pages_and_requires_result_read(api):
    requested = order(api, panel_ids=[], test_ids=[1])
    with api.factory.begin() as db:
        for i in range(20, 42):
            db.add(LabOrderItem(order_item_id=i, order_id=requested['order_id'], test_id=1, status='IN_PROGRESS'))
        db.flush()
        for i in range(20, 42):
            db.add(LabResultItem(order_item_id=i, result_value='1', encoded_by_user_id=1, encoded_at=utc_now(), status='DRAFT'))
    body = call(api, 'GET', '/lab-orders/1/results?page_size=20').json()
    assert len(body['items']) == 20 and body['total'] == 22
    assert set(body['occupied_item_ids']) == set(range(20, 42))
    restrict(api, 'LAB_ORDER_READ')
    assert call(api, 'GET', '/lab-orders/1/results').status_code == 403
