"""Browser authentication HTTP boundary; credentials never appear in error bodies."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.config import settings
from app.api.security_cookies import same_origin, session_cookies, clear_sessions, clear_challenge
from app.services.mfa_service import ChallengeRequired
from app.schemas.mfa import MfaRequired
from app.dependencies.auth import get_current_session, get_current_user, get_db, get_request_ip
from app.models import AuthSession, UserAccount
from app.schemas.auth import LoginRequest, LoginResponse, LogoutResponse, MeResponse
from app.services.auth_service import authenticate, revoke_session
from app.services.rbac_service import get_user_permissions, get_user_roles


class AuthenticationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except RequestValidationError:
                # FastAPI's normal validation detail can include the submitted input.
                response = JSONResponse({"detail": "Invalid authentication request."}, status_code=422)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


router = APIRouter(prefix="/auth", route_class=AuthenticationRoute)


@router.post("/login", response_model=LoginResponse | MfaRequired, responses={202: {"model": MfaRequired}})
def login(
    payload: LoginRequest, request: Request, response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse | MfaRequired:
    # Login has no session CSRF secret yet. Reject cross-origin browser logins.
    same_origin(request)
    result = authenticate(
        db, payload.username, payload.password.get_secret_value(),
        ip_address=get_request_ip(request), user_agent=request.headers.get("user-agent"),
        previous_token=request.cookies.get(settings.auth_session_cookie_name),
    )
    if result is None:
        raise HTTPException(401, "Invalid username or password.")
    if isinstance(result, ChallengeRequired):
        response.status_code = 202
        clear_sessions(response)
        response.set_cookie(settings.mfa_challenge_cookie_name, result.token,
            max_age=settings.mfa_challenge_ttl_minutes*60, httponly=True, secure=True, samesite="strict", path="/")
        return MfaRequired()
    session_cookies(response, result)
    if settings.mfa_challenge_cookie_name in request.cookies:
        clear_challenge(response)
    return result.account


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request, response: Response,
    session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db),
) -> LogoutResponse:
    revoke_session(db, session, get_request_ip(request))
    clear_sessions(response)
    clear_challenge(response)
    return LogoutResponse()


@router.get("/me", response_model=MeResponse)
def me(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db),
       session: AuthSession = Depends(get_current_session)) -> MeResponse:
    from app.dependencies.auth import limited_patient_session
    limited = limited_patient_session(db, session)
    return MeResponse(
        user_id=user.user_id, username=user.username, account_status=user.account_status,
        roles=get_user_roles(db, user.user_id), permissions=[] if limited else get_user_permissions(db, user.user_id),
        staff=user.staff_link.staff if not limited and user.staff_link else None,
        patient=user.patient_link.patient if not limited and user.patient_link else None,
    )
