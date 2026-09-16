"""Patient-facing allowlists intentionally exclude internal report/authentication fields."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator

from app.schemas.auth import Username
from app.schemas.identity import Input, Sex
from app.schemas.laboratory import Output


class ActivationRequest(Input):
    activation_token: SecretStr = Field(min_length=1, max_length=256)
    username: Username
    password: SecretStr = Field(min_length=12, max_length=1024)


class TokenIssued(Output):
    activation_token: str = Field(repr=False)
    expires_at: datetime
    patient_code: str


class ActivationStatus(Output):
    status: Literal['NOT_ACTIVATED', 'TOKEN_ACTIVE', 'TOKEN_EXPIRED', 'ACTIVATED']


class ActivatedAccount(Output):
    user_id: int
    username: str
    account_status: Literal['ACTIVE']
    roles: list[Literal['PATIENT']]


class PatientProfile(Output):
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


class Pagination(Input):
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 20


class ReportFilters(Pagination):
    date_from: date | None = None
    date_to: date | None = None
    search: Annotated[str, Field(max_length=200)] | None = None

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('date_from must not exceed date_to.')
        return self


class ReportSummary(Output):
    report_id: int
    report_code: str
    version_no: int
    released_at: datetime
    order_code: str
    issuing_facility: str
    verification_status: Literal['AUTHENTIC', 'REVOKED'] | None


class Facility(Output):
    facility_name: str
    facility_type: str | None
    address: str | None
    contact_number: str | None
    email: str | None
    website: str | None


class PatientSnapshot(Output):
    patient_code: str
    patient_name: str
    birth_date: date | None
    age_at_report: int | None
    sex: str | None
    physician_name: str | None


class ResultSnapshot(Output):
    section_name_snapshot: str | None
    test_name_snapshot: str
    result_value_snapshot: str
    unit_snapshot: str | None
    reference_range_snapshot: str | None
    flag_snapshot: str | None
    sort_order: int


class Signatory(Output):
    staff_name: str
    signatory_type: str
    license_number_snapshot: str | None
    signed_at: datetime | None
    sort_order: int


class ReportDetail(ReportSummary):
    report_status: Literal['RELEASED']
    generated_at: datetime
    facility: Facility
    patient_snapshot: PatientSnapshot
    result_snapshots: list[ResultSnapshot]
    signatories: list[Signatory]


class AccessEvent(Output):
    action: Literal['PATIENT_REPORT_VIEW', 'PATIENT_REPORT_DOWNLOAD']
    timestamp: datetime
    report_code: str
