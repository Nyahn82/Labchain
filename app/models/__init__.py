"""Register domain and authentication infrastructure models without loading settings."""

from app.models.base import Base
from app.models.identity import (
    FacilityProfile, Patient, ReferringFacility, RequestingPhysician, Staff,
)
from app.models.auth import (
    PatientAccountLink, Permission, Role, RolePermission,
    StaffAccountLink, UserAccount, UserRole,
)
from app.models.auth_session import AuthSession

from app.models.laboratory import (
    LabDepartment, SampleType, TestCatalog, TestSampleType, TestPanel,
    PanelSection, PanelTest, ReferenceRange, TestInterpretationRule,
)

from app.models.workflow import (
    LabOrder, OrderPanel, LabOrderItem, LabPayment, Specimen, SpecimenOrderItem,
    RejectionReason, SpecimenRejection, LabResultItem,
)

from app.models.reporting import (
    ReportTemplate, LabReport, ReportResultItem,
    ReportPatientSnapshot, Signatory, ReportSignatory,
    ReportVerification, Attachment,
)
from app.models.logging import (
    EmailLog, PrintLog, AuditLog,
    LoginLog,
)
from app.models.blockchain import (
    BlockchainNode, BlockchainEvent, BlockchainVerificationLog,
    BlockchainSyncLog,
)

__all__ = [
    "Base", "FacilityProfile", "Patient", "Staff", "ReferringFacility",
    "RequestingPhysician", "UserAccount", "StaffAccountLink", "PatientAccountLink",
    "AuthSession", "Role", "Permission", "UserRole", "RolePermission",
    "LabDepartment", "SampleType", "TestCatalog", "TestSampleType", "TestPanel",
    "PanelSection", "PanelTest", "ReferenceRange", "TestInterpretationRule",
    "LabOrder", "OrderPanel", "LabOrderItem", "LabPayment", "Specimen",
    "SpecimenOrderItem", "RejectionReason", "SpecimenRejection", "LabResultItem",
    "ReportTemplate", "LabReport", "ReportResultItem",
    "ReportPatientSnapshot", "Signatory", "ReportSignatory",
    "ReportVerification", "Attachment",
    "EmailLog", "PrintLog", "AuditLog",
    "LoginLog",
    "BlockchainNode", "BlockchainEvent", "BlockchainVerificationLog",
    "BlockchainSyncLog",
]
