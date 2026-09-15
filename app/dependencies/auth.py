"""Cookie authentication automatically enforces CSRF on every unsafe method."""

from ipaddress import ip_address
from typing import Generator

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import AuthSession, UserAccount
from app.security.tokens import hash_token, secure_compare
from app.services.auth_service import utc_now
from app.services.rbac_service import get_user_permissions, get_user_roles, SYSTEM_ADMIN_ROLE_CODE

_session_cookie = APIKeyCookie(
    name=settings.auth_session_cookie_name, auto_error=False,
    description="Opaque session cookie issued by login. Unsafe methods also require X-CSRF-Token.",
)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        try:
            yield db
        except SQLAlchemyError:
            db.rollback()
            # Never let a database exception print SQL parameters or private hashes.
            raise HTTPException(503, "Database temporarily unavailable.") from None
        except Exception:
            db.rollback()
            raise


def get_request_ip(request: Request) -> str | None:
    # Uvicorn interprets proxy headers only from its configured trusted peers.
    # Never independently trust a browser-supplied X-Forwarded-For header.
    if request.client is None:
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        return None


def validate_csrf(request: Request, session: AuthSession) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    token = request.headers.get("X-CSRF-Token")
    if not token or len(token) > 256 or not secure_compare(
        hash_token(token), session.csrf_token_hash
    ):
        raise HTTPException(403, "Invalid or missing CSRF token.")


def get_current_session(
    request: Request,
    session_token: str | None = Depends(_session_cookie),
    db: Session = Depends(get_db),
) -> AuthSession:
    if not session_token or len(session_token) > 256:
        raise HTTPException(401, "Authentication required.")
    session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == hash_token(session_token),
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > utc_now(),
    ))
    if session is None or session.user.account_status != "ACTIVE":
        raise HTTPException(401, "Authentication required.")
    validate_csrf(request, session)
    return session


def get_current_user(session: AuthSession = Depends(get_current_session)) -> UserAccount:
    return session.user


def require_role(*role_codes: str):
    """Allow any named active role. SYSTEM_ADMIN does not bypass explicit roles."""
    if not role_codes:
        raise ValueError("At least one role code is required.")

    def dependency(
        user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db),
    ) -> UserAccount:
        if not set(role_codes).intersection(get_user_roles(db, user.user_id)):
            raise HTTPException(403, "Insufficient privileges.")
        return user

    return dependency


def require_permission(*permission_codes: str):
    """Allow any named permission; an active SYSTEM_ADMIN bypasses permission checks."""
    if not permission_codes:
        raise ValueError("At least one permission code is required.")

    def dependency(
        user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db),
    ) -> UserAccount:
        roles = get_user_roles(db, user.user_id)
        if SYSTEM_ADMIN_ROLE_CODE not in roles and not set(permission_codes).intersection(
            get_user_permissions(db, user.user_id)
        ):
            raise HTTPException(403, "Insufficient privileges.")
        return user

    return dependency
