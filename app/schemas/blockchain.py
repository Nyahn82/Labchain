"""Separate allowlists for operational, staff and patient anchoring evidence."""
from datetime import datetime
from typing import Literal

from pydantic import Field
from app.schemas.laboratory import Output

AnchoringStatus = Literal['NOT_ANCHORED', 'PENDING', 'PROCESSING', 'RETRYING', 'CONFIRMED', 'FAILED']
SafeAnchoringStatus = Literal['NOT_ANCHORED', 'PENDING', 'RETRYING', 'CONFIRMED', 'FAILED']
EVIDENCE_DESCRIPTION = (
    'Evidence anchoring only, independent of clinical validity, PDF integrity and report release/revocation. '
    'NOT_ANCHORED does not imply invalidity; PENDING/RETRYING do not block report use. '
    'CONFIRMED records committed Fabric evidence; FAILED means automated anchoring requires staff intervention.'
)


class LifecycleAnchoring(Output):
    status: AnchoringStatus = Field(description=EVIDENCE_DESCRIPTION)
    confirmed_at: datetime | None = None
    transaction_id: str | None = None
    block_number: int | None = None


class ReportAnchoring(Output):
    status: AnchoringStatus = Field(description='Aggregate of all relevant lifecycle events. ' + EVIDENCE_DESCRIPTION)
    release: LifecycleAnchoring
    revocation: LifecycleAnchoring | None = None
    supersession: LifecycleAnchoring | None = None


class PatientBlockchainVerification(Output):
    status: SafeAnchoringStatus = Field(description=EVIDENCE_DESCRIPTION)
    confirmed_at: datetime | None = Field(default=None, description='UTC; present only when all relevant lifecycle evidence is confirmed.')


class OutboxCounts(Output):
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    failed: int = Field(ge=0)
    dead: int = Field(ge=0)


class BlockchainStatus(Output):
    delivery_enabled: bool | None = Field(default=None, description=(
        'Unknown (null): MySQL has no worker enablement/heartbeat record. The separate worker environment '
        'is not read by this API; API process settings do not establish worker enablement.'))
    counts: OutboxCounts
    last_confirmed_at: datetime | None
    last_confirmed_transaction_id: str | None
    oldest_pending_at: datetime | None
    worker_health: Literal['IDLE', 'ACTIVE', 'DEGRADED', 'ERROR'] = Field(description=(
        'Outbox-derived state, not worker/peer liveness. Priority: DEAD -> ERROR; FAILED or expired '
        'PROCESSING lease -> DEGRADED; valid PROCESSING lease or due PENDING -> ACTIVE; otherwise IDLE.'))
