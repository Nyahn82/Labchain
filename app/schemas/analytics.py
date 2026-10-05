"""Aggregate-only analytics contracts. No clinical or authentication record DTOs."""
from datetime import date, datetime, time, timedelta
from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from app.schemas.identity import Input

Grain = Literal['auto', 'day', 'week', 'month', 'quarter', 'year']


def bucket_start(day, grain):
    if grain == 'week':
        return day - timedelta(days=day.weekday())
    if grain == 'month':
        return day.replace(day=1)
    if grain == 'quarter':
        return day.replace(month=((day.month-1)//3)*3+1, day=1)
    if grain == 'year':
        return day.replace(month=1, day=1)
    return day


def next_bucket(day, grain):
    if grain in ('day', 'week'):
        return day + timedelta(days=1 if grain == 'day' else 7)
    months = {'month': 1, 'quarter': 3, 'year': 12}[grain]
    month = day.year*12 + day.month-1 + months
    return date(month//12, month % 12+1, 1)


class AnalyticsQuery(Input):
    date_from: date
    date_to: date
    grain: Grain = 'auto'
    top_n: int = Field(10, ge=1, le=20)

    @field_validator('date_from', 'date_to', mode='before')
    @classmethod
    def calendar_dates_only(cls, value):
        if isinstance(value, datetime) or (isinstance(value, str) and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
            raise ValueError('Use UTC calendar dates in YYYY-MM-DD format.')
        return value

    @property
    def resolved_grain(self):
        days = (self.date_to-self.date_from).days+1
        return self.grain if self.grain != 'auto' else ('day' if days <= 31 else 'week' if days <= 180 else 'month' if days <= 730 else 'quarter' if days <= 1460 else 'year')

    @property
    def bounds(self):
        return datetime.combine(self.date_from, time()), datetime.combine(self.date_to+timedelta(days=1), time())

    @property
    def buckets(self):
        result = []
        start = bucket_start(self.date_from, self.resolved_grain)
        while start <= self.date_to and len(result) <= 120:
            result.append(start)
            start = next_bucket(start, self.resolved_grain)
        return result

    @model_validator(mode='after')
    def bounded_range(self):
        if not date(1970, 1, 1) <= self.date_from <= self.date_to <= date(2100, 12, 31):
            raise ValueError('Use an ordered date range between 1970 and 2100.')
        if (self.date_to-self.date_from).days >= 3660:
            raise ValueError('At most 3660 calendar days are allowed.')
        if len(self.buckets) > 120:
            raise ValueError('Choose a coarser grain; at most 120 buckets are allowed.')
        return self


class SafeModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class RangeInfo(SafeModel):
    date_from: date
    date_to: date
    previous_date_from: date
    previous_date_to: date
    timezone: Literal['UTC'] = 'UTC'
    grain: str
    week_starts_on: Literal['Monday'] = 'Monday'
    end_inclusive: bool = True


class Metric(SafeModel):
    key: str
    label: str
    definition: str
    value: float | None
    unit: Literal['count', 'percent', 'seconds', 'amount'] = 'count'
    previous_value: float | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    compared: bool = False


class Point(SafeModel):
    bucket: date
    value: int


class Series(SafeModel):
    key: str
    label: str
    definition: str
    points: list[Point] = Field(max_length=120)


class Group(SafeModel):
    key: str
    label: str
    count: int
    share: float | None = None
    code: str | None = None
    department: str | None = None
    drafted: int | None = None
    reviewed: int | None = None
    verified: int | None = None


class Breakdown(SafeModel):
    key: str
    label: str
    definition: str
    items: list[Group] = Field(max_length=24)
    total: int
    other_count: int = 0


class Turnaround(SafeModel):
    key: str
    label: str
    definition: str
    average_seconds: float | None
    sample_count: int
    excluded_count: int
    candidate_count: int


class AnalyticsResponse(SafeModel):
    range: RangeInfo
    metrics: list[Metric] = []
    series: list[Series] = []
    breakdowns: list[Breakdown] = []
    turnaround: list[Turnaround] = []
    notes: list[str] = []
