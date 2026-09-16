"""Ownership-filtered portal reads. Staff report schemas never cross this boundary."""
from datetime import datetime, time
from io import BytesIO

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.models import AuditLog, FacilityProfile, LabOrder, LabReport, PatientAccountLink, ReportVerification
from app.schemas import patient_portal as s
from app.services import report_release_service as artifacts, reporting_service as snapshots
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import retry_deadlocks

PATIENT_ACTIONS = ('PATIENT_REPORT_VIEW', 'PATIENT_REPORT_DOWNLOAD')


def owned_reports(context):
    return select(LabReport).join(LabOrder, LabOrder.order_id == LabReport.order_id).join(
        PatientAccountLink, PatientAccountLink.patient_id == LabOrder.patient_id).where(
        PatientAccountLink.user_id == context.user_id, PatientAccountLink.patient_id == context.patient.patient_id,
        LabReport.report_status == 'RELEASED')


def require_patient_report_ownership(db, context, report_id):
    statement = owned_reports(context).where(LabReport.report_id == report_id)
    report = db.scalar(statement)
    if report is None:
        raise HTTPException(404, 'Report not found.')
    # Match Phase 5B's order-before-report lock order, then repeat the complete
    # ownership/status predicate as a current read (not a stale MySQL snapshot).
    get_record(db, LabOrder, report.order_id, lock=True)
    report = db.scalar(statement.with_for_update().execution_options(populate_existing=True))
    if report is None:
        raise HTTPException(404, 'Report not found.')
    return report


def report_list(db, context, filters):
    statement = owned_reports(context)
    if filters.date_from:
        statement = statement.where(LabReport.released_at >= datetime.combine(filters.date_from, time.min))
    if filters.date_to:
        statement = statement.where(LabReport.released_at <= datetime.combine(filters.date_to, time.max))
    if filters.search and filters.search.strip():
        statement = statement.where(or_(LabReport.report_code.icontains(filters.search.strip(), autoescape=True),
            LabOrder.order_code.icontains(filters.search.strip(), autoescape=True)))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    verification = select(ReportVerification.verification_status).where(
        ReportVerification.report_id == LabReport.report_id).order_by(ReportVerification.verification_id.desc())
    statement = statement.join(FacilityProfile, FacilityProfile.facility_id == LabReport.facility_id).add_columns(
        LabOrder.order_code, FacilityProfile.facility_name, verification.limit(1).scalar_subquery())
    rows = db.execute(statement.order_by(LabReport.released_at.desc(), LabReport.report_id.desc())
        .offset((filters.page-1)*filters.page_size).limit(filters.page_size))
    items = [s.ReportSummary(report_id=row.report_id, report_code=row.report_code, version_no=row.version_no,
        released_at=row.released_at, order_code=order_code, issuing_facility=facility, verification_status=status)
        for row, order_code, facility, status in rows]
    return dict(items=items, page=filters.page, page_size=filters.page_size, total=total)


@retry_deadlocks
def report_detail(db, context, report_id, ip_address):
    with mutation(db):
        report = require_patient_report_ownership(db, context, report_id)
        detail = snapshots.report_detail(db, report_id, lock=True)
        if detail.patient_snapshot is None:
            raise HTTPException(409, 'Report content is unavailable.')
        order = get_record(db, LabOrder, report.order_id)
        result = s.ReportDetail(report_id=report_id, report_code=report.report_code, version_no=report.version_no,
            report_status='RELEASED', released_at=report.released_at, generated_at=report.generated_at,
            order_code=order.order_code, issuing_facility=detail.facility.facility_name,
            verification_status=detail.verification_status, facility=s.Facility.model_validate(detail.facility),
            patient_snapshot=s.PatientSnapshot.model_validate(detail.patient_snapshot),
            result_snapshots=[s.ResultSnapshot.model_validate(line) for line in detail.result_snapshots],
            signatories=[s.Signatory(staff_name=row.staff_name, signatory_type=row.signatory_type,
                license_number_snapshot=row.profile.license_number_snapshot, signed_at=row.signed_at,
                sort_order=row.sort_order) for row in detail.signatories])
        audit(db, context.user_id, 'PATIENT_REPORT_VIEW', 'LAB_REPORT', report_id, ip_address)
    return result


@retry_deadlocks
def report_pdf(db, context, report_id, ip_address):
    with mutation(db):
        report = require_patient_report_ownership(db, context, report_id)
        rows = artifacts.verifications(db, report_id)
        if len(rows) != 1 or rows[0].verification_status != 'AUTHENTIC' or rows[0].revoked_at is not None:
            audit(db, context.user_id, 'REPORT_INTEGRITY_MISMATCH', 'lab_report', report_id, ip_address,
                  new={'severity': 'HIGH', 'failure': 'VERIFICATION_UNAVAILABLE'})
            data = None
        else:
            data = artifacts.integrity_bytes(db, report, rows[0], context.user_id, ip_address)
        if data is not None:
            audit(db, context.user_id, 'PATIENT_REPORT_DOWNLOAD', 'LAB_REPORT', report_id, ip_address)
        filename = f'report-{report_id}-v{report.version_no}.pdf'
    if data is None:
        # Preserve the integrity audit even though delivery is denied.
        raise HTTPException(409, 'The stored PDF failed its integrity check or is unavailable.')
    return StreamingResponse(BytesIO(data), media_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="{filename}"', 'Content-Length': str(len(data)),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


def access_history(db, context, paging):
    # Include this user's historical events even after revocation, but recheck
    # account-linked ownership before displaying a report reference.
    statement = select(AuditLog.action, AuditLog.created_at, LabReport.report_code).join(
        LabReport, LabReport.report_id == AuditLog.record_id).join(LabOrder, LabOrder.order_id == LabReport.order_id).join(
        PatientAccountLink, PatientAccountLink.patient_id == LabOrder.patient_id).where(
        AuditLog.user_id == context.user_id, AuditLog.action.in_(PATIENT_ACTIONS), AuditLog.entity_type == 'LAB_REPORT',
        PatientAccountLink.user_id == context.user_id, PatientAccountLink.patient_id == context.patient.patient_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(AuditLog.created_at.desc(), AuditLog.audit_id.desc())
        .offset((paging.page-1)*paging.page_size).limit(paging.page_size))
    return dict(items=[s.AccessEvent(action=action, timestamp=timestamp, report_code=code) for action, timestamp, code in rows],
                page=paging.page, page_size=paging.page_size, total=total)
