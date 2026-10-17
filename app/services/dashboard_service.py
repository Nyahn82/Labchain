"""Current workflow counts without patient or report content projections."""
from datetime import datetime, timezone
from sqlalchemy import func, select
from app.models import LabOrder, LabReport, LabResultItem, Patient, Specimen
from app.services.rbac_service import get_user_permissions, get_user_roles, SYSTEM_ADMIN_ROLE_CODE


WORKFLOWS = (
    ('orders', 'LAB_ORDER_READ', LabOrder.status),
    ('specimens', 'SPECIMEN_READ', Specimen.specimen_status),
    ('results', 'LAB_RESULT_READ', LabResultItem.status),
    ('reports', 'REPORT_READ', LabReport.report_status),
)


def overview(db, user_id):
    admin = SYSTEM_ADMIN_ROLE_CODE in get_user_roles(db, user_id)
    permissions = set(get_user_permissions(db, user_id)) if not admin else set()
    response = {}
    if admin or 'PATIENT_READ' in permissions:
        response['patients'] = db.scalar(select(func.count()).select_from(Patient))
    for key, permission, column in WORKFLOWS:
        if admin or permission in permissions:
            # No joins: each stored record/version contributes exactly once.
            counts = {status: 0 for status in column.type.enums}
            counts.update({status: int(count) for status, count in db.execute(
                select(column, func.count()).group_by(column))})
            response[key] = {'total': sum(counts.values()), 'statuses': counts}
    response['generated_at'] = datetime.now(timezone.utc)
    return response
