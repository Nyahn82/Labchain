"""Private allowlisted authentication projections; never serialize ORM secrets."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from app.schemas.identity import Identifier, Input

AccountType = Literal['STAFF', 'PATIENT', 'SYSTEM/UNKNOWN']
ActivityType = Literal['LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGOUT', 'SESSION_REVOKED',
    'ACCOUNT_SUSPENDED', 'ACCOUNT_REACTIVATED', 'ACCOUNT_LOCKED', 'ACCOUNT_DISABLED',
    'ACCOUNT_STATUS_UPDATED', 'PASSWORD_CHANGED', 'MFA_SUCCESS', 'MFA_FAILED', 'MFA_RESET']
SessionState = Literal['ACTIVE', 'EXPIRED', 'REVOKED']


class ActivityFilters(Input):
    page: int = Field(1, ge=1, le=10000)
    page_size: int = Field(20, ge=1, le=100)
    account_type: Literal['STAFF', 'PATIENT'] | None = None
    user_id: Identifier | None = None
    search: str | None = Field(None, max_length=100)
    ip_address: str | None = Field(None, max_length=45)
    date_from: datetime | None = None
    date_to: datetime | None = None
    activity_type: ActivityType | None = None
    status: Literal['SUCCESS', 'FAILED', 'RECORDED'] | None = None

    @model_validator(mode='after')
    def dates(self):
        for name in ('date_from', 'date_to'):
            value = getattr(self, name)
            if value is not None and value.tzinfo is not None:
                setattr(self, name, value.astimezone(timezone.utc).replace(tzinfo=None))
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('date_from must not exceed date_to.')
        return self


class SessionFilters(Input):
    page: int = Field(1, ge=1, le=10000)
    page_size: int = Field(20, ge=1, le=100)
    account_type: Literal['STAFF', 'PATIENT'] | None = None
    user_id: Identifier | None = None
    search: str | None = Field(None, max_length=100)
    state: SessionState | None = 'ACTIVE'


class AccountLabel(BaseModel):
    user_id: int | None
    username: str | None
    account_type: AccountType
    display_name: str | None


class ActivityResponse(AccountLabel):
    activity_id: str
    activity_type: ActivityType
    occurred_at: datetime
    ip_address: str | None
    user_agent: str | None
    status: Literal['SUCCESS', 'FAILED', 'RECORDED']
    session_id: int | None


class SessionResponse(AccountLabel):
    session_id: int
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    ip_address: str | None
    user_agent: str | None
    is_current: bool
    state: SessionState


class RevokeResponse(BaseModel):
    revoked_count: int
