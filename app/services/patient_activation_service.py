"""Staff-provisioned, hashed, expiring activation tokens and atomic redemption."""
from datetime import timedelta
import secrets

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models import Patient, PatientAccountLink, PatientActivationToken, Role, UserAccount, UserRole
from app.schemas import patient_portal as s
from app.security.passwords import hash_password
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import retry_deadlocks

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


def activation_status(db, patient_id):
    get_record(db, Patient, patient_id)
    if db.scalar(select(PatientAccountLink.patient_id).where(PatientAccountLink.patient_id == patient_id)) is not None:
        return s.ActivationStatus(status='ACTIVATED')
    latest = db.scalar(select(PatientActivationToken).where(PatientActivationToken.patient_id == patient_id,
        PatientActivationToken.used_at.is_(None), PatientActivationToken.revoked_at.is_(None))
        .order_by(PatientActivationToken.activation_token_id.desc()).limit(1))
    state = 'NOT_ACTIVATED' if latest is None else ('TOKEN_ACTIVE' if latest.expires_at > utc_now() else 'TOKEN_EXPIRED')
    return s.ActivationStatus(status=state)


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
                or token.expires_at <= utc_now() or account_link(db, patient.patient_id) is not None):
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
