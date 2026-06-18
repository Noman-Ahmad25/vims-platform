from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ApplicationOutcome,
    ApplicationStatus,
    OpportunityCategory,
    OpportunityStatus,
)

if TYPE_CHECKING:
    from app.models.user import User, VolunteerProfile


class Opportunity(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """
    A volunteering opportunity created by staff or admins.

    Volunteers browse published opportunities and submit an ``Application``
    to express interest.
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint(
            "start_date <= end_date",
            name="ck_opportunities_start_before_end",
        ),
        CheckConstraint(
            "slots_total > 0",
            name="ck_opportunities_positive_slots",
        ),
        CheckConstraint(
            "slots_filled >= 0 AND slots_filled <= slots_total",
            name="ck_opportunities_slots_filled_range",
        ),
        {"comment": "Volunteering opportunities published by the organisation."},
    )

    # ── Core fields ───────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    short_description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    category: Mapped[OpportunityCategory] = mapped_column(
        SAEnum(OpportunityCategory, name="opportunitycategory", create_type=True),
        nullable=False,
        index=True,
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        SAEnum(OpportunityStatus, name="opportunitystatus", create_type=True),
        default=OpportunityStatus.DRAFT,
        nullable=False,
        index=True,
    )

    # ── Scheduling ────────────────────────────────────────────────────────────
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    application_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Slots ─────────────────────────────────────────────────────────────────
    slots_total: Mapped[int] = mapped_column(Integer, nullable=False)
    slots_filled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Location ──────────────────────────────────────────────────────────────
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    state_province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="India", nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_remote: Mapped[bool] = mapped_column(
        String(5), default=False, nullable=False
    )

    # ── Requirements ─────────────────────────────────────────────────────────
    required_skills: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(100)), nullable=True
    )
    minimum_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Ownership ─────────────────────────────────────────────────────────────
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    created_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    applications: Mapped[list[Application]] = relationship(
        "Application",
        back_populates="opportunity",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def slots_available(self) -> int:
        return self.slots_total - self.slots_filled

    @property
    def is_full(self) -> bool:
        return self.slots_filled >= self.slots_total

    def __repr__(self) -> str:
        return (
            f"<Opportunity id={self.id} title={self.title!r}"
            f" status={self.status.value!r}>"
        )


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A volunteer's application to participate in an ``Opportunity``.

    The composite unique constraint prevents a single volunteer from
    submitting duplicate applications to the same opportunity.
    """

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint(
            "volunteer_profile_id",
            "opportunity_id",
            name="uq_applications_profile_opportunity",
        ),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_applications_rating_range",
        ),
        {"comment": "Volunteer applications to specific opportunities."},
    )

    # ── FK references ─────────────────────────────────────────────────────────
    volunteer_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("volunteer_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, name="applicationstatus", create_type=True),
        default=ApplicationStatus.SUBMITTED,
        nullable=False,
        index=True,
    )
    outcome: Mapped[ApplicationOutcome | None] = mapped_column(
        SAEnum(ApplicationOutcome, name="applicationoutcome", create_type=True),
        nullable=True,
    )

    # ── Volunteer-supplied content ─────────────────────────────────────────────
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Staff review fields ────────────────────────────────────────────────────
    staff_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Post-completion ────────────────────────────────────────────────────────
    hours_logged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    volunteer_profile: Mapped[VolunteerProfile] = relationship(
        "VolunteerProfile",
        back_populates="applications",
        lazy="selectin",
    )
    opportunity: Mapped[Opportunity] = relationship(
        "Opportunity",
        back_populates="applications",
        lazy="selectin",
    )
    reviewed_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[reviewed_by_id],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Application id={self.id}"
            f" profile={self.volunteer_profile_id}"
            f" opportunity={self.opportunity_id}"
            f" status={self.status.value!r}>"
        )