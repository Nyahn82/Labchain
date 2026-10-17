"""Authenticated staff overview with existing per-resource read permissions."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.api.private import PrivateRoute
from app.dependencies.auth import get_current_user, get_db
from app.models import UserAccount
from app.schemas.dashboard import DashboardOverview
from app.services.auth_activity_service import staff_only
from app.services import dashboard_service

router = APIRouter(prefix='/dashboard', tags=['Overview'], route_class=PrivateRoute)


@router.get('/overview', response_model=DashboardOverview, response_model_exclude_none=True)
def overview(db: Annotated[Session, Depends(get_db)],
             user: Annotated[UserAccount, Depends(get_current_user)]):
    try:
        staff_only(db, user.user_id)
        return dashboard_service.overview(db, user.user_id)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, 'Database temporarily unavailable.') from None
