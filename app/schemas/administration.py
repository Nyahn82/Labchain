"""Safe account and RBAC metadata, with secret request credentials."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.auth import PatientIdentity, StaffIdentity, Username
from app.schemas.identity import Input, text_field

AccountStatus = Literal['ACTIVE', 'INACTIVE', 'LOCKED']


class RoleReplacement(Input):
    role_codes: list[text_field(40)] = Field(max_length=100)

    @field_validator('role_codes')
    @classmethod
    def unique_codes(cls, codes):
        return sorted(set(codes))


class StaffAccountCreate(RoleReplacement):
    username: Username
    password: SecretStr = Field(min_length=12, max_length=1024)


class StatusUpdate(Input):
    account_status: AccountStatus


class AccountResponse(BaseModel):
    user_id: int
    username: str
    account_status: AccountStatus
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str]
    staff: StaffIdentity | None = None
    patient: PatientIdentity | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role_id: int
    role_code: str
    role_name: str
    description: str | None
    is_active: bool


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    permission_id: int
    permission_code: str
    permission_name: str
    description: str | None
