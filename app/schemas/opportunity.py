from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import Field, field_validator, model_validator

from app.models.enums import (
    ApplicationOutcome,
    ApplicationStatus,
    OpportunityCategory,
    OpportunityStatus,
)
from app.schemas.common import AppBaseModel, TimestampSchema, UUIDSchema


# ── Opportunity create / update ────────────────────────────────────────────────


class OpportunityCreate(AppBaseModel):
    title: str = Field(..., min_length=5, max_length=255)
    description: str = Field(..., min_length=20)
    short_description: str | None = Field(default=None, max_length=500)
    category: OpportunityCategory

    start_date: datetime
    end_date: datetime
    application_deadline: datetime | None = None

    slots_total: int = Field(..., ge=1)

    location_name: str | None = Field(default=None, max_length=255)
    location_address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state_province: str | None = Field(default=None, max_length=100)
    country: str = Field(default="India", max_length=100)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    is_remote: bool = False

    required_skills: list[str] | None = None
    minimum_age: int | None = Field(default=None, ge=0, le=120)
    estimated_hours: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def date_order(self) -> "OpportunityCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")
        if self.application_deadline is not None:
            if self.application_deadline >= self.start_date:
                raise ValueError(
                    "application_deadline must be before start_date."
                )
        return self

    @field_validator("start_date", "end_date", "application_deadline", mode="before")
    @classmethod
    def ensure_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class OpportunityUpdate(AppBaseModel):
    """PATCH — every field is optional."""

    title: str | None = Field(default=None, min_length=5, max_length=255)
    description: str | None = Field(default=None, min_length=20)
    short_description: str | None = Field(default=None, max_length=500)
    category: OpportunityCategory | None = None
    status: OpportunityStatus | None = None

    start_date: datetime | None = None
    end_date: datetime | None = None
    application_deadline: datetime | None = None

    slots_total: int | None = Field(default=None, ge=1)

    location_name: str | None = Field(default=None, max_length=255)
    location_address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state_province: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    is_remote: bool | None = None

    required_skills: list[str] | None = None
    minimum_age: int | None = Field(default=None, ge=0, le=120)
    estimated_hours: int | None = Field(default=None, ge=1)


# ── Opportunity responses ─────────────────────────────────────────────────────


class OpportunityResponse(UUIDSchema, TimestampSchema):
    title: str
    description: str
    short_description: str | None
    category: OpportunityCategory
    status: OpportunityStatus

    start_date: datetime
    end_date: datetime
    application_deadline: datetime | None

    slots_total: int
    slots_filled: int
    slots_available: int

    location_name: str | None
    location_address: str | None
    city: str | None
    state_province: str | None
    country: str
    latitude: float | None
    longitude: float | None
    is_remote: bool

    required_skills: list[str] | None
    minimum_age: int | None
    estimated_hours: int | None

    created_by_id: uuid.UUID


class OpportunitySummaryResponse(AppBaseModel):
    id: uuid.UUID
    title: str
    category: OpportunityCategory
    status: OpportunityStatus
    city: str | None
    country: str
    start_date: datetime
    slots_available: int
    is_remote: bool


# ── Application create / review ────────────────────────────────────────────────


class ApplicationCreate(AppBaseModel):
    opportunity_id: uuid.UUID
    cover_letter: str | None = Field(default=None, max_length=3000)
    motivation: str | None = Field(default=None, max_length=2000)


class ApplicationReviewRequest(AppBaseModel):
    """Staff action: update application status after review."""

    status: ApplicationStatus = Field(
        ...,
        description="New status. Allowed transitions enforced at service level.",
    )
    staff_notes: str | None = Field(default=None, max_length=2000)
    rejection_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def rejection_reason_required(self) -> "ApplicationReviewRequest":
        if (
            self.status == ApplicationStatus.REJECTED
            and not self.rejection_reason
        ):
            raise ValueError(
                "rejection_reason is required when status is REJECTED."
            )
        return self


class ApplicationCompleteRequest(AppBaseModel):
    """Staff action: record post-completion data."""

    outcome: ApplicationOutcome
    hours_logged: int = Field(..., ge=0, le=8760)
    rating: int | None = Field(default=None, ge=1, le=5)
    feedback: str | None = Field(default=None, max_length=2000)


class ApplicationWithdrawRequest(AppBaseModel):
    reason: str | None = Field(default=None, max_length=500)


# ── Application responses ─────────────────────────────────────────────────────


class ApplicationResponse(UUIDSchema, TimestampSchema):
    volunteer_profile_id: uuid.UUID
    opportunity_id: uuid.UUID
    reviewed_by_id: uuid.UUID | None

    status: ApplicationStatus
    outcome: ApplicationOutcome | None

    cover_letter: str | None
    motivation: str | None
    staff_notes: str | None
    rejection_reason: str | None
    reviewed_at: datetime | None

    hours_logged: int | None
    rating: int | None
    feedback: str | None
    completed_at: datetime | None

    opportunity: OpportunitySummaryResponse | None = None


class ApplicationSummaryResponse(AppBaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    opportunity_title: str
    status: ApplicationStatus
    created_at: datetime