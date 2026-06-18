from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
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
    AvailabilityType,
    SkillLevel,
    UserRole,
    UserStatus,
)

if TYPE_CHECKING:
    from app.models.opportunity import Application


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """
    Core authentication/identity record.

    One-to-one with ``VolunteerProfile`` when the role is VOLUNTEER;
    STAFF and ADMIN accounts do not require a profile.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        {"comment": "Authentication and identity records for all platform users."},
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── Auth flags ────────────────────────────────────────────────────────────
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    email_verification_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    password_reset_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    password_reset_expires_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── RBAC ─────────────────────────────────────────────────────────────────
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="userrole", create_type=True),
        default=UserRole.VOLUNTEER,
        nullable=False,
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="userstatus", create_type=True),
        default=UserStatus.PENDING_VERIFICATION,
        nullable=False,
        index=True,
    )

    # ── Refresh token storage (last issued only) ───────────────────────────────
    refresh_token_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    profile: Mapped[VolunteerProfile | None] = relationship(
        "VolunteerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE and not self.is_deleted

    @property
    def is_admin(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value!r}>"


class VolunteerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Extended profile data for volunteers.

    Separated from ``User`` so staff/admin accounts remain lean, and so
    profile columns can evolve independently of core auth data.
    """

    __tablename__ = "volunteer_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_volunteer_profiles_user_id"),
        {"comment": "Extended volunteer information linked one-to-one with users."},
    )

    # ── FK ────────────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Contact / Bio ─────────────────────────────────────────────────────────
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    date_of_birth: Mapped[str | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_photo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── Location ──────────────────────────────────────────────────────────────
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    state_province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="India", nullable=False)

    # ── Volunteer-specific ────────────────────────────────────────────────────
    skills: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(100)), nullable=True
    )
    languages_spoken: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(50)), nullable=True
    )
    availability: Mapped[AvailabilityType | None] = mapped_column(
        SAEnum(AvailabilityType, name="availabilitytype", create_type=True),
        nullable=True,
    )
    skill_level: Mapped[SkillLevel | None] = mapped_column(
        SAEnum(SkillLevel, name="skilllevel", create_type=True),
        nullable=True,
    )
    hours_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_volunteer_hours: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped[User] = relationship(
        "User",
        back_populates="profile",
        lazy="selectin",
    )
    applications: Mapped[list[Application]] = relationship(
        "Application",
        back_populates="volunteer_profile",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<VolunteerProfile id={self.id} user_id={self.user_id}>"