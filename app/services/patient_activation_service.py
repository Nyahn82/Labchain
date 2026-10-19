"""Staff-provisioned, hashed, expiring activation tokens and atomic redemption."""
from datetime import timedelta
import secrets

from fastapi import HTTPException
from sqlalchemy import case, exists, func, or_, select

from app.config import settings
from app.models import Patient, PatientAccountLink, PatientActivationToken, Role, UserAccount, UserRole
from app.schemas import patient_portal as s
from app.security.passwords import hash_password
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import retry_deadlocks
from app.services.rbac_service import get_user_permissions, get_user_roles

INVALID_TOKEN = 'Invalid or expired activation token.'


def current(statement):
    return statement.with_for_update().execution_options(populate_existing=True)


def account_link(db, patient_id):
    return db.scalar(current(select(PatientAccountLink).where(PatientAccountLink.patient_id == patient_id)))


@retry_deadlocks
def issue_token(db, patient_id, actor_id, ip_address):
    with mutation(db):
        patient = get_record(db, Patient, patient_id, lock=True)
        if account_link(db, patient_id) is not None:
            raise HTTPException(409, 'Patient account is already activated.')
        if has_consumed_token(db, patient_id):
            raise HTTPException(409, 'Activation history requires administrator review. No invitation was issued.')
        tokens = list(db.scalars(current(select(PatientActivationToken).where(
            PatientActivationToken.patient_id == patient_id,
            PatientActivationToken.used_at.is_(None), PatientActivationToken.revoked_at.is_(None)))))
        now = utc_now()
        for previous in tokens:
            if previous.expires_at > now:
                previous.revoked_at = now
        plaintext = secrets.token_urlsafe(24)
        expiry = now + timedelta(minutes=settings.patient_activation_ttl_minutes)
        token = PatientActivationToken(patient_id=patient_id, token_hash=hash_token(plaintext),
            issued_by_user_id=actor_id, created_at=now, expires_at=expiry, used_at=None, revoked_at=None)
        db.add(token)
        db.flush()
        audit(db, actor_id, 'PATIENT_ACTIVATION_TOKEN_ISSUE', 'patient', patient_id, ip_address)
        response = s.TokenIssued(activation_token=plaintext, expires_at=expiry, patient_code=patient.patient_code)
    return response


def has_consumed_token(db, patient_id):
    return db.scalar(select(PatientActivationToken.activation_token_id).where(
        PatientActivationToken.patient_id == patient_id,
        PatientActivationToken.used_at.is_not(None)).limit(1)) is not None


def can_read_status(db, actor_id):
    roles = get_user_roles(db, actor_id)
    if 'PATIENT' in roles or db.scalar(select(PatientAccountLink.user_id).where(
            PatientAccountLink.user_id == actor_id)) is not None:
        return False
    return 'SYSTEM_ADMIN' in roles or bool(
        {'PATIENT_ACCOUNT_ACTIVATE', 'ACCOUNT_READ'} & set(get_user_permissions(db, actor_id)))


def activation_states(db, patient_ids):
    """Bounded directory projection; never load token hashes or account credentials."""
    ids = list(patient_ids)
    if not ids:
        return {}
    linked = set(db.scalars(select(PatientAccountLink.patient_id).where(
        PatientAccountLink.patient_id.in_(ids))))
    consumed = set(db.scalars(select(PatientActivationToken.patient_id).where(
        PatientActivationToken.patient_id.in_(ids), PatientActivationToken.used_at.is_not(None)).distinct()))
    latest_ids = select(func.max(PatientActivationToken.activation_token_id)).where(
        PatientActivationToken.patient_id.in_(ids)).group_by(PatientActivationToken.patient_id)
    latest = {row.patient_id: row for row in db.execute(select(
        PatientActivationToken.patient_id, PatientActivationToken.expires_at,
        PatientActivationToken.revoked_at).where(PatientActivationToken.activation_token_id.in_(latest_ids)))}
    now = utc_now()
    states = {}
    for patient_id in ids:
        token = latest.get(patient_id)
        if patient_id in linked:
            state = 'ACTIVATED'
        elif patient_id in consumed:
            state = 'REVIEW_REQUIRED'
        elif token is None:
            state = 'NOT_ACTIVATED'
        elif token.revoked_at is not None:
            state = 'TOKEN_REVOKED'
        else:
            state = 'TOKEN_ACTIVE' if token.expires_at > now else 'TOKEN_EXPIRED'
        states[patient_id] = state
    return states


def activation_state_expression(now):
    """SQL equivalent of activation_states, evaluated before counting/pagination."""
    token = PatientActivationToken
    latest = select(func.max(token.activation_token_id)).where(
        token.patient_id == Patient.patient_id).correlate(Patient).scalar_subquery()
    linked = exists(select(PatientAccountLink.patient_id).where(PatientAccountLink.patient_id == Patient.patient_id))
    consumed = exists(select(token.activation_token_id).where(
        token.patient_id == Patient.patient_id, token.used_at.is_not(None)))
    revoked = exists(select(token.activation_token_id).where(token.activation_token_id == latest, token.revoked_at.is_not(None)))
    active = exists(select(token.activation_token_id).where(token.activation_token_id == latest, token.expires_at > now))
    return case((linked, 'ACTIVATED'), (consumed, 'REVIEW_REQUIRED'),
                (latest.is_(None), 'NOT_ACTIVATED'), (revoked, 'TOKEN_REVOKED'),
                (active, 'TOKEN_ACTIVE'), else_='TOKEN_EXPIRED')


def patient_directory(db, *, page, page_size, search=None, patient_code=None, sex=None,
                      activation_group=None, activation_state=None, sort_by='patient_id', sort_direction='asc'):
    state = activation_state_expression(utc_now())
    conditions = []
    for column, value in ((Patient.patient_code, patient_code), (Patient.sex, sex)):
        if value is not None:
            conditions.append(column == value)
    if search and search.strip():
        conditions.append(or_(*(column.icontains(search.strip(), autoescape=True) for column in
            (Patient.patient_code, Patient.first_name, Patient.middle_name, Patient.last_name))))
    if activation_group:
        conditions.append(state == 'ACTIVATED' if activation_group == 'ACTIVATED' else state != 'ACTIVATED')
    if activation_state:
        conditions.append(state == activation_state)
    sorts = {'patient_id': (Patient.patient_id,), 'patient_code': (Patient.patient_code,),
             'name': (Patient.last_name, Patient.first_name, Patient.middle_name), 'activation': (state,)}
    columns = sorts[sort_by]
    ordering = [column.desc() if sort_direction == 'desc' else column.asc() for column in columns]
    total = db.scalar(select(func.count()).select_from(Patient).where(*conditions))
    items = db.scalars(select(Patient).where(*conditions).order_by(*ordering, Patient.patient_id.asc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return dict(items=items, total=total, page=page, page_size=page_size)


def activation_status(db, patient_id):
    get_record(db, Patient, patient_id)
    return s.ActivationStatus(status=activation_states(db, [patient_id])[patient_id])


@retry_deadlocks
def activate(db, payload, ip_address):
    with mutation(db):
        digest = hash_token(payload.activation_token.get_secret_value())
        # Identify the patient without locking the token first. Both issuance and
        # redemption acquire the patient lock before token/link locks.
        candidate = db.scalar(select(PatientActivationToken).where(PatientActivationToken.token_hash == digest))
        if candidate is None:
            raise HTTPException(400, INVALID_TOKEN)
        patient = db.scalar(current(select(Patient).where(Patient.patient_id == candidate.patient_id)))
        token = db.scalar(current(select(PatientActivationToken).where(PatientActivationToken.token_hash == digest)))
        if (patient is None or token is None or token.used_at is not None or token.revoked_at is not None
                or token.expires_at <= utc_now() or account_link(db, patient.patient_id) is not None
                or has_consumed_token(db, patient.patient_id)):
            raise HTTPException(400, INVALID_TOKEN)
        role = db.scalar(select(Role).where(Role.role_code == 'PATIENT').with_for_update(read=True)
                         .execution_options(populate_existing=True))
        if role is None or role.role_code != 'PATIENT' or not role.is_active:
            raise HTTPException(503, 'Patient activation is temporarily unavailable.')
        if db.scalar(current(select(UserAccount.user_id).where(UserAccount.username == payload.username))) is not None:
            raise HTTPException(409, 'Username is unavailable.')
        encoded_password = hash_password(payload.password.get_secret_value())
        now = utc_now()
        if token.expires_at <= now:
            raise HTTPException(400, INVALID_TOKEN)
        user = UserAccount(username=payload.username, password_hash=encoded_password, account_status='ACTIVE', created_at=now)
        db.add(user)
        db.flush()
        db.add(PatientAccountLink(patient_id=patient.patient_id, user_id=user.user_id))
        db.add(UserRole(user_id=user.user_id, role_id=role.role_id, assigned_at=now, assigned_by=token.issued_by_user_id))
        token.used_at = now
        audit(db, user.user_id, 'PATIENT_ACCOUNT_ACTIVATE', 'user_account', user.user_id, ip_address)
        db.flush()
        response = s.ActivatedAccount(user_id=user.user_id, username=user.username, account_status='ACTIVE', roles=['PATIENT'])
    # No auto-login: use the existing auth/login endpoint and its cookie/CSRF flow.
    return response
