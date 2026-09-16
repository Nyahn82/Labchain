"""Phase 5A allowlisted inputs and historical report outputs."""
from datetime import date, datetime
from typing import Literal

from app.schemas.identity import Address, Contact, Email, Identifier, Input, text_field
from app.schemas.laboratory import Output, Partial, SortOrder

ReportStatus = Literal['GENERATED', 'APPROVED', 'RELEASED', 'REVOKED']
SignatoryType = Literal['LAB_IN_CHARGE', 'MEDICAL_TECHNOLOGIST', 'PATHOLOGIST']


class FacilityFields(Input):
    facility_type: text_field(80) | None = None
    address: Address | None = None
    contact_number: Contact | None = None
    email: Email | None = None
    website: text_field(150) | None = None
    logo_path: text_field(255) | None = None


class FacilityCreate(FacilityFields):
    facility_name: text_field(150)


class FacilityPatch(FacilityFields, Partial):
    nonnull = {'facility_name'}
    facility_name: text_field(150) | None = None


class FacilityResponse(FacilityCreate, Output):
    facility_id: int
    created_at: datetime
    updated_at: datetime | None


class TemplateFields(Input):
    panel_id: Identifier | None = None
    header_title: text_field(150) | None = None
    section_title: text_field(150) | None = None
    clinical_note: text_field(16000) | None = None
    footer_note: text_field(16000) | None = None
    medico_legal_note: text_field(16000) | None = None
    is_active: bool = True


class TemplateCreate(TemplateFields):
    template_code: text_field(40)
    template_name: text_field(100)


class TemplatePatch(TemplateFields, Partial):
    nonnull = {'template_code', 'template_name', 'is_active'}
    template_code: text_field(40) | None = None
    template_name: text_field(100) | None = None


class TemplateResponse(TemplateCreate, Output):
    template_id: int


class SignatoryFields(Input):
    signature_image_path: text_field(255) | None = None
    license_number_snapshot: text_field(50) | None = None
    is_active: bool = True


class SignatoryCreate(SignatoryFields):
    staff_id: Identifier


class SignatoryPatch(SignatoryFields, Partial):
    nonnull = {'staff_id', 'is_active'}
    staff_id: Identifier | None = None


class SignatoryResponse(SignatoryCreate, Output):
    signatory_id: int


class GenerateRequest(Input):
    template_id: Identifier | None = None
    remarks: text_field(16000) | None = None


class AssignRequest(Input):
    signatory_id: Identifier
    signatory_type: SignatoryType
    sort_order: SortOrder = 1


class SignRequest(Input):
    report_signatory_id: Identifier


class ReportSignatoryResponse(Output):
    report_signatory_id: int
    report_id: int
    signatory_id: int
    signatory_type: SignatoryType
    signed_at: datetime | None
    sort_order: int
    profile: SignatoryResponse
    staff_name: str


class PatientSnapshot(Output):
    report_id: int
    patient_code: str
    patient_name: str
    birth_date: date | None
    age_at_report: int | None
    sex: str | None
    physician_name: str | None


class ResultSnapshot(Output):
    report_result_item_id: int
    report_id: int
    result_item_id: int
    panel_id_snapshot: int | None
    section_name_snapshot: str | None
    test_name_snapshot: str
    result_value_snapshot: str
    unit_snapshot: str | None
    reference_range_snapshot: str | None
    flag_snapshot: str | None
    sort_order: int


class ReportResponse(Output):
    report_id: int
    report_code: str
    order_id: int
    facility_id: int
    template_id: int | None
    version_no: int
    supersedes_report_id: int | None
    report_status: ReportStatus
    generated_by_user_id: int
    generated_at: datetime
    approved_by_user_id: int | None
    approved_at: datetime | None
    released_by_user_id: int | None
    released_at: datetime | None
    revoked_by_user_id: int | None
    revoked_at: datetime | None
    revocation_reason: str | None
    pdf_path: str | None
    remarks: str | None


class ReportDetail(ReportResponse):
    facility: FacilityResponse
    template: TemplateResponse | None
    patient_snapshot: PatientSnapshot | None
    result_snapshots: list[ResultSnapshot]
    signatories: list[ReportSignatoryResponse]
