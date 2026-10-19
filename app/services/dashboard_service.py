"""Current workflow counts without patient or report content projections."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, text
from app.models import AuthSession, LabOrder, LabReport, LabResultItem, LoginLog, Patient, Specimen, UserAccount
from app.models.service_observation import ServiceObservation
from app.services.activity_observation_service import eligible_staff, PRESENCE_SECONDS, WORKER_FRESH_SECONDS
from app.services.patient_activation_service import can_read_status, activation_state_expression
from app.services.report_stage import signing_stages
from app.services.rbac_service import get_user_permissions, get_user_roles, SYSTEM_ADMIN_ROLE_CODE


WORKFLOWS = (
    ('orders', 'LAB_ORDER_READ', LabOrder.status),
    ('specimens', 'SPECIMEN_READ', Specimen.specimen_status),
    ('results', 'LAB_RESULT_READ', LabResultItem.status),
    ('reports', 'REPORT_READ', LabReport.report_status),
)


def overview(db, user_id):
    admin = SYSTEM_ADMIN_ROLE_CODE in get_user_roles(db, user_id)
    permissions = set(get_user_permissions(db, user_id)) if not admin else set()
    response = {}
    now = datetime.now(timezone.utc)
    naive_now = now.replace(tzinfo=None)
    allowed = lambda code: admin or code in permissions
    if admin or 'PATIENT_READ' in permissions:
        response['patients'] = db.scalar(select(func.count()).select_from(Patient))
    for key, permission, column in WORKFLOWS:
        if admin or permission in permissions:
            # No joins: each stored record/version contributes exactly once.
            counts = {status: 0 for status in column.type.enums}
            counts.update({status: int(count) for status, count in db.execute(
                select(column, func.count()).group_by(column))})
            response[key] = {'total': sum(counts.values()), 'statuses': counts}
    if allowed('PATIENT_READ') and can_read_status(db, user_id):
        state = activation_state_expression(naive_now)
        # Correlated state expressions cannot be grouped directly under MySQL
        # ONLY_FULL_GROUP_BY. Count filtered patients without grouping or joins.
        response['activation'] = {
            'not_activated': db.scalar(select(func.count()).select_from(Patient).where(state != 'ACTIVATED')),
            'review_required': db.scalar(select(func.count()).select_from(Patient).where(state == 'REVIEW_REQUIRED')),
        }
    if allowed('ACCOUNT_READ'):
        counts = dict(db.execute(select(UserAccount.account_status, func.count()).group_by(UserAccount.account_status)).all())
        response['accounts'] = {'active': counts.get('ACTIVE', 0), 'suspended': counts.get('SUSPENDED', 0)}
    if allowed('AUTH_ACTIVITY_VIEW'):
        since = now - timedelta(hours=24)
        response['failed_logins'] = {'count': db.scalar(select(func.count()).select_from(LoginLog).where(
            LoginLog.status == 'FAILED', LoginLog.login_time >= since.replace(tzinfo=None), LoginLog.login_time <= naive_now)),
            'since': since, 'until': now}
        response['presence'] = {'recently_active': db.scalar(select(func.count(func.distinct(AuthSession.user_id)))
            .join(UserAccount, UserAccount.user_id == AuthSession.user_id).where(
                UserAccount.account_status == 'ACTIVE', AuthSession.revoked_at.is_(None), AuthSession.expires_at > naive_now,
                AuthSession.last_activity_at >= naive_now - timedelta(seconds=PRESENCE_SECONDS),
                AuthSession.last_activity_at <= naive_now, *eligible_staff(AuthSession.user_id))),
            'window_seconds': PRESENCE_SECONDS}
    if allowed('REPORT_READ'):
        response['signing'] = {key: db.scalar(select(func.count()).select_from(LabReport).where(condition))
                               for key, condition in signing_stages().items()}
    if allowed('BLOCKCHAIN_STATUS_VIEW'):
        db.execute(text('SELECT 1'))
        worker = db.get(ServiceObservation, 'blockchain_worker')
        status = 'UNKNOWN'
        if worker is not None:
            age = (naive_now - worker.checked_at).total_seconds()
            status = ('UNKNOWN' if age < 0 else 'STALE' if age > WORKER_FRESH_SECONDS
                      else worker.status if worker.status in {'HEALTHY', 'UNHEALTHY', 'STOPPED'} else 'UNKNOWN')
        response['services'] = [
            {'name': 'Application', 'status': 'HEALTHY', 'checked_at': now},
            {'name': 'Database', 'status': 'HEALTHY', 'checked_at': now},
            {'name': 'Blockchain worker', 'status': status,
             'checked_at': worker.checked_at.replace(tzinfo=timezone.utc) if worker else None},
        ]
    response['generated_at'] = now
    return response
