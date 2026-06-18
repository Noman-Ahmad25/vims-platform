from __future__ import annotations

import re
from datetime import date
from uuid import UUID


from pydantic import Field, HttpUrl, field_validator, ConfigDict

from app.models.enums import AvailabilityType, SkillLevel
from app.schemas.common import AppBaseModel, TimestampSchema, UUIDSchema

_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


def _validate_phone(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = re.sub(r"[\s\-()]", "", v)
    if not _PHONE_RE.match(cleaned):
        raise ValueError("Invalid phone number format.")
    return cleaned


# ── Profile create / update ────────────────────────────────────────────────────


class VolunteerProfileCreate(AppBaseModel):
    """Request body for a volunteer filling in their profile for the first time."""

    phone_number: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    bio: str | None = Field(default=None, max_length=2000)
    profile_photo_url: HttpUrl | None = None

    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state_province: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="India", max_length=100)

    skills: list[str] | None = Field(default=None, max_length=50)
    languages_spoken: list[str] | None = Field(default=None, max_length=20)
    availability: AvailabilityType | None = None
    skill_level: SkillLevel | None = None
    hours_per_week: int | None = Field(default=None, ge=1, le=168)

    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)

    @field_validator("phone_number", "emergency_contact_phone", mode="before")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return _validate_phone(v)

    @field_validator("skills", "languages_spoken", mode="before")
    @classmethod
    def strip_list_items(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return [item.strip() for item in v if item.strip()]

    @field_validator("date_of_birth")
    @classmethod
    def dob_not_in_future(cls, v: date | None) -> date | None:
        if v is not None:
            from datetime import date as dt_date

            if v >= dt_date.today():
                raise ValueError("Date of birth must be in the past.")
        return v


class VolunteerProfileUpdate(AppBaseModel):
    """All fields optional — PATCH semantics."""

    phone_number: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    bio: str | None = Field(default=None, max_length=2000)
    profile_photo_url: HttpUrl | None = None

    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state_province: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=100)

    skills: list[str] | None = None
    languages_spoken: list[str] | None = None
    availability: AvailabilityType | None = None
    skill_level: SkillLevel | None = None
    hours_per_week: int | None = Field(default=None, ge=1, le=168)

    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)

    @field_validator("phone_number", "emergency_contact_phone", mode="before")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return _validate_phone(v)


# ── Profile responses ─────────────────────────────────────────────────────────


class VolunteerProfileResponse(UUIDSchema, TimestampSchema):
    user_id: UUID
    phone_number: str | None
    date_of_birth: date | None
    bio: str | None
    profile_photo_url: str | None

    address_line1: str | None
    address_line2: str | None
    city: str | None
    state_province: str | None
    postal_code: str | None
    country: str

    skills: list[str] | None
    languages_spoken: list[str] | None
    availability: AvailabilityType | None
    skill_level: SkillLevel | None
    hours_per_week: int | None
    total_volunteer_hours: int

    emergency_contact_name: str | None
    emergency_contact_phone: str | None

    model_config = ConfigDict(from_attributes=True)


class VolunteerSummaryResponse(AppBaseModel):
    """Lean representation for admin list / search views."""

    id: str
    user_id: str
    full_name: str
    email: str
    city: str | None
    country: str
    skills: list[str] | None
    total_volunteer_hours: int
    availability: AvailabilityType | None


# ── Admin volunteer management ────────────────────────────────────────────────


class AdminVolunteerHoursUpdate(AppBaseModel):
    """Staff can manually credit volunteer hours."""

    hours_to_add: int = Field(..., ge=1, le=8760)
    note: str | None = Field(default=None, max_length=500)


# Force Pydantic to resolve all dynamic and mixin forward type declarations
VolunteerProfileResponse.model_rebuild()
