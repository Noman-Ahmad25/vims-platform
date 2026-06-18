from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import AvailabilityType, SkillLevel
from app.models.user import User, VolunteerProfile
from app.schemas.volunteer import VolunteerProfileCreate, VolunteerProfileUpdate
from app.utils.exceptions import (
    DuplicateResourceError,
    PermissionDeniedError,
    ProfileNotFoundError,
)


class VolunteerService:
    """
    CRUD and business logic for VolunteerProfile records.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _get_profile_by_user_id(self, user_id: uuid.UUID) -> VolunteerProfile | None:
        result = await self._db.execute(
            select(VolunteerProfile)
            .where(VolunteerProfile.user_id == user_id)
            .options(selectinload(VolunteerProfile.user))
        )
        return result.scalar_one_or_none()

    async def _get_profile_by_id(self, profile_id: uuid.UUID) -> VolunteerProfile | None:
        result = await self._db.execute(
            select(VolunteerProfile)
            .where(VolunteerProfile.id == profile_id)
            .options(selectinload(VolunteerProfile.user))
        )
        return result.scalar_one_or_none()

    # ── Profile CRUD ───────────────────────────────────────────────────────────

    async def create_profile(
        self, user: User, payload: VolunteerProfileCreate
    ) -> VolunteerProfile:
        existing = await self._get_profile_by_user_id(user.id)
        if existing is not None:
            raise DuplicateResourceError(
                "A volunteer profile already exists for this account. Use PATCH to update it."
            )

        data = payload.model_dump(exclude_none=True)
        # Coerce HttpUrl to plain string for DB storage
        if "profile_photo_url" in data and data["profile_photo_url"] is not None:
            data["profile_photo_url"] = str(data["profile_photo_url"])

        profile = VolunteerProfile(user_id=user.id, **data)
        self._db.add(profile)
        await self._db.flush()
        return profile

    async def get_my_profile(self, user: User) -> VolunteerProfile:
        profile = await self._get_profile_by_user_id(user.id)
        if profile is None:
            raise ProfileNotFoundError(
                "No profile found. Please create your volunteer profile first."
            )
        return profile

    async def update_my_profile(
        self, user: User, payload: VolunteerProfileUpdate
    ) -> VolunteerProfile:
        profile = await self.get_my_profile(user)
        update_data = payload.model_dump(exclude_unset=True)

        if "profile_photo_url" in update_data and update_data["profile_photo_url"] is not None:
            update_data["profile_photo_url"] = str(update_data["profile_photo_url"])

        for field, value in update_data.items():
            setattr(profile, field, value)

        self._db.add(profile)
        return profile

    # ── Admin: get any profile ────────────────────────────────────────────────

    async def get_profile_by_id(self, profile_id: uuid.UUID) -> VolunteerProfile:
        profile = await self._get_profile_by_id(profile_id)
        if profile is None:
            raise ProfileNotFoundError()
        return profile

    async def get_profile_by_user_id(self, user_id: uuid.UUID) -> VolunteerProfile:
        profile = await self._get_profile_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError()
        return profile

    # ── Admin: list / search volunteers ───────────────────────────────────────

    async def list_volunteers(
        self,
        *,
        city: str | None = None,
        country: str | None = None,
        skill: str | None = None,
        availability: AvailabilityType | None = None,
        skill_level: SkillLevel | None = None,
        search: str | None = None,
    ):
        """
        Return a composable SELECT statement for paginated volunteer listing.
        The caller applies .offset() / .limit() before executing.
        """
        from sqlalchemy import func as safunc, or_
        from sqlalchemy.dialects.postgresql import array

        stmt = (
            select(VolunteerProfile)
            .join(VolunteerProfile.user)
            .where(User.is_deleted.is_(False))
            .options(selectinload(VolunteerProfile.user))
        )

        if city:
            stmt = stmt.where(
                safunc.lower(VolunteerProfile.city).like(f"%{city.lower()}%")
            )
        if country:
            stmt = stmt.where(
                safunc.lower(VolunteerProfile.country) == country.lower()
            )
        if availability:
            stmt = stmt.where(VolunteerProfile.availability == availability)
        if skill_level:
            stmt = stmt.where(VolunteerProfile.skill_level == skill_level)
        if skill:
            # PostgreSQL ARRAY contains operator via any()
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import ARRAY
            from sqlalchemy import String
            stmt = stmt.where(
                VolunteerProfile.skills.any(skill)  # type: ignore[attr-defined]
            )
        if search:
            pattern = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    safunc.lower(User.first_name).like(pattern),
                    safunc.lower(User.last_name).like(pattern),
                    safunc.lower(User.email).like(pattern),
                )
            )
        return stmt.order_by(VolunteerProfile.created_at.desc())

    # ── Admin: credit hours ───────────────────────────────────────────────────

    async def credit_hours(self, profile_id: uuid.UUID, hours: int) -> VolunteerProfile:
        profile = await self.get_profile_by_id(profile_id)
        profile.total_volunteer_hours += hours
        self._db.add(profile)
        return profile

    # ── Admin: update any profile ─────────────────────────────────────────────

    async def admin_update_profile(
        self, profile_id: uuid.UUID, payload: VolunteerProfileUpdate
    ) -> VolunteerProfile:
        profile = await self.get_profile_by_id(profile_id)
        update_data = payload.model_dump(exclude_unset=True)
        if "profile_photo_url" in update_data and update_data["profile_photo_url"] is not None:
            update_data["profile_photo_url"] = str(update_data["profile_photo_url"])
        for field, value in update_data.items():
            setattr(profile, field, value)
        self._db.add(profile)
        return profile