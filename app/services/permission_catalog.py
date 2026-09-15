"""Stable Phase 3B permission metadata; never grant permissions implicitly."""

from sqlalchemy import select
from app.models import Permission

PERMISSION_CATALOG = (
    ('PATIENT_READ', 'Read patients', 'View and search patient records.'),
    ('PATIENT_CREATE', 'Create patients', 'Create patient demographic records.'),
    ('PATIENT_UPDATE', 'Update patients', 'Update patient demographic records.'),
    ('STAFF_READ', 'Read staff', 'View and search staff records.'),
    ('STAFF_CREATE', 'Create staff', 'Create staff identity records.'),
    ('STAFF_UPDATE', 'Update staff', 'Update and deactivate staff records.'),
    ('PHYSICIAN_READ', 'Read physicians', 'View and search requesting physicians.'),
    ('PHYSICIAN_CREATE', 'Create physicians', 'Create requesting physician records.'),
    ('PHYSICIAN_UPDATE', 'Update physicians', 'Update and deactivate requesting physicians.'),
    ('REFERRING_FACILITY_READ', 'Read referring facilities', 'View and search referring facilities.'),
    ('REFERRING_FACILITY_CREATE', 'Create referring facilities', 'Create referring facility records.'),
    ('REFERRING_FACILITY_UPDATE', 'Update referring facilities', 'Update referring facility records.'),
    ('ACCOUNT_READ', 'Read accounts', 'View safe account metadata and linked identity summaries.'),
    ('ACCOUNT_CREATE', 'Create staff accounts', 'Create login accounts for active staff.'),
    ('ACCOUNT_STATUS_UPDATE', 'Update account status', 'Activate, deactivate or lock accounts and revoke sessions.'),
    ('ROLE_READ', 'Read roles and permissions', 'Discover role and permission metadata.'),
    ('ROLE_ASSIGN', 'Assign user roles', 'Replace user role assignments within the actor authority.'),
)


def ensure_permissions(db):
    existing = set(db.scalars(select(Permission.permission_code)))
    created = []
    for code, name, description in PERMISSION_CATALOG:
        if code not in existing:
            db.add(Permission(permission_code=code, permission_name=name, description=description))
            created.append(code)
    db.flush()
    return created
