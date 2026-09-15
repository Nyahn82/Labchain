"""Explicit identity input/output contracts; no credentials or stored patient age."""

from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator,
)


def text_field(length: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=length)]


Code = text_field(20)
Name = text_field(60)
Suffix = text_field(20)
Contact = text_field(30)
# MySQL TEXT is limited in bytes; this bound also fits utf8mb4's worst case.
Address = text_field(16000)
Email = Annotated[EmailStr, Field(max_length=254)]
Sex = Literal['M', 'F', 'Other']
Identifier = Annotated[int, Field(gt=0, le=9223372036854775807)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)


class PatientFields(Input):
    middle_name: Name | None = None
    suffix: Suffix | None = None
    birth_date: date | None = None
    sex: Sex | None = None
    civil_status: Suffix | None = None
    nationality: Name | None = None
    contact_number: Contact | None = None
    email: Email | None = None
    address: Address | None = None


class PatientCreate(PatientFields):
    patient_code: Code
    first_name: Name
    last_name: Name


class PartialInput(Input):
    @model_validator(mode='after')
    def reject_required_nulls(self):
        for field in self.model_fields_set & {'patient_code', 'staff_code', 'first_name', 'last_name', 'facility_name', 'is_active'}:
            if getattr(self, field) is None:
                raise ValueError(f'{field} cannot be null.')
        return self


class PatientPatch(PatientFields, PartialInput):
    patient_code: Code | None = None
    first_name: Name | None = None
    last_name: Name | None = None


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    patient_id: int
    patient_code: str
    first_name: str
    middle_name: str | None
    last_name: str
    suffix: str | None
    birth_date: date | None
    sex: Sex | None
    civil_status: str | None
    nationality: str | None
    contact_number: str | None
    email: str | None
    address: str | None
    created_at: datetime
    updated_at: datetime | None


class StaffFields(Input):
    middle_name: Name | None = None
    suffix: Suffix | None = None
    position_title: text_field(100) | None = None
    license_number: text_field(50) | None = None
    contact_number: Contact | None = None
    email: Email | None = None


class StaffCreate(StaffFields):
    staff_code: Code
    first_name: Name
    last_name: Name
    is_active: bool = True


class StaffPatch(StaffFields, PartialInput):
    staff_code: Code | None = None
    first_name: Name | None = None
    last_name: Name | None = None
    is_active: bool | None = None


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    staff_id: int
    staff_code: str
    first_name: str
    middle_name: str | None
    last_name: str
    suffix: str | None
    position_title: str | None
    license_number: str | None
    contact_number: str | None
    email: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None


class FacilityFields(Input):
    facility_type: text_field(80) | None = None
    address: Address | None = None
    contact_number: Contact | None = None


class FacilityCreate(FacilityFields):
    facility_name: text_field(150)


class FacilityPatch(FacilityFields, PartialInput):
    facility_name: text_field(150) | None = None


class FacilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    referring_facility_id: int
    facility_name: str
    facility_type: str | None
    address: str | None
    contact_number: str | None


class PhysicianFields(Input):
    middle_name: Name | None = None
    suffix: Suffix | None = None
    license_number: text_field(50) | None = None
    specialization: text_field(100) | None = None
    referring_facility_id: Identifier | None = None
    contact_number: Contact | None = None


class PhysicianCreate(PhysicianFields):
    first_name: Name
    last_name: Name
    is_active: bool = True


class PhysicianPatch(PhysicianFields, PartialInput):
    first_name: Name | None = None
    last_name: Name | None = None
    is_active: bool | None = None


class PhysicianResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    physician_id: int
    first_name: str
    middle_name: str | None
    last_name: str
    suffix: str | None
    license_number: str | None
    specialization: str | None
    referring_facility_id: int | None
    contact_number: str | None
    is_active: bool


T = TypeVar('T')


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
