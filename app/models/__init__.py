"""Register every Phase 2A/2B model for Alembic without loading database settings."""

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

__all__ = [
    "Base", "FacilityProfile", "Patient", "Staff", "ReferringFacility",
    "RequestingPhysician", "UserAccount", "StaffAccountLink", "PatientAccountLink",
    "Role", "Permission", "UserRole", "RolePermission",
    "LabDepartment", "SampleType", "TestCatalog", "TestSampleType", "TestPanel",
    "PanelSection", "PanelTest", "ReferenceRange", "TestInterpretationRule",
]
