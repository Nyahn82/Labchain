"""Permission-protected, aggregate-only operational analytics."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, require_permission
from app.models import UserAccount
from app.schemas.analytics import AnalyticsQuery, AnalyticsResponse
from app.services import analytics_service as service
from app.services.auth_activity_service import staff_only


def analytics_reader(user: UserAccount = Depends(require_permission('ANALYTICS_VIEW')), db: Session = Depends(get_db)):
    staff_only(db, user.user_id)
    return user


router = APIRouter(prefix='/admin/analytics', tags=['Laboratory analytics'], route_class=PrivateRoute,
                   dependencies=[Depends(analytics_reader)])


def section_endpoint(handler):
    def endpoint(query: Annotated[AnalyticsQuery, Query()], db: Session = Depends(get_db)):
        return handler(db, query)
    endpoint.__name__ = 'analytics_' + handler.__name__
    return endpoint


for name in ('overview','patients','orders','tests','specimens','reports','operations','system'):
    router.add_api_route('/'+name, section_endpoint(getattr(service, name)), methods=['GET'], response_model=AnalyticsResponse)
