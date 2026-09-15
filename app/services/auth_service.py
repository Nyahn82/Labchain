"""Atomic authentication writes. Tokens exist only in memory and browser cookies."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, AuthSession, LoginLog, UserAccount
from app.schemas.auth import LoginResponse
from app.security.passwords import hash_password, password_needs_rehash, verify_password
from app.security.tokens import hash_token
from app.services.rbac_service import get_user_roles


def utc_now() -> datetime:
    """MySQL DATETIME values are stored as naive UTC throughout authentication."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class LoginResult:
    account: LoginResponse
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)


def authenticate(
    db: Session, username: str, password: str, *, ip_address: str | None,
    user_agent: str | None, previous_token: str | None = None,
) -> LoginResult | None:
    with db.begin():
        # Serialize session issuance with administrative status changes/revocation.
        user = db.scalar(select(UserAccount).where(UserAccount.username == username).with_for_update())
        valid = verify_password(password, user.password_hash if user else None)
        now = utc_now()
        allowed = user is not None and valid and user.account_status == "ACTIVE"
        db.add(LoginLog(
            user_id=user.user_id if user else None, username_attempted=username,
            login_time=now, ip_address=ip_address, status="SUCCESS" if allowed else "FAILED",
        ))
        if not allowed:
            # Returning exits the transaction normally: persist the failed attempt.
            return None

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        if previous_token and len(previous_token) <= 256:
            # Replace the current browser's old session on successful re-login.
            db.execute(update(AuthSession).where(
                AuthSession.token_hash == hash_token(previous_token),
                AuthSession.revoked_at.is_(None),
            ).values(revoked_at=now))
        db.add(AuthSession(
            user_id=user.user_id, token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token), created_at=now,
            expires_at=now + timedelta(minutes=settings.auth_session_ttl_minutes),
            ip_address=ip_address, user_agent=user_agent[:255] if user_agent else None,
        ))
        user.last_login_at = now
        db.add(AuditLog(
            user_id=user.user_id, action="AUTH_LOGIN", entity_type="user_account",
            record_id=user.user_id, ip_address=ip_address, created_at=now,
        ))
        account = LoginResponse(
            user_id=user.user_id, username=user.username, account_status=user.account_status,
            roles=get_user_roles(db, user.user_id),
        )
    return LoginResult(account, session_token, csrf_token)


def revoke_session(db: Session, session: AuthSession, ip_address: str | None) -> None:
    # Authentication already opened this request's transaction. Commit once;
    # get_db rolls back all changes on failure, including the audit event.
    session.revoked_at = utc_now()
    db.add(AuditLog(
        user_id=session.user_id, action="AUTH_LOGOUT", entity_type="auth_session",
        record_id=session.session_id, ip_address=ip_address, created_at=session.revoked_at,
    ))
    db.commit()
