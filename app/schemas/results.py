"""Server-owned derived values and provenance, with explicit safe summaries."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from app.schemas.identity import Identifier, Input, text_field
from app.schemas.laboratory import Flag, Output, Partial, ResultType
from app.schemas.workflow import SpecimenStatus, TestSummary

ResultStatus = Literal['DRAFT', 'REVIEWED', 'VERIFIED']


class ResultCreate(Input):
    result_value: text_field(100)
    specimen_id: Identifier | None = None
    remarks: text_field(16000) | None = None


class ResultPatch(Partial):
    nonnull = {'result_value'}
    result_value: text_field(100) | None = None
    specimen_id: Identifier | None = None
    remarks: text_field(16000) | None = None


class ActorSummary(Output):
    user_id: int
    username: str


class ResultTestSummary(TestSummary):
    result_type: ResultType
    default_unit: str | None


class ResultSpecimenSummary(Output):
    specimen_id: int
    specimen_code: str
    specimen_status: SpecimenStatus
    sample_type_id: int


class ResultRangeSummary(Output):
    range_id: int
    test_id: int
    sex: Literal['M', 'F', 'ANY']
    age_min: Decimal | None
    age_max: Decimal | None
    normal_low: Decimal | None
    normal_high: Decimal | None
    critical_low: Decimal | None
    critical_high: Decimal | None
    qualitative_normal: str | None
    unit: str | None
    effective_from: date | None
    effective_to: date | None
    is_active: bool


class ResultResponse(Output):
    result_item_id: int
    order_item_id: int
    order_id: int
    specimen_id: int | None
    reference_range_id: int | None
    result_value: str
    numeric_value: Decimal | None
    flag: Flag | None
    status: ResultStatus
    remarks: str | None
    encoded_by_user_id: int
    encoded_at: datetime
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    verified_by_user_id: int | None
    verified_at: datetime | None
    test: ResultTestSummary
    specimen: ResultSpecimenSummary | None
    reference_range: ResultRangeSummary | None
    encoded_by: ActorSummary
    reviewed_by: ActorSummary | None
    verified_by: ActorSummary | None
