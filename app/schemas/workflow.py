"""Phase 4A contracts. Server provenance and lifecycle fields are output-only."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.identity import Identifier, Input, text_field
from app.schemas.laboratory import Output, Partial

Priority = Literal['ROUTINE', 'STAT', 'URGENT']
OrderStatus = Literal['REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
PaymentStatus = Literal['PENDING', 'PAID', 'FREE', 'WAIVED', 'SUBSIDIZED']
SpecimenStatus = Literal['PENDING', 'COLLECTED', 'RECEIVED', 'REJECTED', 'PROCESSED']
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]


class OrderCreate(Input):
    patient_id: Identifier
    physician_id: Identifier | None = None
    priority: Priority
    request_reason: text_field(150) | None = None
    clinical_notes: text_field(16000) | None = None
    diagnosis: text_field(16000) | None = None
    panel_ids: list[Identifier] = Field(default_factory=list, max_length=1000)
    test_ids: list[Identifier] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def requests_valid(self):
        if not self.panel_ids and not self.test_ids:
            raise ValueError('At least one panel or test is required.')
        if len(set(self.panel_ids)) != len(self.panel_ids) or len(set(self.test_ids)) != len(self.test_ids):
            raise ValueError('Duplicate request IDs.')
        return self


class CancelRequest(Input):
    reason: text_field(500)


class PaymentCreate(Input):
    payment_status: PaymentStatus
    amount: Amount | None = None
    payment_method: text_field(50) | None = None
    reference_number: text_field(80) | None = None


class SpecimenCreate(Input):
    sample_type_id: Identifier
    order_item_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    remarks: text_field(16000) | None = None

    @model_validator(mode='after')
    def unique_items(self):
        if len(set(self.order_item_ids)) != len(self.order_item_ids):
            raise ValueError('Duplicate order item IDs.')
        return self


class RejectRequest(Input):
    rejection_reason_id: Identifier
    details: text_field(16000) | None = None
    recollection_required: bool


class ReasonCreate(Input):
    reason_code: text_field(40)
    reason_name: text_field(120)
    description: text_field(16000) | None = None
    is_active: bool = True


class ReasonPatch(Partial):
    nonnull = {'reason_code', 'reason_name', 'is_active'}
    reason_code: text_field(40) | None = None
    reason_name: text_field(120) | None = None
    description: text_field(16000) | None = None
    is_active: bool | None = None


class ReasonResponse(Output):
    rejection_reason_id: int
    reason_code: str
    reason_name: str
    description: str | None
    is_active: bool


class PatientSummary(Output):
    patient_id: int
    patient_code: str
    first_name: str
    middle_name: str | None
    last_name: str
    suffix: str | None


class PhysicianSummary(Output):
    physician_id: int
    first_name: str
    middle_name: str | None
    last_name: str
    suffix: str | None


class TestSummary(Output):
    test_id: int
    test_code: str
    test_name: str


class PanelSummary(Output):
    panel_id: int
    panel_code: str
    panel_name: str


class SampleSummary(Output):
    sample_type_id: int
    sample_name: str


class OrderResponse(Output):
    order_id: int
    order_code: str
    patient_id: int
    physician_id: int | None
    ordered_by_user_id: int | None
    order_date: datetime
    priority: Priority
    request_reason: str | None
    clinical_notes: str | None
    diagnosis: str | None
    status: OrderStatus
    created_at: datetime
    updated_at: datetime | None


class OrderListItem(Output):
    order_id: int
    order_code: str
    order_date: datetime
    priority: Priority
    status: OrderStatus
    patient: PatientSummary
    physician: PhysicianSummary | None


class OrderPanelResponse(Output):
    order_panel_id: int
    order_id: int
    panel_id: int
    status: OrderStatus
    panel: PanelSummary


class OrderItemResponse(Output):
    order_item_id: int
    order_id: int
    test_id: int
    order_panel_id: int | None
    status: OrderStatus
    created_at: datetime
    test: TestSummary


class PaymentResponse(Output):
    payment_id: int
    order_id: int
    payment_status: PaymentStatus
    amount: Decimal | None
    payment_method: str | None
    reference_number: str | None
    recorded_by_user_id: int | None
    recorded_at: datetime


class MappingResponse(Output):
    specimen_order_item_id: int
    specimen_id: int
    order_item_id: int
    order_item: OrderItemResponse


class RejectionResponse(Output):
    specimen_rejection_id: int
    specimen_id: int
    rejection_reason_id: int
    details: str | None
    rejected_by_user_id: int
    rejected_at: datetime
    recollection_required: bool
    reason: ReasonResponse


class SpecimenResponse(Output):
    specimen_id: int
    specimen_code: str
    order_id: int
    sample_type_id: int
    collected_by_user_id: int | None
    collected_at: datetime | None
    received_by_user_id: int | None
    received_at: datetime | None
    specimen_status: SpecimenStatus
    remarks: str | None
    created_at: datetime
    sample_type: SampleSummary
    mappings: list[MappingResponse]
    rejections: list[RejectionResponse]


class OrderDetail(OrderResponse):
    patient: PatientSummary
    physician: PhysicianSummary | None
    panels: list[OrderPanelResponse]
    items: list[OrderItemResponse]
    payments: list[PaymentResponse]
    specimens: list[SpecimenResponse]
