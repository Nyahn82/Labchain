from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import Permission, Role, RolePermission, UserRole

SYSTEM_ADMIN_ROLE_CODE = "SYSTEM_ADMIN"


def get_user_roles(db: Session, user_id: int) -> list[str]:
    rows = db.execute(
        select(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
        .where(Role.is_active.is_(True))
    ).scalars().all()
    return sorted(rows)


def get_user_permissions(db: Session, user_id: int) -> list[str]:
    rows = db.execute(
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
        .join(Role, Role.role_id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
        .where(Role.is_active.is_(True))
    ).scalars().all()
    return sorted(set(rows))


def active_roles_for_user(db: Session, user_id: int) -> list[Role]:
    return db.execute(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
        .where(Role.is_active.is_(True))
    ).scalars().all()


def user_has_role(db: Session, user_id: int, role_code: str) -> bool:
    return role_code in get_user_roles(db, user_id)


def user_has_permission(db: Session, user_id: int, permission_code: str) -> bool:
    if user_has_role(db, user_id, SYSTEM_ADMIN_ROLE_CODE):
        return True
    return permission_code in get_user_permissions(db, user_id)


def ensure_core_roles(db: Session) -> list[str]:
    role_rows = [
        ("SYSTEM_ADMIN", "System Administrator", "Primary application administrator"),
        ("LAB_STAFF", "Laboratory Staff", "Laboratory operations and specimen handling."),
        ("LAB_SUPERVISOR", "Laboratory Supervisor", "Lab oversight and review."),
        ("DOCTOR", "Doctor", "Clinical ordering and patient access."),
        ("PATIENT", "Patient", "Patient-facing access."),
    ]
    created = []
    for role_code, role_name, description in role_rows:
        existing = db.execute(select(Role).where(Role.role_code == role_code)).scalar_one_or_none()
        if existing is None:
            db.add(Role(role_code=role_code, role_name=role_name, description=description, is_active=True))
            created.append(role_code)
    db.flush()
    return created


__all__ = [
    "SYSTEM_ADMIN_ROLE_CODE",
    "active_roles_for_user",
    "ensure_core_roles",
    "get_user_permissions",
    "get_user_roles",
    "user_has_permission",
    "user_has_role",
]
