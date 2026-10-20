"""Public registration and bounded, nonpersistent exact-byte PDF comparison."""
import asyncio
import hashlib
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from app.api.private import PrivateRoute
from app.api.reporting import Db
from app.config import settings
from app.dependencies.auth import get_request_ip
from app.schemas.reporting import PublicVerificationResponse
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
