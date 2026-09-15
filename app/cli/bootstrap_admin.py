"""Interactive first-administrator bootstrap. No password arguments or defaults."""

import argparse
import getpass
import sys
import warnings
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AuditLog, Role, UserAccount, UserRole
from app.security.passwords import hash_password
from app.services.rbac_service import ensure_core_roles, SYSTEM_ADMIN_ROLE_CODE


def create_admin(db: Session, username: str, password: str) -> dict:
    """Create account, missing core roles, assignment and audit event atomically."""
    username = username.strip()
    if not 1 <= len(username) <= 60:
        raise ValueError("Username must contain 1 to 60 characters.")
    if not 12 <= len(password) <= 1024:
        raise ValueError("Password must contain 12 to 1024 characters.")
    with db.begin():
        if db.scalar(select(UserAccount.user_id).where(UserAccount.username == username)) is not None:
            raise ValueError("Username already exists; no account was changed.")
        ensure_core_roles(db)
        role = db.scalar(select(Role).where(Role.role_code == SYSTEM_ADMIN_ROLE_CODE))
        if not role.is_active:
            raise ValueError("SYSTEM_ADMIN is inactive; review the existing role before bootstrapping.")
        user = UserAccount(username=username, password_hash=hash_password(password), account_status="ACTIVE")
        db.add(user)
        db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(UserRole(user_id=user.user_id, role_id=role.role_id, assigned_at=now))
        db.add(AuditLog(
            user_id=user.user_id, action="AUTH_BOOTSTRAP_ADMIN", entity_type="user_account",
            record_id=user.user_id, created_at=now,
        ))
        result = {"user_id": user.user_id, "username": user.username}
    return result


def bootstrap_admin(username: str | None = None) -> dict:
    username = input("Username: ") if username is None else username
    # Fail instead of getpass's echoing fallback when no secure terminal exists.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Password (at least 12 characters): ")
        confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    with SessionLocal() as db:
        return create_admin(db, username, password)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create an administrator using a hidden password prompt.")
    parser.add_argument("--username", help="Username; prompted when omitted")
    args = parser.parse_args(argv)
    try:
        result = bootstrap_admin(args.username)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Administrator creation cancelled; a secure interactive terminal is required.", file=sys.stderr)
        raise SystemExit(1) from None
    except SQLAlchemyError:
        print("Administrator creation failed. Check database availability, migrations and username uniqueness.", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Created administrator: {result['username']}")


if __name__ == "__main__":
    main()
