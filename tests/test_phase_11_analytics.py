"""Phase 11 only: rich synthetic SQLite fixtures and private HTTPS boundaries."""
from datetime import datetime, timedelta
import json
import pytest
from sqlalchemy import select, event
from app.api import analytics
from app.models import (
    Patient, LabOrder, LabOrderItem, OrderPanel, TestCatalog as Catalog, TestPanel as Panel, LabDepartment,
    Specimen, SpecimenRejection, RejectionReason, LabResultItem, LabReport, ReportResultItem, FacilityProfile,
    RequestingPhysician, ReferringFacility, LabPayment, LoginLog, AuthSession, BlockchainEvent, BlockchainNode,
    Staff, StaffAccountLink, PatientAccountLink, Role, UserRole, RolePermission, Permission, UserAccount,
)
from app.services.auth_service import utc_now
from app.services.permission_catalog import ensure_permissions
from app.schemas.analytics import AnalyticsQuery
from test_phase_3a_authentication_rbac import env, password_hash, login

ROOT = '/api/v1/admin/analytics/'
RANGE = '?date_from=2026-10-01&date_to=2026-10-07'
SECTIONS = ['overview','patients','orders','tests','specimens','reports','operations','system']
D = datetime.fromisoformat


@pytest.fixture
def api(env):
    env.app.include_router(analytics.router, prefix='/api/v1')
    with env.factory.begin() as db:
        ensure_permissions(db)
        db.add(Role(role_id=2, role_code='SYSTEM_ADMIN', role_name='Administrator', is_active=True))
        db.flush(); db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    assert login(env).status_code == 200
    return env


@pytest.fixture
def rich(api):
    with api.factory.begin() as db:
        for i, created in [(1,'2026-09-01'),(2,'2026-10-01'),(3,'2026-08-01'),(4,'2026-10-08'),(5,'2026-10-07T23:59:59')]:
            db.add(Patient(patient_id=i, patient_code=f'PRIVATE-{i}', first_name='PRIVATE-PATIENT', last_name='PRIVATE-NAME',
                address='PRIVATE-ADDRESS', email='private@example.invalid', created_at=D(created)))
        db.add(FacilityProfile(facility_id=1, facility_name='Issuing test facility'))
        db.add(ReferringFacility(referring_facility_id=1, facility_name='Referral Alpha', contact_number='PRIVATE-PHONE'))
        db.flush()
        db.add(RequestingPhysician(physician_id=1, first_name='Doctor', last_name='Alpha', referring_facility_id=1, contact_number='PRIVATE-PHONE'))
        db.add(RequestingPhysician(physician_id=2, first_name='Doctor', last_name='Direct'))
        for i in (1,2):
            db.add(LabDepartment(department_id=i, department_code=f'D{i}', department_name=f'Department {i}'))
        db.add(Staff(staff_id=1, staff_code='STAFF', first_name='PRIVATE-STAFF', last_name='NAME'))
        db.flush()
        db.add(StaffAccountLink(staff_id=1, user_id=1))
        for i in (1,2):
            db.add(Catalog(test_id=i, test_code=f'T{i}', test_name=f'Test {i}', department_id=i, result_type='NUMERIC'))
        db.add(Panel(panel_id=1, panel_code='PANEL', panel_name='Panel Alpha'))
        from app.models import SampleType
        db.add(SampleType(sample_type_id=1, sample_name='Synthetic blood'))
        db.add_all([RejectionReason(rejection_reason_id=1, reason_code='CLOT', reason_name='Clotted'),
                    RejectionReason(rejection_reason_id=2, reason_code='VOLUME', reason_name='Low volume')])
        db.flush()
        orders = [(1,1,'2026-09-25T10:00','COMPLETED',1), (2,1,'2026-10-01T10:00','COMPLETED',1),
            (3,1,'2026-10-02T11:00','IN_PROGRESS',1), (4,2,'2026-10-05T09:00','COMPLETED',None),
            (5,3,'2026-10-07T12:00','CANCELLED',2), (6,3,'2026-10-08T00:00','REQUESTED',None),
            (7,3,'2026-09-01T12:00','CANCELLED',None), (8,2,'2026-10-07T23:59:59','REQUESTED',None)]
        for i, patient, created, status, physician in orders:
            db.add(LabOrder(order_id=i, order_code=f'O{i}', patient_id=patient, physician_id=physician, created_at=D(created),
                order_date=D(created), status=status, priority='ROUTINE', clinical_notes='PRIVATE-CLINICAL'))
        db.flush()
        db.add(OrderPanel(order_panel_id=1, order_id=2, panel_id=1, status='COMPLETED')); db.flush()
        for i, order, test, panel in [(1,2,1,1),(2,2,2,1),(3,3,1,None),(4,4,2,None),(5,5,1,None),(6,8,1,None),(7,1,2,None)]:
            db.add(LabOrderItem(order_item_id=i, order_id=order, test_id=test, order_panel_id=panel,
                status='CANCELLED' if order==5 else 'COMPLETED', created_at=D('2026-10-01')))
        specs = [(1,2,'2026-10-01T10:30','2026-10-01T11:00','2026-10-01T12:00','PROCESSED'),
                 (2,3,'2026-10-02T11:30','2026-10-02T12:00','2026-10-02T13:00','REJECTED'),
                 (3,4,'2026-10-05T09:30','2026-10-05T10:00',None,'COLLECTED'),
                 (4,8,'2026-10-07T23:59:59',None,None,'PENDING')]
        for i, order, created, collected, received, status in specs:
            db.add(Specimen(specimen_id=i, specimen_code=f'S{i}', order_id=order, sample_type_id=1,
                created_at=D(created), collected_at=D(collected) if collected else None, received_at=D(received) if received else None, specimen_status=status))
        db.flush()
        for i, specimen, reason, recollection in [(1,2,1,True),(2,2,2,False),(3,3,1,True)]:
            db.add(SpecimenRejection(specimen_rejection_id=i, specimen_id=specimen, rejection_reason_id=reason,
                recollection_required=recollection, rejected_by_user_id=1, rejected_at=D('2026-10-06T14:00'), details='PRIVATE-REASON'))
        for i, item, status, reviewed, verified in [(1,1,'VERIFIED','2026-10-01T14:00','2026-10-01T15:00'),
            (2,2,'REVIEWED','2026-10-01T14:30',None),(3,3,'DRAFT',None,None)]:
            db.add(LabResultItem(result_item_id=i, order_item_id=item, specimen_id=1 if i < 3 else 2, result_value='PRIVATE-RESULT',
                status=status, encoded_by_user_id=1, encoded_at=D('2026-10-01T13:00') if i<3 else D('2026-10-02T14:00'),
                reviewed_at=D(reviewed) if reviewed else None, verified_at=D(verified) if verified else None))
        db.flush()
        for i, order, generated, approved, released, revoked in [
            (1,2,'2026-10-01T16:00','2026-10-01T17:00','2026-10-02T10:00',None),
            (2,1,'2026-09-30T16:00','2026-10-01T09:00','2026-10-01T10:00','2026-10-03T11:00'),
            (3,4,'2026-10-05T12:00',None,None,None),
            (4,3,'2026-10-02T16:00','2026-10-02T17:00','2026-10-02T10:00',None)]:
            db.add(LabReport(report_id=i, report_code=f'R{i}', order_id=order, facility_id=1, version_no=1,
                report_status='REVOKED' if revoked else 'RELEASED' if released else 'GENERATED', generated_by_user_id=1,
                generated_at=D(generated), approved_at=D(approved) if approved else None, released_at=D(released) if released else None,
                revoked_at=D(revoked) if revoked else None, remarks='PRIVATE-REPORT'))
        db.flush()
        for i in (1,2):
            db.add(ReportResultItem(report_id=1, result_item_id=i, test_name_snapshot=f'Test {i}', result_value_snapshot='PRIVATE-SNAPSHOT', sort_order=i))
        for i, order, status, amount, recorded in [(1,2,'PENDING',100,'2026-10-01'),(2,2,'PAID',150,'2026-10-02'),(3,4,'FREE',0,'2026-10-05')]:
            db.add(LabPayment(payment_id=i, order_id=order, payment_status=status, amount=amount, recorded_at=D(recorded)))
        for i, status in enumerate(['SUCCESS','FAILED','SUCCESS'], 100):
            db.add(LoginLog(login_log_id=i, user_id=1 if i != 101 else None, username_attempted='PRIVATE-USERNAME',
                login_time=D('2026-10-02'), status=status, ip_address='192.0.2.199'))
        db.add(BlockchainNode(node_id=1, node_code='synthetic', port=7051)); db.flush()
        for i, status in enumerate(['CONFIRMED','PENDING','FAILED'], 1):
            # Core insertion creates synthetic evidence without invoking chaincode or production.
            db.execute(BlockchainEvent.__table__.insert().values(event_id=i, event_uuid=f'00000000-0000-4000-8000-{i:012d}',
                origin_node_id=1, entity_type='REPORT', entity_id=i, event_type='REPORT_RELEASED', record_hash='a'*64,
                event_status=status, deduplication_key=f'synthetic-{i}', entity_reference=f'00000000-0000-4000-9000-{i:012d}',
                canonical_payload='PRIVATE-PAYLOAD', created_at=D('2026-10-02T00:00'), occurred_at=D('2026-10-02T00:00'),
                next_attempt_at=D('2026-10-02T00:00'), confirmed_at=D('2026-10-02T00:02') if status=='CONFIRMED' else None,
                fabric_transaction_id='b'*64 if status=='CONFIRMED' else None, fabric_validation_code=0 if status=='CONFIRMED' else None))
    return api


def get(api, section, query=RANGE):
    result = api.client.get(ROOT+section+query)
    assert result.status_code == 200, result.text
    return result.json()


def metrics(data): return {m['key']:m for m in data['metrics']}
def breakdown(data, key): return next(b for b in data['breakdowns'] if b['key']==key)
def series(data, key): return next(b for b in data['series'] if b['key']==key)['points']


@pytest.mark.parametrize('section', SECTIONS)
def test_empty_sections_are_bounded_valid_and_private(api, section):
    data = get(api, section)
    assert data['range']['timezone']=='UTC'
    assert all(len(s['points']) <= 120 for s in data['series'])
    assert all(len(b['items']) <= 24 for b in data['breakdowns'])
    text = json.dumps(data)
    for forbidden in ('NaN','Infinity','patient_id','username','ip_address','user_agent','session_id','token_hash','record_hash','canonical_payload'):
        assert f'"{forbidden}"' not in text


@pytest.mark.parametrize('section', SECTIONS)
def test_rich_sections_no_phi_and_no_writes(rich, section):
    writes = []
    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE'}: writes.append(statement)
    event.listen(rich.engine, 'before_cursor_execute', observe)
    try: data = get(rich, section)
    finally: event.remove(rich.engine, 'before_cursor_execute', observe)
    assert not writes
    assert 'PRIVATE-' not in json.dumps(data)


def test_overview_definitions_and_comparison(rich):
    rows = metrics(get(rich, 'overview'))
    assert {key:rows[key]['value'] for key in ['new_patients','patients_served','returning_patients','orders','tests_requested','specimens_registered','reports_released']} == {
        'new_patients':2,'patients_served':2,'returning_patients':1,'orders':5,'tests_requested':6,'specimens_registered':4,'reports_released':3}
    assert rows['orders']['previous_value']==1 and rows['orders']['absolute_change']==4 and rows['orders']['percent_change']==400
    assert rows['new_patients']['percent_change'] is None
    assert rows['order_to_release']['value']==pytest.approx(3.5*86400)


def test_patient_bucket_distinctness_and_operational_return(rich):
    data = get(rich,'patients')
    assert sum(p['value'] for p in series(data,'patients_served')) == 4
    assert sum(p['value'] for p in series(data,'returning_patients')) == 3
    weekly = get(rich,'patients',RANGE+'&grain=week')
    assert [p['bucket'] for p in series(weekly,'patients_served')]==['2026-09-28','2026-10-05']
    assert [p['value'] for p in series(weekly,'returning_patients')]==[1,0]
    monthly=get(rich,'patients',RANGE+'&grain=month')
    assert series(monthly,'patients_served')[0]['value']==2
    assert series(monthly,'returning_patients')[0]['value']==1


def test_orders_and_test_panel_department_counts(rich):
    data=get(rich,'orders'); assert metrics(data)['cancellation_rate']['value']==20
    assert breakdown(data,'order_status')['total']==5
    data=get(rich,'tests')
    assert metrics(data)['tests_requested']['value']==6 and metrics(data)['panel_requests']['value']==1
    top=breakdown(data,'top_tests')['items']; assert [x['count'] for x in top]==[4,2]
    assert top[0]['code']=='T1' and top[0]['department']=='Department 1'
    departments=breakdown(data,'departments')['items']
    assert departments[0]['count']==4 and departments[0]['drafted']==1 and departments[0]['verified']==1
    assert breakdown(get(rich,'tests',RANGE+'&top_n=1'),'top_tests')['other_count']==2


def test_specimen_events_ratios_and_reasons(rich):
    data=get(rich,'specimens'); m=metrics(data)
    assert m['registered']['value']==4 and m['collected']['value']==3 and m['received']['value']==2
    assert m['rejected']['value']==2 and m['rejection_events']['value']==3
    assert m['rejections_per_100_registered']['value']==50
    assert m['recollection_required']['value']==2 and m['recollection_rate']['value']==66.67
    assert breakdown(data,'rejection_reasons')['items'][0]['label']=='Clotted'
    assert breakdown(data,'rejection_reasons')['items'][0]['count']==2


def test_report_event_dates_and_invalid_tat(rich):
    data=get(rich,'reports'); m=metrics(data)
    assert [m[k]['value'] for k in ['generated','approved','released','revoked']]==[3,3,3,1]
    assert m['results_reviewed']['value']==2 and m['results_verified']['value']==1
    t={s['key']:s for s in data['turnaround']}
    assert t['order_to_release']['sample_count']==2 and t['order_to_release']['excluded_count']==2
    assert t['order_to_release']['average_seconds']==pytest.approx(3.5*86400)
    assert t['collection_to_receipt']['sample_count']==2 and t['collection_to_receipt']['excluded_count']==1
    assert t['review_to_approval']['sample_count']==1 and t['review_to_approval']['average_seconds']==9000


def test_referrals_peaks_and_latest_payment_not_history_sum(rich):
    data=get(rich,'operations')
    assert breakdown(data,'facilities')['total']==5
    unspecified=next(x for x in breakdown(data,'facilities')['items'] if x['key']=='unspecified')
    assert unspecified['count']==3
    assert len(breakdown(data,'weekday')['items'])==7 and len(breakdown(data,'hour')['items'])==24
    assert sum(x['count'] for x in breakdown(data,'hour')['items'])==5
    assert metrics(data)['recorded_amount']['value']==150
    payments={x['key']:x['count'] for x in breakdown(data,'payments')['items']}
    assert payments['PAID']==1 and payments['PENDING']==0 and payments['NOT_RECORDED']==3


def test_system_aggregates_only(rich):
    data=get(rich,'system'); m=metrics(data)
    assert m['login_success']['value']>=2 and m['login_failed']['value']==1
    assert m['anchors_created']['value']==3 and m['confirmation_rate']['value']==33.33
    assert data['turnaround'][0]['average_seconds']==120
    assert 'b'*64 not in json.dumps(data)


@pytest.mark.parametrize('query', ['','?date_from=2026-10-02&date_to=2026-10-01','?date_from=bad&date_to=2026-10-01',
    '?date_from=1900-01-01&date_to=2026-10-01','?date_from=2020-01-01&date_to=2040-01-01',
    '?date_from=2026-01-01&date_to=2026-10-01&grain=day', RANGE+'&top_n=21', RANGE+'&grain=sql', RANGE+'&extra=1'])
def test_invalid_bounded_inputs(api,query):
    assert api.client.get(ROOT+'overview'+query).status_code==422


@pytest.mark.parametrize('grain', ['day','week','month','quarter','year','auto'])
def test_all_grains(rich,grain):
    data=get(rich,'orders',RANGE+'&grain='+grain)
    assert sum(p['value'] for p in series(data,'orders'))==5


@pytest.mark.parametrize('end,expected', [('2026-01-31','day'),('2026-06-01','week'),('2027-12-01','month'),('2029-01-01','quarter'),('2032-01-01','year')])
def test_auto_grain(end,expected):
    assert AnalyticsQuery(date_from='2026-01-01',date_to=end).resolved_grain==expected


@pytest.mark.parametrize('section', SECTIONS)
def test_rbac_and_patient_exclusion(api,section,monkeypatch):
    from app.config import settings
    api.client.cookies.clear()
    assert api.client.get(ROOT+section+RANGE).status_code==401
    with api.factory.begin() as db:
        db.query(UserRole).filter(UserRole.role_id==2).delete()
    assert login(api).status_code==200
    assert api.client.get(ROOT+section+RANGE).status_code==403
    with api.factory.begin() as db:
        pid=db.scalar(select(Permission.permission_id).where(Permission.permission_code=='ANALYTICS_VIEW'))
        db.add(RolePermission(role_id=1,permission_id=pid))
    assert api.client.get(ROOT+section+RANGE).status_code==200
    monkeypatch.setattr(settings,'patient_mfa_required',False)
    with api.factory.begin() as db:
        db.add(Role(role_id=3,role_code='PATIENT',role_name='Patient')); db.flush()
        db.add(UserRole(role_id=3,user_id=1,assigned_at=utc_now()))
    assert api.client.get(ROOT+section+RANGE).status_code==403


def test_monthly_and_quarterly_history_and_equal_day_comparison(rich):
    data=get(rich,'patients','?date_from=2026-08-01&date_to=2026-10-31&grain=month')
    assert [p['value'] for p in series(data,'new_patients')]==[1,1,3]
    assert [p['value'] for p in series(data,'patients_served')]==[0,1,3]
    assert [p['value'] for p in series(data,'returning_patients')]==[0,0,1]
    info=get(rich,'orders','?date_from=2026-10-01&date_to=2026-10-31')['range']
    assert info['previous_date_from']=='2026-08-31' and info['previous_date_to']=='2026-09-30'
    quarterly=get(rich,'orders','?date_from=2026-08-01&date_to=2026-10-31&grain=quarter')
    assert [p['value'] for p in series(quarterly,'orders')]==[2,6]


@pytest.mark.parametrize('value', ['2026-10-01T00:00:00Z','2026-10-01T00:00:00+08:00','1790812800'])
def test_timezone_is_explicit_calendar_utc_not_datetime_coercion(api,value):
    response=api.client.get(ROOT+'patients',params={'date_from':value,'date_to':'2026-10-07'})
    assert response.status_code==422


def test_missing_tat_and_zero_denominators(api):
    reports=get(api,'reports')
    assert all(t['average_seconds'] is None and t['sample_count']==0 for t in reports['turnaround'])
    assert metrics(get(api,'specimens'))['recollection_rate']['value'] is None
    assert metrics(get(api,'orders'))['cancellation_rate']['value'] is None
    assert metrics(get(api,'overview'))['orders']['percent_change'] is None


def test_legacy_patient_registration_is_not_a_returning_encounter(rich):
    data=metrics(get(rich,'overview','?date_from=2026-10-08&date_to=2026-10-08'))
    # Patient 3 was registered in August, but has only cancelled earlier orders.
    assert data['patients_served']['value']==1 and data['returning_patients']['value']==0


def test_query_count_does_not_scale_with_returned_entities(rich):
    from app.services import analytics_service
    selects=[]
    def observe(conn,cursor,statement,params,context,many):
        if statement.startswith('SELECT'): selects.append(statement)
    event.listen(rich.engine,'before_cursor_execute',observe)
    try:
        with rich.factory() as db:
            analytics_service.tests(db,AnalyticsQuery(date_from='2026-10-01',date_to='2026-10-07'))
    finally: event.remove(rich.engine,'before_cursor_execute',observe)
    assert len(selects)==6  # fixed aggregate queries, no per-patient/test fetches
    assert all('COUNT' in sql.upper() or 'SUM' in sql.upper() for sql in selects)
