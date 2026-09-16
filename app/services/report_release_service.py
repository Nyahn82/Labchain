"""Phase 5B immutable artifacts, public integrity checks and report version lifecycle."""
import hashlib
import hmac
from io import BytesIO
import logging
import re
import secrets

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.config import settings
from app.models import FacilityProfile, LabOrder, LabReport, PrintLog, ReportVerification
from app.schemas import reporting as s
from app.services import report_pdf, report_storage, reporting_service as snapshots
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import retry_deadlocks

logger = logging.getLogger(__name__)


def verification_url(token):
    if not settings.public_base_url:
        raise HTTPException(503, 'Public report verification is not configured.')
    return f'{settings.public_base_url}/api/v1/verify/{token}'


def locked_order_reports(db, report_id):
    # Same parent lock as initial generation, approval and all version mutations.
    parent_id = get_record(db, LabReport, report_id).order_id
    order = get_record(db, LabOrder, parent_id, lock=True)
    versions = list(db.scalars(snapshots.current(select(LabReport).where(
        LabReport.order_id == parent_id).order_by(LabReport.version_no, LabReport.report_id))))
    return order, next(row for row in versions if row.report_id == report_id), versions


def verifications(db, report_id, *, lock=True):
    return list(db.scalars(snapshots.current(select(ReportVerification).where(
        ReportVerification.report_id == report_id).order_by(ReportVerification.verification_id), lock)))


def active_verification(db, report_id):
    rows = [row for row in verifications(db, report_id) if row.verification_status == 'AUTHENTIC' and row.revoked_at is None]
    if len(rows) != 1:
        raise HTTPException(409, 'Report verification state is inconsistent.')
    return rows[0]


def revoke_record(db, report, actor_id, ip_address, reason, now, *, superseded=False):
    verification = active_verification(db, report.report_id)
    report.report_status = 'REVOKED'
    report.revoked_by_user_id, report.revoked_at, report.revocation_reason = actor_id, now, reason
    verification.verification_status, verification.revoked_at = 'REVOKED', now
    # Reasons may contain medical information: retain on report, never duplicate in audit.
    audit(db, actor_id, 'REPORT_REVOKE', 'lab_report', report.report_id, ip_address,
          old={'status': 'RELEASED'}, new={'status': 'REVOKED', 'superseded': superseded})


@retry_deadlocks
def release_report(db, report_id, actor_id, ip_address):
    artifact = None
    try:
        with mutation(db):
            order, report, versions = locked_order_reports(db, report_id)
            if report.report_status != 'APPROVED':
                raise HTTPException(409, 'Only APPROVED reports can be released.')
            if (report.approved_at is None or report.approved_by_user_id is None or
                    any(getattr(report, key) is not None for key in ('pdf_path', 'released_at', 'released_by_user_id',
                        'revoked_at', 'revoked_by_user_id', 'revocation_reason'))):
                raise HTTPException(409, 'Report lifecycle metadata is inconsistent.')
            if verifications(db, report_id):
                raise HTTPException(409, 'Report already has a verification record.')
            detail = snapshots.report_detail(db, report_id, lock=True)
            if (detail.patient_snapshot is None or not detail.result_snapshots or not detail.signatories
                    or any(row.signed_at is None for row in detail.signatories)):
                raise HTTPException(409, 'Complete snapshots and signed signatories are required.')
            # Phase 5A permits a null template for its generic renderer. When selected,
            # the template must still exist and be active, and match the report panel.
            if detail.template and (not detail.template.is_active or
                    (detail.template.panel_id is not None and detail.template.panel_id not in
                     {row.panel_id_snapshot for row in detail.result_snapshots})):
                raise HTTPException(409, 'The selected template is not valid for release.')
            sources = snapshots.verified_sources(db, order)
            expected = {source.result_item_id for _, source in sources}
            if ({line.result_item_id for line in detail.result_snapshots} != expected or
                    len(detail.result_snapshots) != len(expected)):
                raise HTTPException(409, 'Report sources are incomplete or no longer VERIFIED.')
            old = None
            if report.supersedes_report_id is not None:
                old = next((row for row in versions if row.report_id == report.supersedes_report_id), None)
                if old is None or old.version_no >= report.version_no or old.report_status not in {'RELEASED', 'REVOKED'}:
                    raise HTTPException(409, 'Superseded report state is inconsistent.')
            if any(row.report_id != report_id and (
                    (row.report_status == 'RELEASED' and row is not old) or
                    (row.version_no > report.version_no and row.released_at is not None)) for row in versions):
                raise HTTPException(409, 'Another report version has already been released; revise the current version.')
            token = secrets.token_urlsafe(32)
            url = verification_url(token)
            if settings.report_storage_dir is None:
                raise HTTPException(503, 'Report storage is not configured.')
            now = utc_now()
            try:
                data = report_pdf.render_pdf(detail, url, now)
                if not data.startswith(b'%PDF-') or not data.rstrip().endswith(b'%%EOF'):
                    raise ValueError('Invalid rendered artifact')
            except Exception:
                # Renderer exceptions must not expose snapshot data or local paths.
                raise HTTPException(503, 'Report PDF generation failed.') from None
            relative = f'released/{now:%Y}/{report.report_id}-{secrets.token_hex(16)}.pdf'
            try:
                artifact = report_storage.publish_pdf(data, relative)
            except report_storage.ArtifactUnavailable:
                raise HTTPException(503, 'Report storage is unavailable.') from None
            digest = hashlib.sha256(data).hexdigest()
            db.add(ReportVerification(report_id=report_id, verification_token=token, report_hash=digest,
                verification_status='AUTHENTIC', created_at=now, revoked_at=None))
            report.report_status = 'RELEASED'
            report.pdf_path, report.released_by_user_id, report.released_at = relative, actor_id, now
            if old and old.report_status == 'RELEASED':
                revoke_record(db, old, actor_id, ip_address, f'Superseded by report {report.report_code}', now, superseded=True)
                audit(db, actor_id, 'REPORT_SUPERSEDE', 'lab_report', old.report_id, ip_address,
                      new={'superseded_by_report_id': report_id})
            audit(db, actor_id, 'REPORT_RELEASE', 'lab_report', report_id, ip_address,
                  old={'status': 'APPROVED'}, new={'status': 'RELEASED', 'version_no': report.version_no})
            db.flush()
            response = snapshots.report_detail(db, report_id, lock=True)
        return response
    except Exception as exc:
        # Lost COMMIT acknowledgement is uncertain: keep the private file for manual
        # reconciliation instead of risking deletion of a successfully committed PDF.
        driver_args = getattr(getattr(exc, 'orig', None), 'args', ())
        driver_code = driver_args[0] if driver_args else None
        uncertain = isinstance(exc, DBAPIError) and (exc.connection_invalidated or driver_code in {2006, 2013})
        if artifact is not None and not uncertain:
            report_storage.remove_artifact(artifact)
        elif artifact is not None:
            logger.error('Report commit outcome uncertain; private artifact retained for reconciliation.')
        raise


def integrity_bytes(db, report, verification, actor_id, ip_address):
    try:
        data = report_storage.read_private(settings.report_storage_dir, report.pdf_path)
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), verification.report_hash):
            failure = 'HASH_MISMATCH'
        else:
            return data
    except report_storage.ArtifactUnavailable:
        failure = 'ARTIFACT_UNAVAILABLE'
    audit(db, actor_id, 'REPORT_INTEGRITY_MISMATCH', 'lab_report', report.report_id, ip_address,
          new={'severity': 'HIGH', 'failure': failure})
    logger.error('Report integrity check failed (report_id=%s, failure=%s).', report.report_id, failure)
    return None


def staff_pdf(db, report_id, actor_id, ip_address, *, copies=None):
    with mutation(db):
        _, report, _ = locked_order_reports(db, report_id)
        if report.report_status not in {'RELEASED', 'REVOKED'}:
            raise HTTPException(409, 'Only released or revoked historical reports have a final PDF.')
        rows = verifications(db, report_id)
        if len(rows) != 1:
            raise HTTPException(409, 'Report verification state is inconsistent.')
        data = integrity_bytes(db, report, rows[0], actor_id, ip_address)
        if data is not None:
            if copies is not None:
                db.add(PrintLog(report_id=report_id, printed_by_user_id=actor_id, printed_at=utc_now(), copies=copies))
            audit(db, actor_id, 'REPORT_PRINT' if copies is not None else 'REPORT_DOWNLOAD', 'lab_report', report_id,
                  ip_address, new={'copies': copies} if copies is not None else None)
        # Use server-owned numeric filename; report codes are never HTTP header data.
        filename = f'report-{report_id}-v{report.version_no}.pdf'
    if data is None:
        # Error is raised AFTER commit so the integrity audit survives.
        raise HTTPException(409, 'The stored PDF failed its integrity check or is unavailable.')
    # Stream the exact validated bytes, never reopen a path after validation.
    return StreamingResponse(BytesIO(data), media_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="{filename}"', 'Content-Length': str(len(data)),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


def verification_metadata(db, report_id):
    get_record(db, LabReport, report_id)
    rows = verifications(db, report_id, lock=False)
    if not rows:
        raise HTTPException(404, 'Report verification is not available.')
    row = rows[-1]
    return s.VerificationResponse(verification_status=row.verification_status, created_at=row.created_at,
        revoked_at=row.revoked_at, report_hash=row.report_hash, verification_url=verification_url(row.verification_token))


def public_verification(db, token, ip_address):
    neutral = s.PublicVerificationResponse(status='NOT_FOUND', message='Verification record not found.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return neutral
    with mutation(db):
        found = db.scalar(select(ReportVerification).where(ReportVerification.verification_token == token))
        # MySQL's default collation is case insensitive. Require exact token bytes.
        if found is None or not hmac.compare_digest(found.verification_token, token):
            return neutral
        _, report, _ = locked_order_reports(db, found.report_id)
        rows = verifications(db, report.report_id)
        verification = next(row for row in rows if row.verification_id == found.verification_id)
        if report.report_status == 'REVOKED' or verification.verification_status == 'REVOKED' or verification.revoked_at:
            status, message = 'REVOKED', 'This report has been revoked.'
        elif report.report_status != 'RELEASED' or len(rows) != 1:
            return neutral
        elif integrity_bytes(db, report, verification, None, ip_address) is None:
            status, message = 'ALTERED', 'The stored report failed its integrity check or is unavailable.'
        else:
            status, message = 'VERIFIED', 'The released report matches the stored integrity record.'
        facility = get_record(db, FacilityProfile, report.facility_id)
        response = s.PublicVerificationResponse(status=status, message=message, issuing_facility=facility.facility_name,
            report_date=report.released_at.date() if report.released_at else None, version=report.version_no)
    return response


@retry_deadlocks
def revoke_report(db, report_id, payload, actor_id, ip_address):
    with mutation(db):
        _, report, _ = locked_order_reports(db, report_id)
        if report.report_status != 'RELEASED':
            raise HTTPException(409, 'Only RELEASED reports can be revoked.')
        revoke_record(db, report, actor_id, ip_address, payload.reason, utc_now())
        db.flush()
        response = snapshots.report_detail(db, report_id, lock=True)
    return response


@retry_deadlocks
def revise_report(db, report_id, payload, actor_id, ip_address):
    with mutation(db):
        order, source, versions = locked_order_reports(db, report_id)
        if source.report_status not in {'RELEASED', 'REVOKED'}:
            raise HTTPException(409, 'Only RELEASED or REVOKED reports can be revised.')
        values = payload.model_dump()
        if 'template_id' not in payload.model_fields_set:
            values['template_id'] = source.template_id
        report, count = snapshots.create_report_snapshots(db, order, s.GenerateRequest(**values), actor_id,
            version_no=max(row.version_no for row in versions) + 1, supersedes_report_id=report_id)
        audit(db, actor_id, 'REPORT_REVISE', 'lab_report', report.report_id, ip_address,
              new={'supersedes_report_id': report_id, 'version_no': report.version_no, 'result_count': count})
        response = snapshots.report_detail(db, report.report_id, lock=True)
    return response
