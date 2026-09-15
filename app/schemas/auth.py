"""Explicit allowlists for authentication responses and linked identities."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Username
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    user_id: int
    username: str
    account_status: Literal["ACTIVE"]
    roles: list[str]


class StaffIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    staff_id: int
    staff_code: str
    first_name: str
    middle_name: str | None
    last_name: str
    position_title: str | None


class PatientIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: int
    patient_code: str
    first_name: str
    middle_name: str | None
    last_name: str


class MeResponse(LoginResponse):
    permissions: list[str]
    staff: StaffIdentity | None = None
    patient: PatientIdentity | None = None


class LogoutResponse(BaseModel):
    status: Literal["ok"] = "ok"
