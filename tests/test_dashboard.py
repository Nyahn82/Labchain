"""Aggregate overview over synthetic SQLite, through real cookie authentication."""
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.api import dashboard
from app.models import (
    AuditLog, FacilityProfile, LabDepartment, LabOrder, LabReport, LabResultItem,
    Patient, PatientAccountLink, Permission, Role, RolePermission, SampleType,
    Specimen, TestCatalog as Catalog, UserAccount, UserRole,
)
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from app.services import dashboard_service
from test_phase_3a_authentication_rbac import env, password_hash, login

PATH = '/api/v1/dashboard/overview'
PERMISSIONS = ['PATIENT_READ', 'LAB_ORDER_READ', 'SPECIMEN_READ', 'LAB_RESULT_READ', 'REPORT_READ']


@pytest.fixture
def overview_api(env):
    env.app.include_router(dashboard.router, prefix='/api/v1')
    with env.factory.begin() as db:
        ensure_permissions(db)
    return env


def grant(api, permissions):
    with api.factory.begin() as db:
        for permission in permissions:
            identifier = db.scalar(select(Permission.permission_id).where(Permission.permission_code == permission))
            db.add(RolePermission(role_id=1, permission_id=identifier))


def seed(api):
    from app.models import LabOrderItem
    with api.factory.begin() as db:
        db.add(Patient(patient_id=1, patient_code='LEGACY-PRIVATE', first_name='SensitiveName', last_name='SensitiveSurname'))
        db.add(LabDepartment(department_id=1, department_code='LEGACY-DEP', department_name='Synthetic'))
        db.add(FacilityProfile(facility_id=1, facility_name='Synthetic'))
        db.add(SampleType(sample_type_id=1, sample_name='Synthetic'))
        db.flush()
        db.add(Catalog(test_id=1, test_code='LEGACY-TST', test_name='PrivateTest', department_id=1, result_type='TEXT'))
        for i, status in enumerate(['REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'], 1):
            db.add(LabOrder(order_id=i, order_code=f'PRIVATE-ORDER-{i}', patient_id=1,
                            order_date=utc_now(), priority='ROUTINE', status=status))
        db.flush()
        db.add(LabOrderItem(order_item_id=1, order_id=1, test_id=1, status='REQUESTED'))
        for i, status in enumerate(['PENDING', 'COLLECTED', 'RECEIVED', 'REJECTED', 'PROCESSED'], 1):
            db.add(Specimen(specimen_id=i, specimen_code=f'PRIVATE-SPEC-{i}', order_id=1,
                            sample_type_id=1, specimen_status=status))
        db.flush()
        for i, status in enumerate(['DRAFT', 'REVIEWED', 'VERIFIED'], 1):
            db.add(LabResultItem(result_item_id=i, order_item_id=1, result_value='PRIVATE-RESULT',
                                 status=status, encoded_by_user_id=1, encoded_at=utc_now()))
        for i, status in enumerate(['GENERATED', 'APPROVED', 'RELEASED', 'REVOKED'], 1):
            db.add(LabReport(report_id=i, report_code=f'PRIVATE-REPORT-{i}', order_id=1, facility_id=1,
                             version_no=i, report_status=status, generated_by_user_id=1, generated_at=utc_now()))


def test_requires_authentication_and_never_caches(overview_api):
    response = overview_api.client.get(PATH)
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'


def test_no_permissions_returns_no_counts(overview_api):
    seed(overview_api)
    assert login(overview_api).status_code == 200
    response = overview_api.client.get(PATH)
    assert response.status_code == 200
    assert set(response.json()) == {'generated_at'}


@pytest.mark.parametrize('permission,key', zip(PERMISSIONS, ['patients', 'orders', 'specimens', 'results', 'reports']))
def test_each_permission_only_exposes_its_aggregate(overview_api, permission, key):
    seed(overview_api)
    grant(overview_api, [permission])
    assert login(overview_api).status_code == 200
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement.lower())
    event.listen(overview_api.engine, 'before_cursor_execute', capture)
    try:
        response = overview_api.client.get(PATH)
    finally:
        event.remove(overview_api.engine, 'before_cursor_execute', capture)
    assert response.status_code == 200
    assert set(response.json()) == {'generated_at', key}
    assert 'PRIVATE' not in response.text and 'SensitiveName' not in response.text
    assert not any('result_value' in statement or 'first_name' in statement for statement in statements)
    grouped = [sql for sql in statements if 'group by' in sql]
    assert len(grouped) == (0 if key == 'patients' else 1)


def test_real_counts_include_all_statuses_and_report_versions(overview_api):
    seed(overview_api)
    grant(overview_api, PERMISSIONS)
    login(overview_api)
    response = overview_api.client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body['patients'] == 1
    assert body['generated_at'].endswith('Z')
    for key, total in [('orders', 4), ('specimens', 5), ('results', 3), ('reports', 4)]:
        assert body[key]['total'] == total
        assert len(body[key]['statuses']) == total
        assert set(body[key]['statuses'].values()) == {1}
    assert response.headers['cache-control'] == 'no-store'
    assert 'PRIVATE' not in response.text
    assert 'Sensitive' not in response.text


def test_zeroes_come_from_empty_database_and_read_does_not_write(overview_api):
    grant(overview_api, PERMISSIONS)
    login(overview_api)
    with overview_api.factory() as db:
        before = list(db.scalars(select(AuditLog.audit_id)))
    body = overview_api.client.get(PATH).json()
    assert body['patients'] == 0
    for key in ['orders', 'specimens', 'results', 'reports']:
        assert body[key]['total'] == 0
        assert set(body[key]['statuses'].values()) == {0}
    with overview_api.factory() as db:
        assert list(db.scalars(select(AuditLog.audit_id))) == before


def test_admin_uses_existing_permission_bypass(overview_api):
    with overview_api.factory.begin() as db:
        db.add(Role(role_id=2, role_code='SYSTEM_ADMIN', role_name='Admin', is_active=True))
        db.flush()
        db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    login(overview_api)
    assert set(overview_api.client.get(PATH).json()) == {'generated_at', 'patients', 'orders', 'specimens', 'results', 'reports'}


def test_revoked_permission_is_applied_on_next_request(overview_api):
    grant(overview_api, ['REPORT_READ'])
    login(overview_api)
    assert 'reports' in overview_api.client.get(PATH).json()
    with overview_api.factory.begin() as db:
        db.get(Role, 1).is_active = False
    assert set(overview_api.client.get(PATH).json()) == {'generated_at'}


def test_patient_association_cannot_read_global_counts_even_with_permissions(overview_api):
    seed(overview_api)
    grant(overview_api, PERMISSIONS)
    login(overview_api)
    with overview_api.factory.begin() as db:
        db.add(PatientAccountLink(user_id=1, patient_id=1))
    response = overview_api.client.get(PATH)
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'no-store'


def test_database_failure_is_redacted_and_not_reported_as_zero(overview_api, monkeypatch):
    login(overview_api)
    def fail(*args):
        raise OperationalError('PRIVATE SQL', {'patient': 'PRIVATE'}, Exception('PRIVATE'))
    monkeypatch.setattr(dashboard_service, 'overview', fail)
    response = overview_api.client.get(PATH)
    assert response.status_code == 503
    assert 'PRIVATE' not in response.text
    assert 'patients' not in response.json()
    assert response.headers['cache-control'] == 'no-store'


def test_inactive_account_is_denied(overview_api):
    login(overview_api)
    with overview_api.factory.begin() as db:
        db.get(UserAccount, 1).account_status = 'SUSPENDED'
    assert overview_api.client.get(PATH).status_code == 401


def test_patient_role_cannot_use_admin_bypass(overview_api, monkeypatch):
    from app.config import settings
    login(overview_api)
    # Reach the overview's staff guard rather than the earlier patient MFA guard.
    monkeypatch.setattr(settings, 'patient_mfa_required', False)
    with overview_api.factory.begin() as db:
        db.add_all([
            Role(role_id=2, role_code='PATIENT', role_name='Patient', is_active=True),
            Role(role_id=3, role_code='SYSTEM_ADMIN', role_name='Admin', is_active=True),
        ])
        db.flush()
        db.add_all(UserRole(user_id=1, role_id=role, assigned_at=utc_now()) for role in [2, 3])
    response = overview_api.client.get(PATH)
    assert response.status_code == 403
    assert response.json()['detail'] == 'Staff administration access required.'
    assert response.headers['cache-control'] == 'no-store'


def test_overview_is_registered_in_application_openapi():
    from app.main import app
    document = app.openapi()
    operations = document['paths'][PATH]
    assert set(operations) == {'get'}
    reference = operations['get']['responses']['200']['content']['application/json']['schema']['$ref']
    schema = document['components']['schemas'][reference.rsplit('/', 1)[1]]
    assert set(schema['properties']) == {'generated_at', 'patients', 'orders', 'specimens', 'results', 'reports'}
    assert schema['required'] == ['generated_at']
    assert reference == '#/components/schemas/DashboardOverview'
    monitor_schema = document['paths']['/api/v1/admin/blockchain/overview']['get']['responses']['200']['content']['application/json']['schema']
    assert monitor_schema['$ref'] == '#/components/schemas/Overview'
