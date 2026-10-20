"""Redacted public evidence: registration never certifies a presented document."""
from datetime import datetime, timezone
import hmac
import json
import re

from sqlalchemy import select
from app.models import BlockchainEvent, LabReport, ReportVerification
from app.models.blockchain import OutboxIntegrityError
from app.schemas import blockchain_monitor as schemas
from app.schemas.reporting import PublicVerificationResponse
from app.services import blockchain_monitor_client as monitor
from app.services.blockchain_event_validation import validate_event, utc
from app.services.blockchain_monitor_service import artifact_hash
from app.services.identity_service import audit, mutation
from app.services.report_storage import ArtifactUnavailable
from app.config import settings


def ledger_evidence(db, report, digest, replacement):
    events = list(db.scalars(select(BlockchainEvent).where(
        BlockchainEvent.entity_type == 'REPORT', BlockchainEvent.entity_id == report.report_id)
        .order_by(BlockchainEvent.event_id).limit(5)))
    releases = [e for e in events if e.event_type == 'REPORT_RELEASED']
    if not events:
        return 'UNAVAILABLE', None
    if len(releases) != 1 or len(events) > 4:
        return 'FAILED', None
    release = releases[0]
    required = 'REPORT_SUPERSEDED' if replacement else 'REPORT_REVOKED' if report.report_status == 'REVOKED' else None
    if required and not any(e.event_type == required for e in events):
        return 'UNAVAILABLE', None
    if not required and any(e.event_type != 'REPORT_RELEASED' for e in events):
        return 'FAILED', None
    checked = []
    state = 'VERIFIED'
    for event in events:
        try:
            validate_event(event)
            payload = json.loads(event.canonical_payload)
            if (event.entity_reference != report.blockchain_entity_uuid or
                payload['artifact_sha256'] != digest or payload['report_version'] != report.version_no or
                (event is release and utc(event.occurred_at) != utc(report.released_at)) or
                (event is not release and (event.predecessor_event_id != release.event_id or event.previous_hash != release.record_hash)) or
                (event.event_type == 'REPORT_SUPERSEDED' and (replacement is None or payload['superseding_entity_reference'] != replacement.blockchain_entity_uuid))):
                return 'FAILED', None
        except (OutboxIntegrityError, ValueError, TypeError, KeyError):
            return 'FAILED', None
        if event.event_status in {'FAILED', 'DEAD'}:
            return 'FAILED', None
        if event.event_status != 'CONFIRMED':
            state = 'PENDING'
            continue
        try:
            anchor = monitor.query({'action': 'anchor', 'anchor_id': event.event_uuid}, schemas.AnchorEvidence)
            tx = monitor.query({'action': 'transaction', 'transaction_id': anchor.transaction_id}, schemas.TransactionDetail)
        except monitor.MonitorUnavailable:
            if state != 'PENDING': state = 'UNAVAILABLE'
            continue
        if anchor.source_node is None or anchor.source_msp is None:
            if state != 'PENDING': state = 'UNAVAILABLE'
            continue
        if not (anchor.anchor_id == event.event_uuid and anchor.entity_reference == event.entity_reference
            and anchor.event_type == event.event_type and anchor.content_hash == event.record_hash
            and anchor.previous_hash == event.previous_hash and anchor.transaction_id == event.fabric_transaction_id
            and anchor.source_node == payload['source_node'] and anchor.source_msp == payload['source_msp']
            and tx.transaction_id == anchor.transaction_id and tx.validation_code == 0
            and tx.validation_status == 'VALID' and event.fabric_validation_code == 0
            and event.fabric_block_number == tx.block_number):
            return 'FAILED', min(checked) if checked else None
        checked.extend([anchor.checked_at, tx.checked_at])
    observed = min(checked) if checked else None
    if state == 'VERIFIED' and (observed is None or not -5 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 60):
        state = 'UNAVAILABLE'
    return state, observed


def public_verification(db, token, ip_address, uploaded_digest=None):
    now = datetime.now(timezone.utc)
    result = PublicVerificationResponse(status='NOT_FOUND', message='Verification record not found.', checked_at=now,
        max_upload_bytes=settings.verification_upload_max_bytes)
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return result
    verification = db.scalar(select(ReportVerification).where(ReportVerification.verification_token == token))
    if verification is None or not hmac.compare_digest(verification.verification_token, token):
        return result
    report = db.get(LabReport, verification.report_id)
    if report is None or report.released_at is None or report.report_status not in {'RELEASED', 'REVOKED'}:
        return result
    if not re.fullmatch(r'[0-9a-f]{64}', verification.report_hash):
        result.status = 'UNAVAILABLE'
        return result
    rows = list(db.scalars(select(ReportVerification).where(ReportVerification.report_id == report.report_id)))
    if len(rows) != 1:
        result.status = 'UNAVAILABLE'
        return result
    replacement = db.scalar(select(LabReport).where(LabReport.supersedes_report_id == report.report_id,
        LabReport.released_at.is_not(None)).order_by(LabReport.version_no.desc()).limit(1))
    result.status = ('SUPERSEDED' if replacement else 'REVOKED' if report.report_status == 'REVOKED'
                     or verification.verification_status == 'REVOKED' or verification.revoked_at else 'REGISTERED')
    result.message = 'Registration identifies a report; compare the PDF to check its exact bytes.'
    result.report_code = report.report_code
    result.version = report.version_no
    result.report_date = report.released_at.date()
    result.released_at = report.released_at.replace(tzinfo=timezone.utc)
    presentation = report.presentation_snapshot
    facility = presentation.get('facility') if isinstance(presentation, dict) else None
    if isinstance(facility, dict) and facility.get('facility_id') == report.facility_id and isinstance(facility.get('facility_name'), str):
        result.issuing_facility = facility['facility_name']
        result.issuer_evidence = 'SNAPSHOT'
    else:
        result.issuer_evidence = 'LEGACY_UNAVAILABLE'
    result.document_comparison = ('NOT_COMPARED' if uploaded_digest is None else
        'MATCH' if hmac.compare_digest(uploaded_digest, verification.report_hash) else 'MISMATCH')
    failure = None
    try:
        result.stored_artifact = 'MATCH' if hmac.compare_digest(artifact_hash(report.pdf_path), verification.report_hash) else 'MISMATCH'
        if result.stored_artifact == 'MISMATCH': failure = 'HASH_MISMATCH'
    except (OSError, ValueError, RuntimeError, ArtifactUnavailable):
        result.stored_artifact = 'UNAVAILABLE'
        failure = 'ARTIFACT_UNAVAILABLE'
    if failure:
        with mutation(db):
            audit(db, None, 'REPORT_INTEGRITY_MISMATCH', 'lab_report', report.report_id, ip_address,
                  new={'severity': 'HIGH', 'failure': failure})
    # Read-only independent ledger queries; no submission, backfill or clinical changes.
    marker = (report.report_status, report.revoked_at, verification.verification_status, verification.report_hash)
    result.blockchain_evidence, result.blockchain_checked_at = ledger_evidence(db, report, verification.report_hash, replacement)
    replacement_id = replacement.report_id if replacement else None
    report_id = report.report_id
    verification_id = verification.verification_id
    db.rollback()  # End the read snapshot before checking for a concurrent lifecycle change.
    current = db.get(LabReport, report_id, populate_existing=True)
    v = db.get(ReportVerification, verification_id, populate_existing=True)
    current_replacement = db.scalar(select(LabReport.report_id).where(LabReport.supersedes_report_id == report_id,
        LabReport.released_at.is_not(None)).order_by(LabReport.version_no.desc()).limit(1))
    if current_replacement != replacement_id or current is None or v is None or marker != (current.report_status, current.revoked_at, v.verification_status, v.report_hash):
        result.status = 'UNAVAILABLE'
        result.blockchain_evidence = 'UNAVAILABLE'
        result.document_comparison = 'NOT_COMPARED'
        result.message = 'Report state changed during verification. Check again.'
    result.checked_at = datetime.now(timezone.utc)
    return result
