"""Atomic account administration with serialized administrator safety checks."""

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.models import (
    AuthSession, PatientAccountLink, Permission, Role, RolePermission, Staff, StaffAccountLink,
    UserAccount, UserRole,
)
from app.schemas.administration import AccountResponse
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.security.passwords import hash_password
from app.services.rbac_service import SYSTEM_ADMIN_ROLE_CODE

ACCOUNT_LOAD_OPTIONS = (
    selectinload(UserAccount.user_roles).selectinload(UserRole.role),
    selectinload(UserAccount.staff_link).selectinload(StaffAccountLink.staff),
    selectinload(UserAccount.patient_link).selectinload(PatientAccountLink.patient),
)


def account_response(user):
    return AccountResponse(
        user_id=user.user_id, username=user.username, account_status=user.account_status,
        last_login_at=user.last_login_at, created_at=user.created_at,
        roles=sorted(assignment.role.role_code for assignment in user.user_roles),
        staff=user.staff_link.staff if user.staff_link else None,
        patient=user.patient_link.patient if user.patient_link else None,
    )


def lock_administration(db):
    # Existing ROLE row is the shared mutex across workers/processes. Always
    # acquire this before locking an account. Locking reads below see committed
    # state even when auth SELECTs established a MySQL REPEATABLE READ snapshot.
    return db.scalar(select(Role).where(Role.role_code == SYSTEM_ADMIN_ROLE_CODE)
                     .with_for_update().execution_options(populate_existing=True))


def current_roles(db, user_id):
    return list(db.scalars(select(Role).join(UserRole, UserRole.role_id == Role.role_id)
                          .where(UserRole.user_id == user_id).order_by(Role.role_id)
                          .with_for_update().execution_options(populate_existing=True)))


def role_permissions(db, role_ids):
    return set(db.scalars(select(Permission.permission_code)
                         .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
                         .where(RolePermission.role_id.in_(role_ids)).with_for_update()))


def actor_authority(db, actor_id, required):
    actor = get_record(db, UserAccount, actor_id, lock=True)
    if actor.account_status != 'ACTIVE':
        raise HTTPException(401, 'Authentication required.')
    roles = [role for role in current_roles(db, actor_id) if role.is_active]
    admin = any(role.role_code == SYSTEM_ADMIN_ROLE_CODE for role in roles)
    permissions = role_permissions(db, [role.role_id for role in roles])
    if not admin and required not in permissions:
        raise HTTPException(403, 'Insufficient privileges.')
    return admin, permissions


def resolve_roles(db, codes):
    roles = list(db.scalars(select(Role).where(Role.role_code.in_(codes)).order_by(Role.role_id)
                           .with_for_update().execution_options(populate_existing=True)))
    # Compare canonical codes in Python too: MySQL collation may ignore case.
    if {role.role_code for role in roles} != set(codes):
        raise HTTPException(422, 'One or more role codes do not exist.')
    if any(not role.is_active for role in roles):
        raise HTTPException(422, 'Inactive roles cannot be assigned.')
    return roles


def authorize_role_grants(db, roles, admin, permissions):
    if admin:
        return
    if 'ROLE_ASSIGN' not in permissions:
        raise HTTPException(403, 'Role assignment permission required.')
    if any(role.role_code == SYSTEM_ADMIN_ROLE_CODE for role in roles):
        raise HTTPException(403, 'Only SYSTEM_ADMIN may assign SYSTEM_ADMIN.')
    if not role_permissions(db, [role.role_id for role in roles]) <= permissions:
        raise HTTPException(403, 'Cannot assign permissions beyond your own authority.')


def protect_last_admin(db, user, existing_roles, admin_role):
    if user.account_status != 'ACTIVE' or admin_role is None or not admin_role.is_active:
        return
    if not any(role.role_id == admin_role.role_id for role in existing_roles):
        return
    # Current locking read, not a count from the older authentication snapshot.
    active_ids = set(db.scalars(select(UserAccount.user_id)
                               .join(UserRole, UserRole.user_id == UserAccount.user_id)
                               .where(UserRole.role_id == admin_role.role_id,
                                      UserAccount.account_status == 'ACTIVE')
                               .order_by(UserAccount.user_id).with_for_update()))
    if active_ids <= {user.user_id}:
        raise HTTPException(409, 'The last active SYSTEM_ADMIN must remain usable.')


def assign_roles(db, user_id, roles, actor_id):
    now = utc_now()
    for role in roles:
        db.add(UserRole(user_id=user_id, role_id=role.role_id, assigned_by=actor_id, assigned_at=now))


def create_staff_account(db, staff_id, payload, actor_id, ip_address):
    with mutation(db):
        lock_administration(db)
        admin, permissions = actor_authority(db, actor_id, 'ACCOUNT_CREATE')
        staff = get_record(db, Staff, staff_id, lock=True)
        if not staff.is_active:
            raise HTTPException(409, 'Staff must be active to create an account.')
        if db.get(StaffAccountLink, staff_id) is not None:
            raise HTTPException(409, 'Staff already has an account.')
        if db.scalar(select(UserAccount.user_id).where(UserAccount.username == payload.username)) is not None:
            raise HTTPException(409, 'Username already exists.')
        roles = resolve_roles(db, payload.role_codes)
        if roles:
            authorize_role_grants(db, roles, admin, permissions)
        user = UserAccount(username=payload.username,
                           password_hash=hash_password(payload.password.get_secret_value()),
                           account_status='ACTIVE')
        db.add(user)
        db.flush()
        db.add(StaffAccountLink(staff_id=staff_id, user_id=user.user_id))
        assign_roles(db, user.user_id, roles, actor_id)
        audit(db, actor_id, 'STAFF_ACCOUNT_CREATE', 'user_account', user.user_id, ip_address,
              new={'staff_id': staff_id, 'role_ids': [role.role_id for role in roles]})
        db.flush()
        result = account_response(user)
    return result


def update_status(db, user_id, payload, actor_id, ip_address):
    with mutation(db):
        admin_role = lock_administration(db)
        admin, _ = actor_authority(db, actor_id, 'ACCOUNT_STATUS_UPDATE')
        user = get_record(db, UserAccount, user_id, lock=True)
        roles = current_roles(db, user_id)
        if not admin and any(role.role_code == SYSTEM_ADMIN_ROLE_CODE for role in roles):
            raise HTTPException(403, 'Only SYSTEM_ADMIN may manage administrator accounts.')
        if payload.account_status != 'ACTIVE':
            protect_last_admin(db, user, roles, admin_role)
        old_status = user.account_status
        user.account_status = payload.account_status
        user.updated_at = utc_now()
        if payload.account_status in {'INACTIVE', 'LOCKED'}:
            db.execute(update(AuthSession).where(AuthSession.user_id == user_id,
                                                AuthSession.revoked_at.is_(None))
                       .values(revoked_at=user.updated_at))
        audit(db, actor_id, 'ACCOUNT_STATUS_UPDATE', 'user_account', user_id, ip_address,
              old={'account_status': old_status}, new={'account_status': payload.account_status})
        db.flush()
        result = account_response(user)
    return result


def replace_roles(db, user_id, payload, actor_id, ip_address):
    with mutation(db):
        admin_role = lock_administration(db)
        admin, permissions = actor_authority(db, actor_id, 'ROLE_ASSIGN')
        user = get_record(db, UserAccount, user_id, lock=True)
        existing = current_roles(db, user_id)
        roles = resolve_roles(db, payload.role_codes)
        if not admin and any(role.role_code == SYSTEM_ADMIN_ROLE_CODE for role in existing):
            raise HTTPException(403, 'Only SYSTEM_ADMIN may manage administrator accounts.')
        authorize_role_grants(db, roles, admin, permissions)
        if not any(role.role_code == SYSTEM_ADMIN_ROLE_CODE for role in roles):
            protect_last_admin(db, user, existing, admin_role)
        db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        assign_roles(db, user_id, roles, actor_id)
        audit(db, actor_id, 'USER_ROLES_UPDATE', 'user_account', user_id, ip_address,
              old={'role_ids': sorted(role.role_id for role in existing)},
              new={'role_ids': sorted(role.role_id for role in roles)})
        db.flush()
        db.expire(user, ['user_roles'])
        result = account_response(user)
    return result
