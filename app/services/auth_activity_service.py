"""SQL-paginated projections of persisted authentication evidence only."""
from fastapi import HTTPException
from sqlalchemy import String, and_, case, cast, func, literal, or_, select, union_all, update
from app.models import (AuditLog, AuthSession, LoginLog, Patient, PatientAccountLink,
                        Staff, StaffAccountLink, UserAccount)
from app.services.administration_service import actor_authority, current_roles, lock_administration
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.rbac_service import get_user_roles

ACCOUNT_EVENTS = {
    'ACCOUNT_SUSPENDED': 'ACCOUNT_SUSPENDED', 'ACCOUNT_REACTIVATED': 'ACCOUNT_REACTIVATED',
    'ACCOUNT_LOCKED': 'ACCOUNT_LOCKED', 'ACCOUNT_DISABLED': 'ACCOUNT_DISABLED',
    'PASSWORD_CHANGE': 'PASSWORD_CHANGED', 'MFA_CHALLENGE_SUCCESS': 'MFA_SUCCESS',
    'MFA_CHALLENGE_FAILED': 'MFA_FAILED', 'ACCOUNT_MFA_RESET': 'MFA_RESET',
    'AUTH_ALL_SESSIONS_REVOKED': 'SESSION_REVOKED',
}
SESSION_EVENTS = {'AUTH_LOGOUT': 'LOGOUT', 'AUTH_SESSION_REVOKED': 'SESSION_REVOKED'}


def staff_only(db, user_id):
    # A patient role or clinical portal association is not an administration identity.
    if ('PATIENT' in get_user_roles(db, user_id) or db.scalar(select(PatientAccountLink.user_id)
            .where(PatientAccountLink.user_id == user_id)) is not None):
        raise HTTPException(403, 'Staff administration access required.')


def identities():
    kind = case((PatientAccountLink.user_id.is_not(None), 'PATIENT'),
                (StaffAccountLink.user_id.is_not(None), 'STAFF'), else_='SYSTEM/UNKNOWN')
    name = case((PatientAccountLink.user_id.is_not(None), Patient.first_name + ' ' + Patient.last_name),
                (StaffAccountLink.user_id.is_not(None), Staff.first_name + ' ' + Staff.last_name), else_=None)
    return kind, name


def join_identity(statement, user_column):
    return (statement.outerjoin(UserAccount, UserAccount.user_id == user_column)
            .outerjoin(StaffAccountLink, StaffAccountLink.user_id == UserAccount.user_id)
            .outerjoin(Staff, Staff.staff_id == StaffAccountLink.staff_id)
            .outerjoin(PatientAccountLink, PatientAccountLink.user_id == UserAccount.user_id)
            .outerjoin(Patient, Patient.patient_id == PatientAccountLink.patient_id))


def identity_conditions(filters, kind, name):
    conditions = []
    if filters.account_type:
        conditions.append(kind == filters.account_type)
    if filters.user_id is not None:
        conditions.append(UserAccount.user_id == filters.user_id)
    if filters.search and filters.search.strip():
        term = filters.search.strip()
        conditions.append(or_(UserAccount.username.icontains(term, autoescape=True), name.icontains(term, autoescape=True)))
    return conditions


def page(db, statement, filters):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    items = db.execute(statement.offset((filters.page - 1) * filters.page_size).limit(filters.page_size)).mappings().all()
    return dict(items=[dict(row) for row in items], total=total, page=filters.page, page_size=filters.page_size)


def activities(db, filters):
    # LoginLog is authoritative for logins; omit AUTH_LOGIN to avoid duplicates.
    # Unknown attempted usernames and all JSON audit payloads stay private.
    logins = select(literal('login').label('source'), LoginLog.login_log_id.label('source_id'),
        case((LoginLog.status == 'SUCCESS', 'LOGIN_SUCCESS'), else_='LOGIN_FAILED').label('activity_type'),
        LoginLog.login_time.label('occurred_at'), LoginLog.user_id.label('subject_id'),
        LoginLog.ip_address.label('ip_address'), cast(literal(None), String(255)).label('user_agent'),
        cast(LoginLog.status, String(16)).label('status'), cast(literal(None), AuthSession.session_id.type).label('session_id'))
    # Audit.user_id is the ACTOR. record_id or the exact session FK is the subject.
    old_status_event = case(
        (AuditLog.new_value['account_status'].as_string() == 'LOCKED', 'ACCOUNT_LOCKED'),
        (AuditLog.new_value['account_status'].as_string() == 'DISABLED', 'ACCOUNT_DISABLED'),
        else_='ACCOUNT_STATUS_UPDATED')
    event = case(ACCOUNT_EVENTS | SESSION_EVENTS, value=AuditLog.action, else_=old_status_event)
    audits = select(literal('audit').label('source'), AuditLog.audit_id.label('source_id'),
        event.label('activity_type'), AuditLog.created_at.label('occurred_at'),
        case((AuditLog.entity_type == 'auth_session', AuthSession.user_id), else_=AuditLog.record_id).label('subject_id'),
        AuditLog.ip_address.label('ip_address'), AuthSession.user_agent.label('user_agent'),
        case((AuditLog.action == 'MFA_CHALLENGE_FAILED', 'FAILED'),
             (AuditLog.action == 'MFA_CHALLENGE_SUCCESS', 'SUCCESS'), else_='RECORDED').label('status'),
        AuthSession.session_id.label('session_id')).outerjoin(AuthSession, and_(
            AuditLog.entity_type == 'auth_session', AuditLog.record_id == AuthSession.session_id)).where(or_(
                and_(AuditLog.entity_type == 'user_account', AuditLog.action.in_([*ACCOUNT_EVENTS, 'ACCOUNT_STATUS_UPDATE'])),
                and_(AuditLog.entity_type == 'auth_session', AuditLog.action.in_(SESSION_EVENTS))))
    projection = union_all(logins, audits).subquery()
    kind, name = identities()
    statement = join_identity(select(projection, UserAccount.user_id, UserAccount.username,
        kind.label('account_type'), name.label('display_name')).select_from(projection), projection.c.subject_id)
    conditions = identity_conditions(filters, kind, name)
    for field in ('activity_type', 'status', 'ip_address'):
        if getattr(filters, field) is not None:
            conditions.append(getattr(projection.c, field) == getattr(filters, field))
    if filters.date_from:
        conditions.append(projection.c.occurred_at >= filters.date_from)
    if filters.date_to:
        conditions.append(projection.c.occurred_at <= filters.date_to)
    result = page(db, statement.where(*conditions).order_by(
        projection.c.occurred_at.desc(), projection.c.source.desc(), projection.c.source_id.desc()), filters)
    for item in result['items']:
        item['activity_id'] = f"{item.pop('source')}:{item.pop('source_id')}"
        item.pop('subject_id')
    return result


def sessions(db, filters, current_session_id):
    now = utc_now()
    kind, name = identities()
    state = case((AuthSession.revoked_at.is_not(None), 'REVOKED'),
                 (AuthSession.expires_at <= now, 'EXPIRED'), else_='ACTIVE')
    statement = join_identity(select(AuthSession.session_id, AuthSession.created_at, AuthSession.expires_at,
        AuthSession.revoked_at, AuthSession.ip_address, AuthSession.user_agent, UserAccount.user_id,
        UserAccount.username, kind.label('account_type'), name.label('display_name'), state.label('state'),
        (AuthSession.session_id == current_session_id).label('is_current')).select_from(AuthSession), AuthSession.user_id)
    conditions = identity_conditions(filters, kind, name)
    if filters.state:
        conditions.append(state == filters.state)
    return page(db, statement.where(*conditions).order_by(AuthSession.created_at.desc(), AuthSession.session_id.desc()), filters)


def revoke(db, actor_session, ip_address, *, session_id=None, user_id=None):
    with mutation(db):
        lock_administration(db)
        admin, _ = actor_authority(db, actor_session.user_id, 'SESSION_MANAGE')
        staff_only(db, actor_session.user_id)
        if session_id is not None:
            # Read target id, then lock account BEFORE session, matching login/MFA order.
            target_id = db.scalar(select(AuthSession.user_id).where(AuthSession.session_id == session_id))
            if target_id is None:
                raise HTTPException(404, 'Session not found.')
        else:
            target_id = user_id
        get_record(db, UserAccount, target_id, lock=True)
        roles = current_roles(db, target_id)
        if not admin and any(role.role_code == 'SYSTEM_ADMIN' for role in roles):
            raise HTTPException(403, 'Only SYSTEM_ADMIN may manage administrator sessions.')
        if session_id == actor_session.session_id or (session_id is None and target_id == actor_session.user_id):
            raise HTTPException(409, 'Use Log out to end your own current session.')
        now = utc_now()
        conditions = [AuthSession.user_id == target_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now]
        if session_id is not None:
            conditions.append(AuthSession.session_id == session_id)
        count = db.execute(update(AuthSession).where(*conditions).values(revoked_at=now)).rowcount
        if session_id is None:
            from app.services.mfa_service import revoke_challenges
            revoke_challenges(db, target_id, now)
        audit(db, actor_session.user_id, 'AUTH_SESSION_REVOKED' if session_id is not None else 'AUTH_ALL_SESSIONS_REVOKED',
              'auth_session' if session_id is not None else 'user_account',
              session_id if session_id is not None else target_id, ip_address, new={'revoked_count': count})
    return {'revoked_count': count}
