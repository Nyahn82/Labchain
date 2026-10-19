"""Server-observed activity. No tokens, patient values or arbitrary service commands."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import exists, select, update, or_
from app.models import AuthSession, PatientAccountLink, Role, Staff, StaffAccountLink, UserRole
from app.models.service_observation import ServiceObservation

PRESENCE_SECONDS = 300
ACTIVITY_WRITE_SECONDS = 60
WORKER_FRESH_SECONDS = 300


def eligible_staff(user_column):
    # A real staff association is required; patient associations/mixed roles are excluded.
    return (
        exists(select(StaffAccountLink.staff_id).join(Staff).where(
            StaffAccountLink.user_id == user_column, Staff.is_active.is_(True))),
        ~exists(select(PatientAccountLink.patient_id).where(PatientAccountLink.user_id == user_column)),
        ~exists(select(UserRole.user_role_id).join(Role).where(
            UserRole.user_id == user_column, Role.role_code == 'PATIENT', Role.is_active.is_(True))),
    )


def observe_authenticated_activity(db, session, now):
    """Called after authentication/CSRF/MFA, before route mutations. At most one write/minute.

    This commits only its own observation; authentication has performed reads only.
    Existing mutation services retain ownership of subsequent business transactions.
    """
    cutoff = now - timedelta(seconds=ACTIVITY_WRITE_SECONDS)
    if session.last_activity_at is not None and session.last_activity_at > cutoff:
        return
    if not db.scalar(select(exists().where(AuthSession.session_id == session.session_id,
                                          *eligible_staff(AuthSession.user_id)))):
        return
    db.execute(update(AuthSession).where(
        AuthSession.session_id == session.session_id,
        AuthSession.revoked_at.is_(None), AuthSession.expires_at > now,
        or_(AuthSession.last_activity_at.is_(None), AuthSession.last_activity_at <= cutoff),
    ).values(last_activity_at=now.replace(microsecond=0)))
    db.commit()


def record_worker(sessions, status='HEALTHY'):
    """One worker service per installation; startup/shutdown/cycle observations only."""
    if status not in {'HEALTHY', 'UNHEALTHY', 'STOPPED'}:
        raise ValueError('Unsupported observation')
    with sessions.begin() as db:
        row = db.get(ServiceObservation, 'blockchain_worker')
        if row is None:
            row = ServiceObservation(service='blockchain_worker')
            db.add(row)
        row.status = status
        # MySQL DATETIME has second precision; prevent rounding into the future.
        row.checked_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
