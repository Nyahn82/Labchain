"""Register every Phase 2A/2B/2C model for Alembic without loading database settings."""

from app.models.base import Base
from app.models.identity import (
    FacilityProfile, Patient, ReferringFacility, RequestingPhysician, Staff,
)
from app.models.auth import (
    PatientAccountLink, Permission, Role, RolePermission,
    StaffAccountLink, UserAccount, UserRole,
)

from app.models.laboratory import (
    LabDepartment, SampleType, TestCatalog, TestSampleType, TestPanel,
    PanelSection, PanelTest, ReferenceRange, TestInterpretationRule,
)

from app.models.workflow import (
    LabOrder, OrderPanel, LabOrderItem, LabPayment, Specimen, SpecimenOrderItem,
    RejectionReason, SpecimenRejection, LabResultItem,
)

__all__ = [
    "Base", "FacilityProfile", "Patient", "Staff", "ReferringFacility",
    "RequestingPhysician", "UserAccount", "StaffAccountLink", "PatientAccountLink",
    "Role", "Permission", "UserRole", "RolePermission",
    "LabDepartment", "SampleType", "TestCatalog", "TestSampleType", "TestPanel",
    "PanelSection", "PanelTest", "ReferenceRange", "TestInterpretationRule",
    "LabOrder", "OrderPanel", "LabOrderItem", "LabPayment", "Specimen",
    "SpecimenOrderItem", "RejectionReason", "SpecimenRejection", "LabResultItem",
]
