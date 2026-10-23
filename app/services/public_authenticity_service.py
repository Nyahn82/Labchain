"""Redacted public evidence: registration never certifies a presented document."""
from datetime import datetime, timedelta, timezone
import hmac
import json
import re

from sqlalchemy import select
from app.models import BlockchainEvent, LabReport, ReportVerification
from app.models.blockchain import OutboxIntegrityError
from app.schemas import blockchain_monitor as schemas
from app.schemas.reporting import PublicVerificationResponse, PublicPeerEvidence
from app.services import blockchain_monitor_client as monitor
from app.services.blockchain_event_validation import validate_event, utc
from app.services.blockchain_monitor_service import artifact_hash
from app.services.identity_service import audit, mutation
from app.services.report_storage import ArtifactUnavailable
from app.config import settings


def release_time_matches(event_time, report_time):
    event_time, report_time = utc(event_time), utc(report_time)
    if event_time == report_time:
        return True
    # lab_report.released_at is MySQL DATETIME(0), while the immutable event is
    # DATETIME(6). MySQL rounds fractional seconds on storage. Compare that exact
    # representation, not a general time tolerance; never rewrite historical rows.
    return report_time.microsecond == 0 and report_time == (
        event_time + timedelta(microseconds=500000)).replace(microsecond=0)


PEER_MSPS = {'peer1': 'Org1MSP', 'peer2': 'Org1MSP', 'peer3': 'Org2MSP', 'peer4': 'Org2MSP'}


def peer_outcome(status, checked_at=None):
    return [dict(peer=peer, status=status, checked_at=checked_at) for peer in PEER_MSPS]


def aggregate_peer_evidence(observed, events, pending=False, details=None):
    """Validate every independently returned observation; disagreement never wins a vote."""
    now = datetime.now(timezone.utc)
    expected = {e.event_uuid: e for e in events}
    if observed.channel != 'labchain-channel' or sorted(p.peer for p in observed.peers) != sorted(PEER_MSPS):
        return 'FAILED', None, peer_outcome('FAILED')
    results, blocks, witnesses = [], {}, []
    priority = {'VERIFIED': 0, 'OFFLINE': 1, 'TIMEOUT': 2, 'UNAVAILABLE': 3,
                'MISSING': 4, 'LAGGING': 5, 'PENDING': 6, 'FAILED': 7, 'CONFLICT': 8}
    for peer in observed.peers:
        status = 'PENDING' if pending else 'VERIFIED'
        def mark(value):
            nonlocal status
            if priority[value] > priority[status]: status = value
        if peer.msp != PEER_MSPS[peer.peer] or peer.channel != 'labchain-channel': mark('FAILED')
        fresh = peer.checked_at.tzinfo is not None and -5 <= (now - peer.checked_at).total_seconds() <= 30
        if not fresh: mark('UNAVAILABLE')
        if sorted(e.anchor_id for e in peer.events) != sorted(expected): mark('FAILED')
        for observation in peer.events:
            event = expected.get(observation.anchor_id)
            if event is None: mark('FAILED'); continue
            if observation.status != 'OBSERVED': mark(observation.status)
            if observation.evidence is None:
                if observation.status == 'OBSERVED': mark('FAILED')
                continue
            anchor, tx = observation.evidence.anchor, observation.evidence.transaction
            payload = json.loads(event.canonical_payload)
            if anchor is not None and not (anchor.anchor_id == event.event_uuid and anchor.entity_reference == event.entity_reference
                and anchor.event_type == event.event_type and anchor.content_hash == event.record_hash
                and anchor.previous_hash == event.previous_hash and anchor.transaction_id == event.fabric_transaction_id
                and anchor.source_node == payload['source_node'] and anchor.source_msp == payload['source_msp']):
                mark('CONFLICT'); continue
            if tx is not None:
                if tx.validation_code != 0 or tx.validation_status != 'VALID': mark('FAILED'); continue
                if tx.channel != 'labchain-channel' or tx.creator_msp != payload['source_msp']: mark('FAILED'); continue
                if tx.transaction_id != event.fabric_transaction_id or tx.block_number != event.fabric_block_number:
                    mark('CONFLICT'); continue
            if anchor is None or tx is None:
                if observation.status == 'OBSERVED': mark('FAILED')
                continue
            if fresh:
                blocks.setdefault(event.event_uuid, []).append((peer.peer, tx.block_hash))
                witnesses.append(dict(event_type=event.event_type, artifact_sha256=payload['artifact_sha256'],
                    content_hash=anchor.content_hash, transaction_id=tx.transaction_id, block_number=tx.block_number,
                    validation_status=tx.validation_status, source_msp=anchor.source_msp, source_peer=peer.peer,
                    checked_at=peer.checked_at))
        results.append(dict(peer=peer.peer, status=status, checked_at=peer.checked_at))
    for values in blocks.values():
        if len({block_hash for _, block_hash in values}) > 1:
            affected = {peer for peer, _ in values}
            for result in results:
                if result['peer'] in affected: result['status'] = 'CONFLICT'
    results.sort(key=lambda item: item['peer'])
    if details is not None:
        verified = {p['peer'] for p in results if p['status'] == 'VERIFIED'}
        details.extend(w for w in witnesses if w['source_peer'] in verified)
    states = [p['status'] for p in results]
    status = ('CONFLICT' if 'CONFLICT' in states else 'FAILED' if 'FAILED' in states else
              'FOUR_PEER_VERIFIED' if states.count('VERIFIED') == 4 else
              'PARTIAL' if 'VERIFIED' in states else 'PENDING' if pending else 'UNAVAILABLE')
    times = [p['checked_at'] for p in results if p['checked_at'].tzinfo is not None
             and -5 <= (now - p['checked_at']).total_seconds() <= 30]
    return status, min(times) if times else None, results


def ledger_evidence(db, report, digest, replacement, details=None):
    events = list(db.scalars(select(BlockchainEvent).where(
        BlockchainEvent.entity_type == 'REPORT', BlockchainEvent.entity_id == report.report_id)
        .order_by(BlockchainEvent.event_id).limit(5)))
    releases = [e for e in events if e.event_type == 'REPORT_RELEASED']
    def unavailable(status): return status, None, peer_outcome(status)
    if not events: return unavailable('UNAVAILABLE')
    if len(releases) != 1 or len(events) > 4: return unavailable('FAILED')
    release = releases[0]
    required = 'REPORT_SUPERSEDED' if replacement else 'REPORT_REVOKED' if report.report_status == 'REVOKED' else None
    if required and not any(e.event_type == required for e in events): return unavailable('UNAVAILABLE')
    if not required and any(e.event_type != 'REPORT_RELEASED' for e in events): return unavailable('FAILED')
    confirmed, pending = [], False
    for event in events:
        try:
            validate_event(event)
            payload = json.loads(event.canonical_payload)
            if (event.entity_reference != report.blockchain_entity_uuid or
                payload['artifact_sha256'] != digest or payload['report_version'] != report.version_no or
                (event is release and not release_time_matches(event.occurred_at, report.released_at)) or
                (event is not release and (event.predecessor_event_id != release.event_id or event.previous_hash != release.record_hash)) or
                (event.event_type == 'REPORT_SUPERSEDED' and (replacement is None or payload['superseding_entity_reference'] != replacement.blockchain_entity_uuid))):
                return unavailable('FAILED')
        except (OutboxIntegrityError, ValueError, TypeError, KeyError): return unavailable('FAILED')
        if event.event_status in {'FAILED', 'DEAD'}: return unavailable('FAILED')
        if event.event_status != 'CONFIRMED': pending = True; continue
        if event.fabric_validation_code != 0 or event.fabric_block_number is None or not event.fabric_transaction_id:
            return unavailable('FAILED')
        confirmed.append(event)
    if not confirmed: return unavailable('PENDING')
    try:
        observed = monitor.query({'action': 'report_evidence', 'events': [dict(anchor_id=e.event_uuid,
            transaction_id=e.fabric_transaction_id, block_number=e.fabric_block_number) for e in confirmed]}, schemas.FourPeerEvidence)
    except monitor.MonitorInvalidEvidence: return unavailable('FAILED')
    except monitor.MonitorUnavailable: return unavailable('UNAVAILABLE')
    return aggregate_peer_evidence(observed, confirmed, pending, details)


def public_verification(db, token, ip_address, uploaded_digest=None, ledger_details=None):
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
    result.blockchain_evidence, result.blockchain_checked_at, peers = ledger_evidence(db, report, verification.report_hash, replacement, ledger_details)
    result.blockchain_peers = [PublicPeerEvidence(**p) for p in peers]
    result.blockchain_verified_count = sum(p['status'] == 'VERIFIED' for p in peers)
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
        result.blockchain_peers = [PublicPeerEvidence(**p) for p in peer_outcome('UNAVAILABLE')]
        result.blockchain_verified_count = 0
        result.blockchain_checked_at = None
        result.document_comparison = 'NOT_COMPARED'
        result.message = 'Report state changed during verification. Check again.'
        if ledger_details is not None: ledger_details.clear()
    result.checked_at = datetime.now(timezone.utc)
    return result
