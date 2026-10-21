"""Bounded, explicit result schemas; no executable rules or invented normal ranges."""
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.identity import Input, text_field

FacilityStatus = Literal['UNREVIEWED', 'APPROVED', 'UNAVAILABLE', 'REFERRAL_ONLY']


class ResultField(Input):
    key: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    label: text_field(100)
    kind: Literal['number', 'text', 'choice']
    unit: text_field(50) | None = None
    choices: list[text_field(80)] = Field(default_factory=list, max_length=30)
    required: bool = True

    @model_validator(mode='after')
    def choice_configuration(self):
        if self.kind == 'choice' and not self.choices:
            raise ValueError('Choice fields require approved options.')
        if len(set(self.choices)) != len(self.choices):
            raise ValueError('Duplicate result options.')
        return self


class ResultSchema(Input):
    version: Literal[1] = 1
    fields: list[ResultField] = Field(default_factory=list, max_length=40)
    susceptibility: bool = False

    @model_validator(mode='after')
    def unique_fields(self):
        if len({f.key for f in self.fields}) != len(self.fields):
            raise ValueError('Duplicate result field keys.')
        return self


class CollectionGuidance(Input):
    container: text_field(2000) | None = None
    anticoagulant: text_field(2000) | None = None
    handling: text_field(2000) | None = None
    rejection_rules: list[text_field(2000)] = Field(default_factory=list, max_length=30)
    review_status: Literal['FACILITY_SOP_REQUIRED', 'GENERAL_REFERENCE_FACILITY_VALIDATION_REQUIRED', 'FACILITY_CONFIGURED'] = 'FACILITY_SOP_REQUIRED'
    sources: list[text_field(200)] = Field(default_factory=list, max_length=30)
