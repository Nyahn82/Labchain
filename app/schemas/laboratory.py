"""Explicit Phase 3C contracts; identifiers and relationships are never PATCHable."""

from datetime import date
from decimal import Decimal
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.identity import Identifier, Input, text_field

ResultType = Literal['NUMERIC', 'TEXT', 'POS_NEG']
RangeSex = Literal['M', 'F', 'ANY']
PatientSex = Literal['M', 'F', 'Other']
Flag = Literal['NORMAL', 'LOW', 'HIGH', 'CRITICAL_LOW', 'CRITICAL_HIGH', 'ABNORMAL']
SortOrder = Annotated[int, Field(ge=-2147483648, le=2147483647)]
Age = Annotated[Decimal, Field(ge=0, max_digits=6, decimal_places=2, allow_inf_nan=False)]
Threshold = Annotated[Decimal, Field(max_digits=12, decimal_places=3, allow_inf_nan=False)]
Description = text_field(16000)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Partial(Input):
    nonnull: ClassVar[set[str]] = set()

    @model_validator(mode='after')
    def reject_nulls(self):
        if any(getattr(self, field) is None for field in self.model_fields_set & self.nonnull):
            raise ValueError('Required fields cannot be null.')
        return self


class DepartmentFields(Input):
    description: Description | None = None
    is_active: bool = True


class DepartmentCreate(DepartmentFields):
    department_code: text_field(30)
    department_name: text_field(100)


class DepartmentPatch(DepartmentFields, Partial):
    nonnull = {'department_code', 'department_name', 'is_active'}
    department_code: text_field(30) | None = None
    department_name: text_field(100) | None = None


class DepartmentResponse(DepartmentCreate, Output):
    department_id: int


class SampleTypeCreate(DepartmentFields):
    sample_name: text_field(80)


class SampleTypePatch(DepartmentFields, Partial):
    nonnull = {'sample_name', 'is_active'}
    sample_name: text_field(80) | None = None


class SampleTypeResponse(SampleTypeCreate, Output):
    sample_type_id: int


class TestFields(Input):
    default_unit: text_field(50) | None = None
    methodology: text_field(150) | None = None
    default_sort_order: SortOrder | None = None
    is_active: bool = True


class TestCreate(TestFields):
    test_code: text_field(30)
    test_name: text_field(150)
    department_id: Identifier
    result_type: ResultType


class TestPatch(TestFields, Partial):
    nonnull = {'test_code', 'test_name', 'department_id', 'result_type', 'is_active'}
    test_code: text_field(30) | None = None
    test_name: text_field(150) | None = None
    department_id: Identifier | None = None
    result_type: ResultType | None = None


class TestResponse(TestCreate, Output):
    test_id: int


class SampleAssignment(Input):
    sample_type_id: Identifier
    is_default: bool


class SampleReplacement(Input):
    sample_types: list[SampleAssignment] = Field(max_length=1000)


class SampleAssignmentResponse(Output):
    test_sample_type_id: int
    test_id: int
    sample_type_id: int
    is_default: bool
    sample_type: SampleTypeResponse


class TestDetail(TestResponse):
    department: DepartmentResponse
    sample_types: list[SampleAssignmentResponse]


class PanelFields(DepartmentFields):
    department_id: Identifier | None = None


class PanelCreate(PanelFields):
    panel_code: text_field(30)
    panel_name: text_field(120)


class PanelPatch(PanelFields, Partial):
    nonnull = {'panel_code', 'panel_name', 'is_active'}
    panel_code: text_field(30) | None = None
    panel_name: text_field(120) | None = None


class PanelResponse(PanelCreate, Output):
    panel_id: int


class SectionCreate(Input):
    section_name: text_field(120)
    sort_order: SortOrder
    is_active: bool = True


class SectionPatch(Partial):
    nonnull = {'section_name', 'sort_order', 'is_active'}
    section_name: text_field(120) | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = None


class SectionResponse(SectionCreate, Output):
    section_id: int
    panel_id: int


class PanelAssignment(Input):
    test_id: Identifier
    section_id: Identifier | None = None
    sort_order: SortOrder
    is_required: bool


class PanelReplacement(Input):
    tests: list[PanelAssignment] = Field(max_length=1000)


class PanelAssignmentResponse(PanelAssignment, Output):
    panel_test_id: int
    panel_id: int
    test: TestResponse


class PanelDetail(PanelResponse):
    sections: list[SectionResponse]
    tests: list[PanelAssignmentResponse]


class RangeFields(Input):
    age_min: Age | None = None
    age_max: Age | None = None
    normal_low: Threshold | None = None
    normal_high: Threshold | None = None
    critical_low: Threshold | None = None
    critical_high: Threshold | None = None
    qualitative_normal: text_field(80) | None = None
    unit: text_field(50) | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool = True


class RangeCreate(RangeFields):
    sex: RangeSex

    @model_validator(mode='after')
    def ordered_bounds(self):
        for low, high in (
            ('age_min', 'age_max'), ('normal_low', 'normal_high'),
            ('critical_low', 'normal_low'), ('normal_high', 'critical_high'),
            ('critical_low', 'critical_high'), ('effective_from', 'effective_to'),
        ):
            lower, upper = getattr(self, low), getattr(self, high)
            if lower is not None and upper is not None and lower > upper:
                raise ValueError('Lower bound must not exceed upper bound.')
        return self


class RangePatch(RangeFields, Partial):
    nonnull = {'sex', 'is_active'}
    sex: RangeSex | None = None


class RangeResponse(RangeCreate, Output):
    range_id: int
    test_id: int


class ResolverQuery(Input):
    sex: PatientSex
    age_years: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    as_of_date: date


class RuleFields(Input):
    interpretation_text: Description | None = None
    possible_causes: Description | None = None
    recommendation: Description | None = None
    is_active: bool = True


class RuleCreate(RuleFields):
    flag: Flag


class RulePatch(RuleFields, Partial):
    nonnull = {'flag', 'is_active'}
    flag: Flag | None = None


class RuleResponse(RuleCreate, Output):
    rule_id: int
    test_id: int
