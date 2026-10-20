"""Public registration and bounded, nonpersistent exact-byte PDF comparison."""
import asyncio
import hashlib
import hmac
from typing import Annotated
from sqlalchemy import select
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from app.api.private import PrivateRoute
from app.api.reporting import Db
from app.config import settings
from app.dependencies.auth import get_request_ip
from app.schemas.reporting import PublicVerificationResponse, StaffQrRequest, StaffQrResponse
from app.models import UserAccount
from app.dependencies.auth import require_permission, require_role
from app.services.public_authenticity_service import public_verification
from app.services import verification_limits as limits

router = APIRouter(tags=['Public Report Verification'], route_class=PrivateRoute)


@router.get('/verify/{verification_token}', response_model=PublicVerificationResponse, response_model_exclude_none=True)
def verify_report(verification_token: str, request: Request, db: Db):
    limits.admit(get_request_ip(request) or 'unknown')
    try:
        # Existing immutable QR URLs continue to work for browsers and API clients.
        if 'text/html' in request.headers.get('accept', '') and len(verification_token) <= 128:
            return RedirectResponse('/#/verify/' + quote(verification_token, safe=''), status_code=303,
                headers={'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
        return public_verification(db, verification_token, get_request_ip(request))
    finally:
        limits.slots.release()


@router.post('/verify/{verification_token}/compare', response_model=PublicVerificationResponse, response_model_exclude_none=True)
async def compare_pdf(verification_token: str, request: Request, db: Db):
    limits.admit(get_request_ip(request) or 'unknown')
    try:
        if (request.headers.get('origin') and request.headers['origin'] != settings.public_base_url) or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Cross-site document submission is not allowed.')
        if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/pdf' or request.headers.get('content-encoding', 'identity') != 'identity':
            raise HTTPException(415, 'Submit an unencoded PDF document.')
        declared = request.headers.get('content-length')
        if declared is not None and (not declared.isascii() or not declared.isdigit()):
            raise HTTPException(400, 'Invalid document length.')
        if declared is not None and int(declared) > settings.verification_upload_max_bytes:
            raise HTTPException(413, 'PDF exceeds the verification size limit.')
        digest = hashlib.sha256()
        total = 0
        head = b''
        tail = b''
        try:
            async with asyncio.timeout(30):
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > settings.verification_upload_max_bytes:
                        raise HTTPException(413, 'PDF exceeds the verification size limit.')
                    head = (head + chunk[:16])[:16]
                    tail = (tail + chunk[-1024:])[-1024:]
                    digest.update(chunk)
        except TimeoutError:
            raise HTTPException(408, 'Document upload timed out.') from None
        except ClientDisconnect:
            raise HTTPException(400, 'Document upload was interrupted.') from None
        if declared is not None and total != int(declared):
            raise HTTPException(400, 'Document upload was incomplete.')
        # Envelope checks only. Never parse, render, decompress or execute untrusted PDF content.
        if not re.match(rb'%PDF-[12]\.\d', head) or not tail.rstrip().endswith(b'%%EOF'):
            raise HTTPException(415, 'The submitted bytes do not have a supported PDF envelope.')
        return await run_in_threadpool(public_verification, db, verification_token, get_request_ip(request), digest.hexdigest())
    finally:
        limits.slots.release()


@router.post('/verify/staff/resolve', response_model=StaffQrResponse,
    dependencies=[Depends(require_permission('REPORT_READ')),
                  Depends(require_permission('REPORT_DOWNLOAD'))])
def staff_resolve(payload: StaffQrRequest,
                  request: Request, db: Db,
                  actor: Annotated[UserAccount,
                    Depends(require_role('SYSTEM_ADMIN','LAB_STAFF','LAB_SUPERVISOR','DOCTOR','LAB_SIGNER'))]):
    from app.models import ReportVerification
    from app.services.rbac_service import get_user_roles, user_has_permission
    from app.services.identity_service import audit, mutation
    roles = get_user_roles(db, actor.user_id)
    if 'PATIENT' in roles or ('SYSTEM_ADMIN' not in roles and
        (actor.staff_link is None or not actor.staff_link.staff.is_active)):
        raise HTTPException(403, 'Active personnel access is required.')
    limits.admit(get_request_ip(request) or 'unknown')
    try:
        row = db.scalar(select(ReportVerification).where(ReportVerification.verification_token == payload.token))
        if row is None or not hmac.compare_digest(row.verification_token, payload.token):
            raise HTTPException(404, 'Report not found.')
        report_id = row.report_id
        detailed = user_has_permission(db, actor.user_id, 'BLOCKCHAIN_EXPLORER_VIEW') and user_has_permission(db, actor.user_id, 'BLOCKCHAIN_INTEGRITY_VERIFY')
        actor_id = actor.user_id
        witnesses = []
        evidence = public_verification(db, payload.token, get_request_ip(request), ledger_details=witnesses if detailed else None)
        if evidence.status == 'NOT_FOUND': raise HTTPException(404, 'Report not found.')
        if evidence.status == 'UNAVAILABLE': raise HTTPException(409, 'Report state changed or is inconsistent. Scan again.')
        with mutation(db):
            audit(db, actor_id, 'REPORT_QR_VERIFY', 'lab_report', report_id, get_request_ip(request),
                  new={'version':evidence.version,'status':evidence.status,'stored_artifact':evidence.stored_artifact,
                       'blockchain_evidence':evidence.blockchain_evidence})
        return dict(report_id=report_id, verification=evidence, ledger_details=witnesses,
                    ledger_details_authorized=detailed)
    finally:
        limits.slots.release()
