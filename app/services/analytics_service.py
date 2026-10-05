"""Read-only SQL aggregates. Python only assembles bounded grouped results."""
from datetime import datetime, time, timedelta
from sqlalchemy import String, cast, and_, case, exists, extract, func, literal, or_, select
from sqlalchemy.orm import aliased
from app.models import (
    Patient, LabOrder, LabOrderItem, OrderPanel, TestCatalog, TestPanel, LabDepartment,
    Specimen, SpecimenRejection, RejectionReason, LabResultItem, LabReport, ReportResultItem,
    RequestingPhysician, ReferringFacility, LabPayment, LoginLog, AuthSession,
    StaffAccountLink, PatientAccountLink, UserAccount, BlockchainEvent,
)
from app.schemas.analytics import AnalyticsResponse, AnalyticsQuery, RangeInfo, next_bucket
from app.services.analytics_sql import SecondsBetween, MondayWeekday
from app.services.auth_service import utc_now


def between(column, bounds):
    return and_(column >= bounds[0], column < bounds[1])


def count(db, statement):
    return int(db.scalar(statement) or 0)


def ratio(numerator, denominator):
    return round(100*numerator/denominator, 2) if denominator else None


def metric(key, label, value, definition, unit='count', **extra):
    return dict(key=key, label=label, value=value, definition=definition, unit=unit, **extra)


def response(query, **values):
    start, end = query.bounds
    return AnalyticsResponse(range=RangeInfo(date_from=query.date_from, date_to=query.date_to,
        previous_date_from=(start-(end-start)).date(), previous_date_to=(start-timedelta(days=1)).date(),
        grain=query.resolved_grain), **values)


def bucket_expression(column, query):
    # Only validated, bounded calendar boundaries become SQL bind values.
    return case(*[(and_(column >= datetime.combine(day, time()),
                       column < datetime.combine(next_bucket(day, query.resolved_grain), time())), day.isoformat())
                  for day in query.buckets])


def trend(db, query, key, label, definition, column, statement):
    bucket = bucket_expression(column, query)
    rows = db.execute(statement.add_columns(bucket).where(between(column, query.bounds)).group_by(bucket)).all()
    values = {day: int(n) for n, day in rows}
    return dict(key=key, label=label, definition=definition,
                points=[dict(bucket=day, value=values.get(day.isoformat(), 0)) for day in query.buckets])


def distribution(db, key, label, definition, column, statement, states):
    values = {str(state): int(n) for state, n in db.execute(statement.add_columns(column).group_by(column).with_only_columns(column, func.count())).all()}
    total = sum(values.values())
    return dict(key=key, label=label, definition=definition, total=total,
                items=[dict(key=s, label=s, count=values.get(s, 0), share=ratio(values.get(s, 0), total)) for s in states])


def ranked(key, label, definition, rows, total):
    items = [dict(key=str(row[0]) if row[0] is not None else 'unspecified', label=row[1] or 'Direct / Not specified',
                  count=int(row[2]), share=ratio(int(row[2]), total)) for row in rows]
    return dict(key=key, label=label, definition=definition, items=items, total=total,
                other_count=max(0, total-sum(r['count'] for r in items)))


def qualifying(bounds):
    return and_(between(LabOrder.created_at, bounds), LabOrder.status != 'CANCELLED')


def returning_before(start):
    prior = aliased(LabOrder)
    return exists(select(prior.order_id).where(prior.patient_id == LabOrder.patient_id,
        prior.created_at < start, prior.status != 'CANCELLED'))


def requested_tests(bounds):
    return select(func.count()).select_from(LabOrderItem).join(LabOrder, LabOrder.order_id == LabOrderItem.order_id).where(between(LabOrder.created_at, bounds))


def headline_values(db, bounds):
    return {
        'new_patients': count(db, select(func.count()).select_from(Patient).where(between(Patient.created_at, bounds))),
        'patients_served': count(db, select(func.count(func.distinct(LabOrder.patient_id))).where(qualifying(bounds))),
        'returning_patients': count(db, select(func.count(func.distinct(LabOrder.patient_id))).where(qualifying(bounds), returning_before(bounds[0]))),
        'orders': count(db, select(func.count()).select_from(LabOrder).where(between(LabOrder.created_at, bounds))),
        'tests_requested': count(db, requested_tests(bounds)),
        'specimens_registered': count(db, select(func.count()).select_from(Specimen).where(between(Specimen.created_at, bounds))),
        'reports_released': count(db, select(func.count()).select_from(LabReport).where(between(LabReport.released_at, bounds))),
        'order_to_release': order_release_tat(db, bounds)['average_seconds'],
    }

HEADLINES = {
    'new_patients': ('New patient registrations', 'Patient records created in the period; not necessarily patients served.'),
    'patients_served': ('Patients served', 'Distinct patients with non-cancelled orders created in the period.'),
    'returning_patients': ('Returning patients', 'Patients served in this period with a non-cancelled order before its start.'),
    'orders': ('Orders created', 'All orders created in the period, including currently cancelled orders.'),
    'tests_requested': ('Tests requested', 'All individual LabOrderItem rows on period-created orders, including cancelled items and panel-expanded tests.'),
    'specimens_registered': ('Specimens registered', 'Specimens whose created_at is in the period.'),
    'reports_released': ('Report versions released', 'Report versions with a released_at timestamp in the period, including subsequently revoked versions.'),
    'order_to_release': ('Average order-to-release TAT', 'Average order creation to release of report versions released in the period; only valid complete timestamp sequences.'),
}


def overview(db, query):
    start, end = query.bounds
    current, previous = headline_values(db, (start, end)), headline_values(db, (start-(end-start), start))
    metrics = []
    for key, (label, definition) in HEADLINES.items():
        value, old = current[key], previous[key]
        change = value-old if value is not None and old is not None else None
        metrics.append(metric(key, label, value, definition, 'seconds' if key == 'order_to_release' else 'count',
            previous_value=old, absolute_change=change, percent_change=ratio(change, old) if change is not None else None, compared=True))
    return response(query, metrics=metrics)


def patients(db, query):
    definitions = HEADLINES
    series = [trend(db, query, 'new_patients', *definitions['new_patients'], Patient.created_at, select(func.count()).select_from(Patient)),
              trend(db, query, 'patients_served', *definitions['patients_served'], LabOrder.created_at,
                    select(func.count(func.distinct(LabOrder.patient_id))).where(LabOrder.status != 'CANCELLED'))]
    # Returning is relative to each bucket's clipped start, not registration age.
    prior = aliased(LabOrder)
    bucket_start = case(*[(between(LabOrder.created_at, (datetime.combine(day, time()), datetime.combine(next_bucket(day, query.resolved_grain), time()))),
                          max(datetime.combine(day, time()), query.bounds[0])) for day in query.buckets])
    earlier = exists(select(prior.order_id).where(prior.patient_id == LabOrder.patient_id, prior.status != 'CANCELLED', prior.created_at < bucket_start))
    series.append(trend(db, query, 'returning_patients', 'Returning patients',
        'Distinct served patients with an earlier non-cancelled order before each bucket starts (clipped to the selected range).',
        LabOrder.created_at, select(func.count(func.distinct(LabOrder.patient_id))).where(LabOrder.status != 'CANCELLED', earlier)))
    return response(query, series=series, notes=['Distinct patient counts are per bucket and must not be summed to obtain the period total.'])


def orders(db, query):
    base = select(func.count()).select_from(LabOrder).where(between(LabOrder.created_at, query.bounds))
    total = count(db, base)
    cancelled = count(db, base.where(LabOrder.status == 'CANCELLED'))
    return response(query, metrics=[metric('non_cancelled', 'Non-cancelled orders', total-cancelled, 'Period-created orders whose current status is not CANCELLED.'),
        metric('cancelled', 'Cancelled orders', cancelled, 'Period-created orders currently CANCELLED.'),
        metric('cancellation_rate', 'Cancellation rate', ratio(cancelled, total), 'Currently cancelled period-created orders / all period-created orders.', 'percent')],
        series=[trend(db, query, 'orders', 'Orders created', HEADLINES['orders'][1], LabOrder.created_at, select(func.count()).select_from(LabOrder))],
        breakdowns=[distribution(db, 'order_status', 'Current status of period-created orders', HEADLINES['orders'][1], LabOrder.status, base,
            ['REQUESTED','IN_PROGRESS','COMPLETED','CANCELLED'])])


def tests(db, query):
    base = requested_tests(query.bounds)
    total = count(db, base)
    test_count = func.count(LabOrderItem.order_item_id)
    rows = db.execute(select(TestCatalog.test_id, TestCatalog.test_name, test_count, TestCatalog.test_code, LabDepartment.department_name)
        .select_from(LabOrderItem).join(LabOrder, LabOrder.order_id == LabOrderItem.order_id)
        .join(TestCatalog, TestCatalog.test_id == LabOrderItem.test_id).join(LabDepartment, LabDepartment.department_id == TestCatalog.department_id)
        .where(between(LabOrder.created_at, query.bounds)).group_by(TestCatalog.test_id, TestCatalog.test_name, TestCatalog.test_code, LabDepartment.department_name)
        .order_by(test_count.desc(), TestCatalog.test_id).limit(query.top_n)).all()
    top = ranked('top_tests', 'Top requested tests', HEADLINES['tests_requested'][1], rows, total)
    for item, row in zip(top['items'], rows):
        item.update(code=row[3], department=row[4])
    panels = select(func.count()).select_from(OrderPanel).join(LabOrder, LabOrder.order_id == OrderPanel.order_id).where(between(LabOrder.created_at, query.bounds))
    panel_count = count(db, panels)
    panel_rows = db.execute(panels.with_only_columns(TestPanel.panel_id, TestPanel.panel_name, func.count())
        .join(TestPanel, TestPanel.panel_id == OrderPanel.panel_id).group_by(TestPanel.panel_id, TestPanel.panel_name)
        .order_by(func.count().desc(), TestPanel.panel_id).limit(query.top_n)).all()
    # Aggregate results per item first: multiple result rows never inflate workload.
    result_counts = select(LabResultItem.order_item_id,
        *[func.sum(case((LabResultItem.status == state, 1), else_=0)).label(state.lower()) for state in ('DRAFT','REVIEWED','VERIFIED')]
        ).group_by(LabResultItem.order_item_id).subquery()
    departments = db.execute(select(LabDepartment.department_id, LabDepartment.department_name, test_count, LabDepartment.department_code,
        *[func.coalesce(func.sum(getattr(result_counts.c, state)), 0) for state in ('draft','reviewed','verified')])
        .select_from(LabOrderItem).join(LabOrder, LabOrder.order_id == LabOrderItem.order_id)
        .join(TestCatalog, TestCatalog.test_id == LabOrderItem.test_id).join(LabDepartment, LabDepartment.department_id == TestCatalog.department_id)
        .outerjoin(result_counts, result_counts.c.order_item_id == LabOrderItem.order_item_id)
        .where(between(LabOrder.created_at, query.bounds)).group_by(LabDepartment.department_id, LabDepartment.department_name, LabDepartment.department_code)
        .order_by(test_count.desc(), LabDepartment.department_id).limit(20)).all()
    workload = ranked('departments', 'Department workload', 'Requested test items on period-created orders; result counts are current states for those items.', departments, total)
    for item, row in zip(workload['items'], departments):
        item.update(code=row[3], drafted=int(row[4]), reviewed=int(row[5]), verified=int(row[6]))
    return response(query, metrics=[metric('tests_requested', 'Tests requested', total, HEADLINES['tests_requested'][1]),
        metric('panel_requests', 'Panel requests', panel_count, 'OrderPanel rows on period-created orders, separately from their individual tests.')],
        series=[trend(db, query, 'tests_requested', 'Requested test trend', HEADLINES['tests_requested'][1], LabOrder.created_at,
            select(func.count()).select_from(LabOrderItem).join(LabOrder, LabOrder.order_id == LabOrderItem.order_id))],
        breakdowns=[top, workload, ranked('panels', 'Top requested panels', 'Panel requests on period-created orders, including cancelled requests.', panel_rows, panel_count)],
        notes=['Demand includes cancelled orders/items; no extra counts are added for panel membership. Rankings show requested tests only, not unused catalog entries.'])


def specimens(db, query):
    bounds = query.bounds
    registered = count(db, select(func.count()).select_from(Specimen).where(between(Specimen.created_at, bounds)))
    rejection_base = select(func.count()).select_from(SpecimenRejection).where(between(SpecimenRejection.rejected_at, bounds))
    events = count(db, rejection_base)
    rejected = count(db, rejection_base.with_only_columns(func.count(func.distinct(SpecimenRejection.specimen_id)) ))
    recollection = count(db, rejection_base.where(SpecimenRejection.recollection_required.is_(True)))
    reason_rows = db.execute(rejection_base.with_only_columns(RejectionReason.rejection_reason_id, RejectionReason.reason_name, func.count())
        .join(RejectionReason, RejectionReason.rejection_reason_id == SpecimenRejection.rejection_reason_id)
        .group_by(RejectionReason.rejection_reason_id, RejectionReason.reason_name)
        .order_by(func.count().desc(), RejectionReason.rejection_reason_id).limit(query.top_n)).all()
    metrics = [metric('registered', 'Specimens registered', registered, 'Specimen.created_at in period.'),
        metric('rejected', 'Distinct specimens rejected', rejected, 'Distinct specimen IDs with a rejection event in period.'),
        metric('rejection_events', 'Rejection events', events, 'SpecimenRejection rows with rejected_at in period.'),
        metric('rejections_per_100_registered', 'Rejections per 100 registered specimens', ratio(rejected, registered),
            'Distinct specimens rejected in period / specimens registered in period × 100. Different cohorts; may exceed 100. Not a QC acceptance/rejection rate.', 'percent'),
        metric('recollection_required', 'Recollection-required events', recollection, 'Rejection events in period marked recollection_required.'),
        metric('recollection_rate', 'Recollection-required event rate', ratio(recollection, events), 'Recollection-required events / all rejection events in period.', 'percent')]
    series = [trend(db, query, 'rejections', 'Rejection events over time', 'Events grouped by rejected_at; repeated rejection events are separate observations.',
        SpecimenRejection.rejected_at, select(func.count()).select_from(SpecimenRejection))]
    for key, col in [('collected', Specimen.collected_at), ('received', Specimen.received_at)]:
        metrics.append(metric(key, f'Specimens {key}', count(db, select(func.count()).select_from(Specimen).where(between(col, bounds))), f'Persisted {key}_at in period.'))
    metrics.append(metric('processed', 'Registered specimens currently processed', count(db, select(func.count()).select_from(Specimen).where(
        between(Specimen.created_at, bounds), Specimen.specimen_status == 'PROCESSED')), 'Current PROCESSED state among specimens registered in period; no processed_at exists.'))
    return response(query, metrics=metrics, series=series, breakdowns=[
        distribution(db, 'specimen_status', 'Current status of period-registered specimens', 'Registration cohort; not transition counts.', Specimen.specimen_status,
            select(func.count()).select_from(Specimen).where(between(Specimen.created_at, bounds)), ['PENDING','COLLECTED','RECEIVED','REJECTED','PROCESSED']),
        ranked('rejection_reasons', 'Top rejection reasons', 'Rejection events, not distinct specimens, by persisted reason.', reason_rows, events)],
        notes=['No acceptance event timestamp or processed_at exists. The rejection ratio compares two different period cohorts and can exceed 100.'])


def tat(db, key, label, definition, start, end, bounds, statement, valid_extra=literal(True), *, all_candidates=False):
    # Completed stages by endpoint date; also expose incomplete/negative stages
    # whose start occurred in range, rather than silently treating them as zero.
    candidates = or_(between(end, bounds), and_(between(start, bounds), or_(end.is_(None), end < start)))
    if all_candidates:
        candidates = literal(True)
    valid = and_(start.is_not(None), end.is_not(None), end >= start, valid_extra)
    row = db.execute(statement.with_only_columns(func.count(), func.sum(case((valid, 1), else_=0)),
        func.avg(case((valid, SecondsBetween(start, end)), else_=None))).where(candidates)).one()
    total, samples, average = int(row[0]), int(row[1] or 0), row[2]
    return dict(key=key, label=label, definition=definition, candidate_count=total, sample_count=samples,
                excluded_count=total-samples, average_seconds=round(float(average), 3) if average is not None else None)


def report_sequence():
    return and_(LabReport.generated_at >= LabOrder.created_at, LabReport.approved_at >= LabReport.generated_at,
                LabReport.released_at >= LabReport.approved_at)


def order_release_tat(db, bounds):
    return tat(db, 'order_to_release', 'Order created → report released', HEADLINES['order_to_release'][1],
        LabOrder.created_at, LabReport.released_at, bounds,
        select(func.count()).select_from(LabReport).join(LabOrder, LabOrder.order_id == LabReport.order_id), report_sequence())


def reports(db, query):
    metrics, series = [], []
    for stage in ('generated','approved','released','revoked'):
        col = getattr(LabReport, stage+'_at')
        label, definition = f'Report versions {stage}', f'Report versions with persisted {stage}_at in period, regardless of later status.'
        metrics.append(metric(stage, label, count(db, select(func.count()).select_from(LabReport).where(between(col, query.bounds))), definition))
        series.append(trend(db, query, stage, label, definition, col, select(func.count()).select_from(LabReport)))
    result_base = select(func.count()).select_from(LabResultItem).where(between(LabResultItem.encoded_at, query.bounds))
    metrics.append(metric('results_total', 'Result items encoded', count(db, result_base), 'Result items with encoded_at in period.'))
    for stage in ('reviewed','verified'):
        col = getattr(LabResultItem, stage+'_at')
        definition = f'Result items with their real {stage}_at in period, independently of encoding date.'
        metrics.append(metric('results_'+stage, f'Result items {stage}', count(db, select(func.count()).select_from(LabResultItem).where(between(col, query.bounds))), definition))
        series.append(trend(db, query, 'results_'+stage, f'Results {stage}', definition, col, select(func.count()).select_from(LabResultItem)))
    stages = [order_release_tat(db, query.bounds),
        tat(db, 'order_to_collection', 'Order created → specimen collected', 'One sample per specimen; collected_at is the completion timestamp.',
            LabOrder.created_at, Specimen.collected_at, query.bounds,
            select(func.count()).select_from(Specimen).join(LabOrder, LabOrder.order_id == Specimen.order_id), and_(Specimen.created_at >= LabOrder.created_at, Specimen.collected_at >= Specimen.created_at)),
        tat(db, 'collection_to_receipt', 'Specimen collected → received', 'One sample per specimen; received_at is the completion timestamp.',
            Specimen.collected_at, Specimen.received_at, query.bounds, select(func.count()).select_from(Specimen), Specimen.collected_at >= Specimen.created_at),
        tat(db, 'receipt_to_review', 'Specimen received → result reviewed', 'One sample per result using its exact specimen_id; no inferred specimen association.',
            Specimen.received_at, LabResultItem.reviewed_at, query.bounds,
            select(func.count()).select_from(LabResultItem).outerjoin(Specimen, Specimen.specimen_id == LabResultItem.specimen_id)
            .join(LabOrderItem, LabOrderItem.order_item_id == LabResultItem.order_item_id),
            and_(Specimen.order_id == LabOrderItem.order_id, Specimen.collected_at >= Specimen.created_at, Specimen.received_at >= Specimen.collected_at,
                 LabResultItem.encoded_at >= Specimen.received_at, LabResultItem.reviewed_at >= LabResultItem.encoded_at)),
        tat(db, 'approval_to_release', 'Report approved → released', 'One sample per report version; release must follow generation and approval.',
            LabReport.approved_at, LabReport.released_at, query.bounds, select(func.count()).select_from(LabReport),
            LabReport.approved_at >= LabReport.generated_at)]
    reviewed = select(ReportResultItem.report_id, func.max(LabResultItem.reviewed_at).label('last_review'),
        func.sum(case((or_(LabResultItem.reviewed_at.is_(None), LabResultItem.reviewed_at < LabResultItem.encoded_at), 1), else_=0)).label('missing')).select_from(ReportResultItem)
    reviewed = reviewed.join(LabResultItem, LabResultItem.result_item_id == ReportResultItem.result_item_id).group_by(ReportResultItem.report_id).subquery()
    stages.append(tat(db, 'review_to_approval', 'Last linked result review → report approved',
        'One sample per report version using the latest review of its persisted ReportResultItem links. All linked results must have review timestamps.',
        reviewed.c.last_review, LabReport.approved_at, query.bounds,
        select(func.count()).select_from(LabReport).outerjoin(reviewed, reviewed.c.report_id == LabReport.report_id),
        and_(reviewed.c.missing == 0, LabReport.generated_at >= reviewed.c.last_review, LabReport.approved_at >= LabReport.generated_at)))
    return response(query, metrics=metrics, series=series, turnaround=stages,
        breakdowns=[distribution(db, 'result_status', 'Current status of period-encoded results', 'Encoding cohort; not historical state transitions.', LabResultItem.status, result_base, ['DRAFT','REVIEWED','VERIFIED'])],
        notes=['TAT candidates end in the period, plus incomplete/negative stages started in the period. Invalid/missing endpoints and invalid stage sequences are excluded and counted.',
               'Reports count versions, including revisions. Stage timestamps are used directly; updated_at is never a substitute.'])


def operations(db, query):
    bounds = query.bounds
    base = select(func.count()).select_from(LabOrder).where(between(LabOrder.created_at, bounds))
    total = count(db, base)
    referrals = base.outerjoin(RequestingPhysician, RequestingPhysician.physician_id == LabOrder.physician_id)
    physician_name = RequestingPhysician.first_name + ' ' + RequestingPhysician.last_name
    physician_rows = db.execute(referrals.with_only_columns(RequestingPhysician.physician_id, physician_name, func.count())
        .group_by(RequestingPhysician.physician_id, physician_name).order_by(func.count().desc(), RequestingPhysician.physician_id).limit(query.top_n)).all()
    facility_rows = db.execute(referrals.outerjoin(ReferringFacility, ReferringFacility.referring_facility_id == RequestingPhysician.referring_facility_id)
        .with_only_columns(ReferringFacility.referring_facility_id, ReferringFacility.facility_name, func.count())
        .group_by(ReferringFacility.referring_facility_id, ReferringFacility.facility_name)
        .order_by(func.count().desc(), ReferringFacility.referring_facility_id).limit(query.top_n)).all()
    breakdowns = [ranked('physicians', 'Top requesting physicians', 'All period-created orders; current physician names. Missing physician is Direct / Not specified.', physician_rows, total),
        ranked('facilities', 'Top referring facilities', 'All period-created orders through current physician-to-facility association; missing links are Direct / Not specified.', facility_rows, total)]
    for key, label, expression, labels in [
        ('weekday', 'Order arrival pattern by weekday', MondayWeekday(LabOrder.created_at), ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']),
        ('hour', 'Order arrival pattern by hour (UTC)', extract('hour', LabOrder.created_at), [f'{hour:02d}:00' for hour in range(24)])]:
        rows = dict(db.execute(base.with_only_columns(expression, func.count()).group_by(expression)).all())
        breakdowns.append(dict(key=key, label=label, definition='All order creation timestamps in UTC; not specimen-processing workload.', total=total,
            items=[dict(key=str(i), label=name, count=rows.get(i, 0), share=ratio(rows.get(i, 0), total)) for i, name in enumerate(labels)]))
    # LabPayment is append-only history, not a financial ledger. Select exactly
    # one latest record per selected order, with deterministic timestamp/id ties.
    newer = aliased(LabPayment)
    latest = ~exists(select(newer.payment_id).where(newer.order_id == LabPayment.order_id, or_(
        newer.recorded_at > LabPayment.recorded_at, and_(newer.recorded_at == LabPayment.recorded_at, newer.payment_id > LabPayment.payment_id))))
    payment_join = and_(LabPayment.order_id == LabOrder.order_id, latest)
    payment_state = func.coalesce(cast(LabPayment.payment_status, String(20)), 'NOT_RECORDED')
    payments = base.outerjoin(LabPayment, payment_join)
    breakdowns.append(distribution(db, 'payments', 'Latest recorded payment status of period-created orders',
        'One latest payment-history record per order by recorded_at then payment_id. Includes orders with no record.',
        payment_state, payments, ['PENDING','PAID','FREE','WAIVED','SUBSIDIZED','NOT_RECORDED']))
    amount = db.scalar(payments.with_only_columns(func.sum(LabPayment.amount)))
    return response(query, breakdowns=breakdowns, metrics=[metric('recorded_amount', 'Latest recorded amount for selected orders',
        float(amount) if amount is not None else None, 'Sum of non-null amounts from the latest payment record per selected order, across all payment statuses. Not accounting revenue; currency is not specified in the schema.', 'amount')],
        notes=['Payments have recorded_at, not paid_at. No revenue or payment-date trend is shown. Amounts may include unpaid, waived or subsidized entries; no currency is assumed.',
               'Referral attribution uses the current physician/facility relationship, not a historical snapshot. Bounded rankings include an Other total.'])


def system(db, query):
    bounds = query.bounds
    logins = select(func.count()).select_from(LoginLog).where(between(LoginLog.login_time, bounds))
    successes = count(db, logins.where(LoginLog.status == 'SUCCESS'))
    failures = count(db, logins.where(LoginLog.status == 'FAILED'))
    kind = case((PatientAccountLink.user_id.is_not(None), 'PATIENT'), (StaffAccountLink.user_id.is_not(None), 'STAFF'), else_='SYSTEM/UNKNOWN')
    account_logins = logins.outerjoin(PatientAccountLink, PatientAccountLink.user_id == LoginLog.user_id).outerjoin(StaffAccountLink, StaffAccountLink.user_id == LoginLog.user_id)
    types = distribution(db, 'login_types', 'Login attempts by account type', 'All period login attempts; unresolved/unlinked identities are SYSTEM/UNKNOWN. Current associations only.', kind, account_logins, ['STAFF','PATIENT','SYSTEM/UNKNOWN'])
    active = count(db, select(func.count()).select_from(AuthSession).join(UserAccount, UserAccount.user_id == AuthSession.user_id)
        .where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > utc_now(), UserAccount.account_status == 'ACTIVE'))
    anchors = select(func.count()).select_from(BlockchainEvent).where(between(BlockchainEvent.created_at, bounds))
    created = count(db, anchors)
    confirmed = count(db, anchors.where(BlockchainEvent.event_status == 'CONFIRMED'))
    latency = tat(db, 'anchor_confirmation', 'Anchor confirmation latency', 'Created-to-confirmed duration for CONFIRMED events created in period; missing/negative timestamps excluded.',
        BlockchainEvent.created_at, BlockchainEvent.confirmed_at, query.bounds,
        anchors.where(BlockchainEvent.event_status == 'CONFIRMED'), all_candidates=True)
    return response(query, metrics=[metric('login_success', 'Successful logins', successes, 'LoginLog SUCCESS rows with login_time in period.'),
        metric('login_failed', 'Failed logins', failures, 'LoginLog FAILED rows with login_time in period.'),
        metric('login_failure_rate', 'Login failure rate', ratio(failures, successes+failures), 'Failed / all persisted login attempts in period.', 'percent'),
        metric('active_sessions_now', 'Active sessions now', active, 'Current unexpired/unrevoked sessions for ACTIVE accounts; point-in-time, not date-range scoped.'),
        metric('anchors_created', 'Anchors created', created, 'Application blockchain events whose created_at is in period; no Fabric network probes.'),
        metric('confirmation_rate', 'Created-anchor confirmation rate', ratio(confirmed, created), 'Current CONFIRMED events / all events created in period.', 'percent')],
        breakdowns=[types, distribution(db, 'anchors', 'Current status of period-created anchors', 'Application outbox evidence, not node or consensus health.', BlockchainEvent.event_status,
            anchors, ['PENDING','PROCESSING','CONFIRMED','FAILED','DEAD'])], turnaround=[latency],
        notes=['Active sessions is a live snapshot. All other counts use the selected range. No usernames, IPs, agents, tokens, session IDs, hashes or payloads are returned.'])
