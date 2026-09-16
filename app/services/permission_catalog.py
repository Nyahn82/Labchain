"""Stable Phase 3B/3C/4A permission metadata; never grant permissions implicitly."""

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
    ('LAB_MASTER_READ', 'Read laboratory master data', 'View laboratory configuration and select reference ranges.'),
    ('LAB_DEPARTMENT_MANAGE', 'Manage laboratory departments', 'Create, update and deactivate laboratory departments.'),
    ('SAMPLE_TYPE_MANAGE', 'Manage sample types', 'Create, update and deactivate sample types.'),
    ('TEST_CATALOG_MANAGE', 'Manage test catalog', 'Manage individual tests and their allowed sample types.'),
    ('TEST_PANEL_MANAGE', 'Manage test panels', 'Manage panels, sections and test composition.'),
    ('REFERENCE_RANGE_MANAGE', 'Manage reference ranges', 'Manage reference range configuration and applicability.'),
    ('INTERPRETATION_RULE_MANAGE', 'Manage interpretation rules', 'Manage approved general explanatory text only.'),
    ('LAB_ORDER_READ', 'Read laboratory orders', 'View orders and their workflow details.'),
    ('LAB_ORDER_CREATE', 'Create laboratory orders', 'Request individual tests and expand panels.'),
    ('LAB_ORDER_CANCEL', 'Cancel laboratory orders', 'Cancel unfinished laboratory orders.'),
    ('PAYMENT_READ', 'Read payment history', 'View laboratory order payment history.'),
    ('PAYMENT_RECORD', 'Record payment history', 'Append laboratory payment status records.'),
    ('SPECIMEN_READ', 'Read specimens', 'View specimens, mappings and rejection history.'),
    ('SPECIMEN_REGISTER', 'Register specimens', 'Register specimens mapped to requested tests.'),
    ('SPECIMEN_COLLECT', 'Collect specimens', 'Record specimen collection.'),
    ('SPECIMEN_RECEIVE', 'Receive specimens', 'Record receipt of collected specimens.'),
    ('SPECIMEN_REJECT', 'Reject specimens', 'Reject collected or received specimens.'),
    ('REJECTION_REASON_MANAGE', 'Manage rejection reasons', 'View, create and update specimen rejection reasons.'),
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
