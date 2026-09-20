"""MFA challenges, patient self-service, administrative reset and password change."""
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.api.auth import AuthenticationRoute
from app.api.security_cookies import same_origin, session_cookies, clear_sessions, clear_challenge
from app.config import settings
from app.dependencies.auth import get_current_session, get_db, get_request_ip, require_permission
from app.dependencies.patient import get_current_patient
from app.models import AuthSession, UserAccount
from app.schemas import mfa as s
from app.schemas.auth import LoginResponse, LogoutResponse
from app.schemas.identity import Identifier
from app.services import mfa_service as service

router = APIRouter(route_class=AuthenticationRoute)
Db = Annotated[Session, Depends(get_db)]
CurrentSession = Annotated[AuthSession, Depends(get_current_session)]
patient = [Depends(get_current_patient)]


def challenge_response(db, request, response, code, recovery=False):
    same_origin(request)
    result = service.verify_challenge(db, request.cookies.get(settings.mfa_challenge_cookie_name),
        code, get_request_ip(request), request.headers.get('user-agent'), recovery=recovery)
    if isinstance(result, service.ChallengeFailure):
        error = JSONResponse({'detail': 'MFA verification failed.'}, status_code=503 if result.unavailable else 401)
        if result.clear_cookie:
            clear_challenge(error)
        return error
    session_cookies(response, result)
    clear_challenge(response)
    return result.account


@router.post('/auth/mfa/verify', response_model=LoginResponse, tags=['Authentication'])
def verify(payload: s.TotpCode, request: Request, response: Response, db: Db):
    return challenge_response(db, request, response, payload.code.get_secret_value())


@router.post('/auth/mfa/recovery', response_model=LoginResponse, tags=['Authentication'])
def recovery(payload: s.RecoveryCode, request: Request, response: Response, db: Db):
    return challenge_response(db, request, response, payload.recovery_code.get_secret_value(), True)


@router.get('/patient/security', response_model=s.SecurityStatus, dependencies=patient, tags=['Patient Security'])
def status(db: Db, session: CurrentSession):
    return service.security_status(db, session)


@router.post('/patient/mfa/totp/enroll', response_model=s.Enrollment, dependencies=patient, tags=['Patient Security'])
def enroll(request: Request, db: Db, session: CurrentSession):
    return service.enroll(db, session, get_request_ip(request))


@router.post('/patient/mfa/totp/confirm', response_model=s.Confirmed, dependencies=patient, tags=['Patient Security'])
def confirm(payload: s.TotpCode, request: Request, db: Db, session: CurrentSession):
    return service.confirm(db, session, payload.code.get_secret_value(), get_request_ip(request))


@router.post('/patient/mfa/recovery-codes/regenerate', response_model=s.RecoveryCodes, dependencies=patient, tags=['Patient Security'])
def regenerate(payload: s.Regenerate, request: Request, db: Db, session: CurrentSession):
    return service.regenerate(db, session, payload.password.get_secret_value(), payload.totp_code.get_secret_value(), get_request_ip(request))


@router.post('/patient/mfa/disable', response_model=LogoutResponse, dependencies=patient, tags=['Patient Security'])
def disable(payload: s.Disable, request: Request, response: Response, db: Db, session: CurrentSession):
    code = payload.recovery_code if payload.recovery_code is not None else payload.totp_code
    service.disable(db, session, payload.password.get_secret_value(), code.get_secret_value(),
        get_request_ip(request), recovery=payload.recovery_code is not None)
    clear_sessions(response)
    clear_challenge(response)
    return LogoutResponse()


@router.post('/users/{user_id}/mfa/reset', response_model=LogoutResponse, tags=['Administration'])
def reset(user_id: Identifier, request: Request, response: Response, db: Db, session: CurrentSession,
          actor: Annotated[UserAccount, Depends(require_permission('ACCOUNT_MFA_RESET'))]):
    service.admin_reset(db, user_id, session, get_request_ip(request))
    if user_id == actor.user_id:
        clear_sessions(response)
        clear_challenge(response)
    return LogoutResponse()


@router.post('/auth/change-password', response_model=LogoutResponse, tags=['Authentication'])
def change_password(payload: s.PasswordChange, request: Request, response: Response, db: Db, session: CurrentSession):
    service.change_password(db, session, payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(), get_request_ip(request))
    clear_sessions(response)
    clear_challenge(response)
    return LogoutResponse()
