"""Aggregate-only overview contract; unauthorized sections are omitted."""
from datetime import datetime
from pydantic import BaseModel, NonNegativeInt


class WorkflowCounts(BaseModel):
    total: NonNegativeInt
    statuses: dict[str, NonNegativeInt]


class DashboardOverview(BaseModel):
    generated_at: datetime
    patients: NonNegativeInt | None = None
    orders: WorkflowCounts | None = None
    specimens: WorkflowCounts | None = None
    results: WorkflowCounts | None = None
    reports: WorkflowCounts | None = None
