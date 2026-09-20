"""Account-serialized MFA operations. Failed challenges commit their attempt count."""
from dataclasses import dataclass, field
from datetime import timedelta, timezone
import secrets

from fastapi import HTTPException
import pyotp
from sqlalchemy import select, update

from app.config import settings
from app.models import AuthSession, MfaChallenge, MfaRecoveryCode, UserAccount, UserTotpMfa
from app.security.mfa_crypto import decode_key, decrypt_secret, encrypt_secret
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import retry_deadlocks


@dataclass
class ChallengeRequired:
    token: str = field(repr=False)


@dataclass
class ChallengeFailure:
    clear_cookie: bool = False
    unavailable: bool = False


def current(statement):
    return statement.with_for_update().execution_options(populate_existing=True)


def configuration(db, user_id, *, lock=True):
    statement = select(UserTotpMfa).where(UserTotpMfa.user_id == user_id)
    return db.scalar(current(statement) if lock else statement)


def enabled(mfa):
    return mfa is not None and mfa.confirmed_at is not None and mfa.enabled_at is not None and mfa.disabled_at is None


def revoke_challenges(db, user_id, now):
    db.execute(update(MfaChallenge).where(MfaChallenge.user_id == user_id,
        MfaChallenge.used_at.is_(None), MfaChallenge.revoked_at.is_(None)).values(revoked_at=now))


def revoke_sessions(db, user_id, now, except_id=None):
    statement = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_id is not None:
        statement = statement.where(AuthSession.session_id != except_id)
    db.execute(statement.values(revoked_at=now))


def revoke_codes(db, mfa_id, now):
    db.execute(update(MfaRecoveryCode).where(MfaRecoveryCode.mfa_id == mfa_id,
        MfaRecoveryCode.used_at.is_(None), MfaRecoveryCode.revoked_at.is_(None)).values(revoked_at=now))


def create_challenge(db, user, ip_address, user_agent):
    now = utc_now()
    revoke_challenges(db, user.user_id, now)
    token = secrets.token_urlsafe(32)
    db.add(MfaChallenge(user_id=user.user_id, token_hash=hash_token(token), created_at=now,
        expires_at=now+timedelta(minutes=settings.mfa_challenge_ttl_minutes), attempt_count=0,
        ip_address=ip_address, user_agent=user_agent[:255] if user_agent else None))
    return ChallengeRequired(token)


def secret_for(mfa):
    return decrypt_secret(mfa.secret_ciphertext, mfa.secret_nonce,
        decode_key(settings.mfa_secret_encryption_key.get_secret_value()), mfa.user_id)


def accept_totp(mfa, code, now):
    # PyOTP performs the OTP cryptography. The matching counter is persisted under
    # the account/MFA row locks, so concurrent requests cannot reuse a time step.
    totp = pyotp.TOTP(secret_for(mfa))
    counter = int(now.replace(tzinfo=timezone.utc).timestamp()) // totp.interval
    matches = [step for step in range(counter-settings.mfa_totp_valid_window,
        counter+settings.mfa_totp_valid_window+1)
        if pyotp.utils.strings_equal(totp.at(step*totp.interval), code)]
    if not matches or (mfa.last_used_counter is not None and max(matches) <= mfa.last_used_counter):
        return False
    mfa.last_used_counter = max(matches)
    return True


def canonical_recovery(code):
    # Generated lowercase hexadecimal preserves 128 bits of entropy.
    # Only surrounding whitespace and display hyphens are ignored.
    return code.strip().replace('-', '')


def new_recovery_codes(db, mfa, now):
    codes = []
    for _ in range(settings.mfa_recovery_code_count):
        raw = secrets.token_hex(16)  # 128 random bits; case is significant
        code = '-'.join(raw[i:i+8] for i in range(0, len(raw), 8))
        db.add(MfaRecoveryCode(mfa_id=mfa.mfa_id, code_hash=hash_token(raw), created_at=now))
        codes.append(code)
    return codes


def consume_recovery(db, mfa, code, now):
    row = db.scalar(current(select(MfaRecoveryCode).where(MfaRecoveryCode.mfa_id == mfa.mfa_id,
        MfaRecoveryCode.code_hash == hash_token(canonical_recovery(code)),
        MfaRecoveryCode.used_at.is_(None), MfaRecoveryCode.revoked_at.is_(None))))
    if row is None:
        return False
    row.used_at = now
    return True


def live_session(db, session):
    user = get_record(db, UserAccount, session.user_id, lock=True)
    live = db.scalar(current(select(AuthSession).where(AuthSession.session_id == session.session_id)))
    if user.account_status != 'ACTIVE' or live is None or live.revoked_at is not None or live.expires_at <= utc_now():
        raise HTTPException(401, 'Authentication required.')
    return user, live


def security_status(db, session):
    mfa = configuration(db, session.user_id, lock=False)
    codes = list(db.scalars(select(MfaRecoveryCode.recovery_code_id).where(
        MfaRecoveryCode.mfa_id == mfa.mfa_id, MfaRecoveryCode.used_at.is_(None),
        MfaRecoveryCode.revoked_at.is_(None)))) if enabled(mfa) else []
    return dict(mfa_required=settings.patient_mfa_required, totp_enabled=enabled(mfa),
        mfa_verified_for_current_session=enabled(mfa) and session.mfa_verified_at is not None,
        unused_recovery_codes=len(codes))


@retry_deadlocks
def enroll(db, session, ip_address):
    with mutation(db):
        user, _ = live_session(db, session)
        mfa = configuration(db, user.user_id)
        if enabled(mfa):
            raise HTTPException(409, 'MFA is already enabled.')
        secret = pyotp.random_base32()
        ciphertext, nonce = encrypt_secret(secret, decode_key(settings.mfa_secret_encryption_key.get_secret_value()), user.user_id)
        now = utc_now()
        if mfa is None:
            mfa = UserTotpMfa(user_id=user.user_id)
            db.add(mfa)
        else:
            revoke_codes(db, mfa.mfa_id, now)
        mfa.secret_ciphertext, mfa.secret_nonce, mfa.created_at = ciphertext, nonce, now
        mfa.confirmed_at = mfa.enabled_at = mfa.disabled_at = mfa.last_used_counter = None
        revoke_challenges(db, user.user_id, now)
        audit(db, user.user_id, 'PATIENT_MFA_ENROLL_START', 'user_account', user.user_id, ip_address)
        result = dict(secret=secret, provisioning_uri=pyotp.TOTP(secret).provisioning_uri(
            name=user.username, issuer_name=settings.mfa_totp_issuer))
    return result


def verified_factor(db, mfa, code, ip_address, actor_id):
    try:
        return accept_totp(mfa, code, utc_now())
    except ValueError:
        audit(db, actor_id, 'MFA_SECRET_UNAVAILABLE', 'user_account', mfa.user_id, ip_address)
        return None


@retry_deadlocks
def confirm(db, session, code, ip_address):
    with mutation(db):
        user, live = live_session(db, session)
        mfa = configuration(db, user.user_id)
        if mfa is None or enabled(mfa) or mfa.disabled_at is not None:
            raise HTTPException(409, 'Pending MFA enrollment required.')
        valid = verified_factor(db, mfa, code, ip_address, user.user_id)
        if valid:
            now = utc_now()
            mfa.confirmed_at = mfa.enabled_at = live.mfa_verified_at = now
            mfa.disabled_at = None
            revoke_sessions(db, user.user_id, now, except_id=live.session_id)
            revoke_challenges(db, user.user_id, now)
            codes = new_recovery_codes(db, mfa, now)
            audit(db, user.user_id, 'PATIENT_MFA_ENABLED', 'user_account', user.user_id, ip_address)
        elif valid is False:
            audit(db, user.user_id, 'MFA_CHALLENGE_FAILED', 'user_account', user.user_id, ip_address)
    if valid is None:
        raise HTTPException(503, 'MFA is temporarily unavailable.')
    if not valid:
        raise HTTPException(400, 'Invalid verification code.')
    return dict(enabled=True, recovery_codes=codes)


@retry_deadlocks
def verify_challenge(db, token, code, ip_address, user_agent, *, recovery=False):
    from app.services.auth_service import complete_login
    if not token or len(token) > 256:
        return ChallengeFailure(clear_cookie=True)
    with mutation(db):
        candidate = db.scalar(select(MfaChallenge).where(MfaChallenge.token_hash == hash_token(token)))
        if candidate is None:
            return ChallengeFailure(clear_cookie=True)
        user = get_record(db, UserAccount, candidate.user_id, lock=True)
        mfa = configuration(db, user.user_id)
        challenge = db.scalar(current(select(MfaChallenge).where(MfaChallenge.challenge_id == candidate.challenge_id)))
        now = utc_now()
        if (challenge is None or challenge.used_at is not None or challenge.revoked_at is not None
                or challenge.expires_at <= now or challenge.attempt_count >= settings.mfa_max_challenge_attempts
                or user.account_status != 'ACTIVE' or not enabled(mfa)):
            if challenge is not None and challenge.used_at is None:
                challenge.revoked_at = now
            return ChallengeFailure(clear_cookie=True)
        valid = consume_recovery(db, mfa, code, now) if recovery else verified_factor(db, mfa, code, ip_address, user.user_id)
        if not valid:
            challenge.attempt_count += 1
            exhausted = challenge.attempt_count >= settings.mfa_max_challenge_attempts
            if exhausted:
                challenge.revoked_at = now
            audit(db, user.user_id, 'MFA_CHALLENGE_FAILED', 'user_account', user.user_id, ip_address)
            return ChallengeFailure(clear_cookie=exhausted, unavailable=valid is None)
        challenge.used_at = now
        result = complete_login(db, user, ip_address, user_agent, mfa_verified_at=now)
        audit(db, user.user_id, 'MFA_CHALLENGE_SUCCESS', 'user_account', user.user_id, ip_address)
        if recovery:
            audit(db, user.user_id, 'MFA_RECOVERY_CODE_USED', 'user_account', user.user_id, ip_address)
    return result


def require_verified(live, mfa):
    if not enabled(mfa) or live.mfa_verified_at is None:
        raise HTTPException(403, 'MFA verification required.')


@retry_deadlocks
def regenerate(db, session, password, code, ip_address):
    with mutation(db):
        user, live = live_session(db, session)
        mfa = configuration(db, user.user_id)
        require_verified(live, mfa)
        if not verify_password(password, user.password_hash):
            raise HTTPException(400, 'Security verification failed.')
        valid = verified_factor(db, mfa, code, ip_address, user.user_id)
        if valid:
            now = utc_now()
            revoke_codes(db, mfa.mfa_id, now)
            revoke_sessions(db, user.user_id, now, except_id=live.session_id)
            revoke_challenges(db, user.user_id, now)
            codes = new_recovery_codes(db, mfa, now)
            audit(db, user.user_id, 'PATIENT_MFA_RECOVERY_CODES_REGENERATED', 'user_account', user.user_id, ip_address)
    if valid is None:
        raise HTTPException(503, 'MFA is temporarily unavailable.')
    if not valid:
        raise HTTPException(400, 'Security verification failed.')
    return dict(recovery_codes=codes)


def disable_configuration(db, mfa, now):
    mfa.disabled_at = now
    revoke_codes(db, mfa.mfa_id, now)
    revoke_challenges(db, mfa.user_id, now)
    revoke_sessions(db, mfa.user_id, now)


@retry_deadlocks
def disable(db, session, password, code, ip_address, *, recovery=False):
    with mutation(db):
        user, live = live_session(db, session)
        mfa = configuration(db, user.user_id)
        require_verified(live, mfa)
        if not verify_password(password, user.password_hash):
            raise HTTPException(400, 'Security verification failed.')
        valid = consume_recovery(db, mfa, code, utc_now()) if recovery else verified_factor(db, mfa, code, ip_address, user.user_id)
        if valid:
            disable_configuration(db, mfa, utc_now())
            audit(db, user.user_id, 'PATIENT_MFA_DISABLED', 'user_account', user.user_id, ip_address)
            if recovery:
                audit(db, user.user_id, 'MFA_RECOVERY_CODE_USED', 'user_account', user.user_id, ip_address)
    if valid is None:
        raise HTTPException(503, 'MFA is temporarily unavailable.')
    if not valid:
        raise HTTPException(400, 'Security verification failed.')


@retry_deadlocks
def admin_reset(db, user_id, actor_session, ip_address):
    from app.services.administration_service import actor_authority, lock_administration
    with mutation(db):
        lock_administration(db)
        actor_authority(db, actor_session.user_id, 'ACCOUNT_MFA_RESET')
        live_session(db, actor_session)
        get_record(db, UserAccount, user_id, lock=True)
        mfa = configuration(db, user_id)
        if not enabled(mfa):
            raise HTTPException(409, 'MFA is not enabled.')
        disable_configuration(db, mfa, utc_now())
        audit(db, actor_session.user_id, 'ACCOUNT_MFA_RESET', 'user_account', user_id, ip_address)


@retry_deadlocks
def change_password(db, session, current_password, new_password, ip_address):
    with mutation(db):
        user, _ = live_session(db, session)
        if not verify_password(current_password, user.password_hash) or new_password == current_password:
            raise HTTPException(400, 'Password change verification failed.')
        user.password_hash = hash_password(new_password)
        user.updated_at = utc_now()
        revoke_sessions(db, user.user_id, user.updated_at)
        revoke_challenges(db, user.user_id, user.updated_at)
        audit(db, user.user_id, 'PASSWORD_CHANGE', 'user_account', user.user_id, ip_address)
