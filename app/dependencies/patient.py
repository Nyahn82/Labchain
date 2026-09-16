"""The authenticated account link is the only source of patient identity."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies.auth import get_db, require_role
from app.models import Patient, PatientAccountLink, UserAccount


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
