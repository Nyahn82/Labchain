"""Private staff authentication activity and session administration."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from app.api.private import PrivateRoute
from app.dependencies.auth import get_current_session, get_db, get_request_ip, require_permission
from app.models import AuthSession, UserAccount
from app.schemas.auth_activity import ActivityFilters, ActivityResponse, SessionFilters, SessionResponse, RevokeResponse
from app.schemas.identity import Identifier, Page
from app.services import auth_activity_service as service

router = APIRouter(prefix='/admin', tags=['Authentication administration'], route_class=PrivateRoute)
Db = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthSession, Depends(get_current_session)]


def activity_reader(user: UserAccount = Depends(require_permission('AUTH_ACTIVITY_VIEW')), db: Session = Depends(get_db)):
    service.staff_only(db, user.user_id)
    return user


def session_reader(user: UserAccount = Depends(require_permission('AUTH_ACTIVITY_VIEW', 'SESSION_MANAGE')), db: Session = Depends(get_db)):
    service.staff_only(db, user.user_id)
    return user


@router.get('/auth-activity', response_model=Page[ActivityResponse], dependencies=[Depends(activity_reader)])
def activity(filters: Annotated[ActivityFilters, Query()], db: Db):
    return service.activities(db, filters)


@router.get('/sessions', response_model=Page[SessionResponse], dependencies=[Depends(session_reader)])
def sessions(filters: Annotated[SessionFilters, Query()], db: Db, current: Current):
    return service.sessions(db, filters, current.session_id)


@router.get('/users/{user_id}/sessions', response_model=Page[SessionResponse], dependencies=[Depends(session_reader)])
def user_sessions(user_id: Identifier, filters: Annotated[SessionFilters, Query()], db: Db, current: Current):
    return service.sessions(db, filters.model_copy(update={'user_id': user_id}), current.session_id)


@router.post('/sessions/{session_id}/revoke', response_model=RevokeResponse,
             dependencies=[Depends(require_permission('SESSION_MANAGE'))])
def revoke_session(session_id: Identifier, request: Request, db: Db, current: Current):
    return service.revoke(db, current, get_request_ip(request), session_id=session_id)


@router.post('/users/{user_id}/sessions/revoke-all', response_model=RevokeResponse,
             dependencies=[Depends(require_permission('SESSION_MANAGE'))])
def revoke_all(user_id: Identifier, request: Request, db: Db, current: Current):
    return service.revoke(db, current, get_request_ip(request), user_id=user_id)
