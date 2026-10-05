"""Safe account management and read-only role/permission discovery."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.private import PrivateRoute
from app.dependencies.auth import get_db, get_request_ip, require_permission
from app.models import Permission, Role, UserAccount, StaffAccountLink, PatientAccountLink
from app.schemas.administration import (
    AccountResponse, AccountStatus, PermissionResponse, RoleReplacement,
    RoleResponse, StaffAccountCreate, StatusUpdate, SuspendRequest,
)
from app.schemas.identity import Identifier, Page
from app.services import administration_service as service
from app.services.identity_service import get_record, list_records

router = APIRouter(tags=['Administration'], route_class=PrivateRoute)


@router.post('/staff/{staff_id}/account', response_model=AccountResponse, status_code=201)
def create_staff_account(staff_id: Identifier, payload: StaffAccountCreate, request: Request,
                         actor: UserAccount = Depends(require_permission('ACCOUNT_CREATE')),
                         db: Session = Depends(get_db)):
    return service.create_staff_account(db, staff_id, payload, actor.user_id, get_request_ip(request))


@router.get('/users', response_model=Page[AccountResponse])
def users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          search: str | None = Query(None, max_length=200), account_status: AccountStatus | None = None,
          staff_id: Identifier | None = None, patient_id: Identifier | None = None,
          actor: UserAccount = Depends(require_permission('ACCOUNT_READ')),
          db: Session = Depends(get_db)):
    filters = {'account_status': account_status}
    if staff_id is not None or patient_id is not None:
        statement = select(UserAccount.user_id)
        if staff_id is not None:
            statement = statement.join(StaffAccountLink).where(StaffAccountLink.staff_id == staff_id)
        if patient_id is not None:
            statement = statement.join(PatientAccountLink).where(PatientAccountLink.patient_id == patient_id)
        filters['user_id'] = db.scalar(statement) or -1
    result = list_records(db, UserAccount, page=page, page_size=page_size, search=search,
                          search_fields=('username',), filters=filters,
                          options=service.ACCOUNT_LOAD_OPTIONS)
    result['items'] = [service.account_response(user) for user in result['items']]
    return result


@router.get('/users/{user_id}', response_model=AccountResponse)
def user_detail(user_id: Identifier, actor: UserAccount = Depends(require_permission('ACCOUNT_READ')),
                db: Session = Depends(get_db)):
    return service.account_response(get_record(db, UserAccount, user_id))


@router.patch('/users/{user_id}/status', response_model=AccountResponse)
def status(user_id: Identifier, payload: StatusUpdate, request: Request,
           actor: UserAccount = Depends(require_permission('ACCOUNT_STATUS_UPDATE')),
           db: Session = Depends(get_db)):
    return service.update_status(db, user_id, payload, actor.user_id, get_request_ip(request))


@router.put('/users/{user_id}/roles', response_model=AccountResponse)
def roles_update(user_id: Identifier, payload: RoleReplacement, request: Request,
                 actor: UserAccount = Depends(require_permission('ROLE_ASSIGN')),
                 db: Session = Depends(get_db)):
    return service.replace_roles(db, user_id, payload, actor.user_id, get_request_ip(request))


@router.get('/roles', response_model=list[RoleResponse])
def roles(actor: UserAccount = Depends(require_permission('ROLE_READ')), db: Session = Depends(get_db)):
    return db.scalars(select(Role).order_by(Role.role_code, Role.role_id)).all()


@router.get('/permissions', response_model=list[PermissionResponse])
def permissions(actor: UserAccount = Depends(require_permission('ROLE_READ')), db: Session = Depends(get_db)):
    return db.scalars(select(Permission).order_by(Permission.permission_code, Permission.permission_id)).all()


@router.post('/users/{user_id}/suspend', response_model=AccountResponse)
def suspend(user_id: Identifier, payload: SuspendRequest, request: Request,
            actor: UserAccount = Depends(require_permission('ACCOUNT_STATUS_UPDATE')),
            db: Session = Depends(get_db)):
    return service.update_status(db, user_id, StatusUpdate(account_status='SUSPENDED', reason=payload.reason),
                                 actor.user_id, get_request_ip(request), expected_status='ACTIVE')


@router.post('/users/{user_id}/reactivate', response_model=AccountResponse)
def reactivate(user_id: Identifier, request: Request,
               actor: UserAccount = Depends(require_permission('ACCOUNT_STATUS_UPDATE')),
               db: Session = Depends(get_db)):
    return service.update_status(db, user_id, StatusUpdate(account_status='ACTIVE'),
                                 actor.user_id, get_request_ip(request), expected_status='SUSPENDED')
