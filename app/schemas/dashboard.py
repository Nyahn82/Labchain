"""Aggregate-only overview contract; unauthorized sections are omitted."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, NonNegativeInt


class WorkflowCounts(BaseModel):
    total: NonNegativeInt
    statuses: dict[str, NonNegativeInt]


class Presence(BaseModel):
    recently_active: NonNegativeInt
    window_seconds: int = 300


class ActivationCounts(BaseModel):
    not_activated: NonNegativeInt
    review_required: NonNegativeInt


class AccountCounts(BaseModel):
    active: NonNegativeInt
    suspended: NonNegativeInt


class FailedLogins(BaseModel):
    count: NonNegativeInt
    since: datetime
    until: datetime


class SigningCounts(BaseModel):
    unassigned: NonNegativeInt
    awaiting_signature: NonNegativeInt
    awaiting_approval: NonNegativeInt


class ServiceHealth(BaseModel):
    name: str
    status: Literal['HEALTHY', 'UNHEALTHY', 'STALE', 'UNKNOWN', 'STOPPED']
    checked_at: datetime | None = None


class DashboardOverview(BaseModel):
    generated_at: datetime
    patients: NonNegativeInt | None = None
    orders: WorkflowCounts | None = None
    specimens: WorkflowCounts | None = None
    results: WorkflowCounts | None = None
    reports: WorkflowCounts | None = None
    presence: Presence | None = None
    activation: ActivationCounts | None = None
    accounts: AccountCounts | None = None
    failed_logins: FailedLogins | None = None
    signing: SigningCounts | None = None
    services: list[ServiceHealth] | None = None
