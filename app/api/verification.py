"""Public, redacted QR verification. Deliberately has no authentication dependency."""
from fastapi import APIRouter, Request
from app.api.private import PrivateRoute
from app.api.reporting import Db
from app.dependencies.auth import get_request_ip
from app.schemas.reporting import PublicVerificationResponse
from app.services.report_release_service import public_verification

router = APIRouter(tags=['Public Report Verification'], route_class=PrivateRoute)


@router.get('/verify/{verification_token}', response_model=PublicVerificationResponse, response_model_exclude_none=True)
def verify_report(verification_token: str, request: Request, db: Db):
    return public_verification(db, verification_token, get_request_ip(request))
