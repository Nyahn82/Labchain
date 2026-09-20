"""The authenticated account link is the only source of patient identity."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies.auth import get_db, require_role, get_current_session
from app.models import AuthSession, Patient, PatientAccountLink, UserAccount


@dataclass(frozen=True)
class PatientContext:
    user_id: int
    patient: Patient


def get_current_patient(
    user: Annotated[UserAccount, Depends(require_role('PATIENT'))],
    db: Annotated[Session, Depends(get_db)],
) -> PatientContext:
    patient = db.scalar(select(Patient).join(PatientAccountLink, PatientAccountLink.patient_id == Patient.patient_id)
        .where(PatientAccountLink.user_id == user.user_id).with_for_update(read=True)
        .execution_options(populate_existing=True))
    if patient is None:
        raise HTTPException(403, 'Patient account is not configured for portal access.')
    return PatientContext(user_id=user.user_id, patient=patient)


def require_patient_mfa(
    context: Annotated[PatientContext, Depends(get_current_patient)],
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> PatientContext:
    from app.config import settings
    from app.services.mfa_service import configuration, enabled
    if settings.patient_mfa_required:
        if not enabled(configuration(db, context.user_id)):
            raise HTTPException(403, 'MFA_ENROLLMENT_REQUIRED')
        if session.mfa_verified_at is None:
            raise HTTPException(403, 'MFA_REQUIRED')
    return context
