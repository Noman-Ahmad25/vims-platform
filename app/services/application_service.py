from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import ApplicationStatus, OpportunityStatus
from app.models.opportunity import Application, Opportunity
from app.models.user import User, VolunteerProfile
from app.schemas.opportunity import (
    ApplicationCompleteRequest,
    ApplicationCreate,
    ApplicationReviewRequest,
)
from app.utils.exceptions import (
    ApplicationNotFoundError,
    BadRequestError,
    DuplicateResourceError,
    InvalidStateTransitionError,
    OpportunityNotFoundError,
    PermissionDeniedError,
    ProfileNotFoundError,
    SlotCapacityExceededError,
)

# Statuses from which a volunteer may withdraw
_WITHDRAWABLE_STATUSES = {
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.WAITLISTED,
}

# Staff-allowed review target statuses (not COMPLETED — that uses its own endpoint)
_REVIEWABLE_TARGET_STATUSES = {
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WAITLISTED,
}


class ApplicationService:
    """
    Application workflow: submit, review, withdraw, complete.
    Owns slot counter consistency on the parent Opportunity.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _get_application_by_id(self, app_id: uuid.UUID) -> Application | None:
        result = await self._db.execute(
            select(Application)
            .where(Application.id == app_id)
            .options(
                selectinload(Application.volunteer_profile).selectinload(
                    VolunteerProfile.user
                ),
                selectinload(Application.opportunity),
            )
        )
        return result.scalar_one_or_none()

    async def _get_application_or_raise(self, app_id: uuid.UUID) -> Application:
        app = await self._get_application_by_id(app_id)
        if app is None:
            raise ApplicationNotFoundError()
        return app

    async def _get_profile_or_raise(self, user_id: uuid.UUID) -> VolunteerProfile:
        result = await self._db.execute(
            select(VolunteerProfile).where(VolunteerProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ProfileNotFoundError(
                "Please create your volunteer profile before applying."
            )
        return profile

    async def _get_opportunity_or_raise(self, opp_id: uuid.UUID) -> Opportunity:
        result = await self._db.execute(
            select(Opportunity).where(
                Opportunity.id == opp_id,
                Opportunity.is_deleted.is_(False),
            )
        )
        opp = result.scalar_one_or_none()
        if opp is None:
            raise OpportunityNotFoundError()
        return opp

    async def _check_duplicate(
        self, profile_id: uuid.UUID, opp_id: uuid.UUID
    ) -> None:
        result = await self._db.execute(
            select(Application).where(
                Application.volunteer_profile_id == profile_id,
                Application.opportunity_id == opp_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise DuplicateResourceError(
                "You have already applied to this opportunity."
            )

    # ── Submit ─────────────────────────────────────────────────────────────────

    async def submit_application(
        self, current_user: User, payload: ApplicationCreate
    ) -> Application:
        profile = await self._get_profile_or_raise(current_user.id)
        opp = await self._get_opportunity_or_raise(payload.opportunity_id)

        if opp.status != OpportunityStatus.PUBLISHED:
            raise BadRequestError("This opportunity is not open for applications.")

        if opp.application_deadline is not None:
            deadline = opp.application_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > deadline:
                raise BadRequestError("The application deadline for this opportunity has passed.")

        if opp.is_full:
            raise SlotCapacityExceededError()

        await self._check_duplicate(profile.id, opp.id)

        application = Application(
            volunteer_profile_id=profile.id,
            opportunity_id=opp.id,
            cover_letter=payload.cover_letter,
            motivation=payload.motivation,
            status=ApplicationStatus.SUBMITTED,
        )
        self._db.add(application)
        await self._db.flush()
        return application

    # ── Volunteer: view own applications ──────────────────────────────────────

    async def list_my_applications(self, current_user: User):
        """Return a composable SELECT for the volunteer's own applications."""
        profile_result = await self._db.execute(
            select(VolunteerProfile).where(
                VolunteerProfile.user_id == current_user.id
            )
        )
        profile = profile_result.scalar_one_or_none()
        if profile is None:
            # Return an empty result set without raising
            return select(Application).where(Application.id == None)  # noqa

        return (
            select(Application)
            .where(Application.volunteer_profile_id == profile.id)
            .options(selectinload(Application.opportunity))
            .order_by(Application.created_at.desc())
        )

    async def get_my_application(
        self, current_user: User, app_id: uuid.UUID
    ) -> Application:
        profile_result = await self._db.execute(
            select(VolunteerProfile).where(
                VolunteerProfile.user_id == current_user.id
            )
        )
        profile = profile_result.scalar_one_or_none()
        if profile is None:
            raise ApplicationNotFoundError()

        result = await self._db.execute(
            select(Application)
            .where(
                Application.id == app_id,
                Application.volunteer_profile_id == profile.id,
            )
            .options(selectinload(Application.opportunity))
        )
        app = result.scalar_one_or_none()
        if app is None:
            raise ApplicationNotFoundError()
        return app

    # ── Volunteer: withdraw ────────────────────────────────────────────────────

    async def withdraw_application(
        self, current_user: User, app_id: uuid.UUID, reason: str | None = None
    ) -> Application:
        app = await self.get_my_application(current_user, app_id)

        if app.status not in _WITHDRAWABLE_STATUSES:
            raise InvalidStateTransitionError(
                f"Cannot withdraw an application with status '{app.status.value}'."
            )

        # Release the slot if it was ACCEPTED (slot was already counted)
        if app.status == ApplicationStatus.ACCEPTED:
            opp = await self._get_opportunity_or_raise(app.opportunity_id)
            if opp.slots_filled > 0:
                opp.slots_filled -= 1
                self._db.add(opp)

        app.status = ApplicationStatus.WITHDRAWN
        if reason:
            app.staff_notes = f"Withdrawn by volunteer. Reason: {reason}"
        self._db.add(app)
        return app

    # ── Staff: list applications for an opportunity ───────────────────────────

    async def list_applications_for_opportunity(
        self,
        opp_id: uuid.UUID,
        *,
        status: ApplicationStatus | None = None,
    ):
        stmt = (
            select(Application)
            .where(Application.opportunity_id == opp_id)
            .options(
                selectinload(Application.volunteer_profile).selectinload(
                    VolunteerProfile.user
                ),
                selectinload(Application.opportunity),
            )
            .order_by(Application.created_at.asc())
        )
        if status is not None:
            stmt = stmt.where(Application.status == status)
        return stmt

    # ── Staff: get single application ─────────────────────────────────────────

    async def get_application_by_id(self, app_id: uuid.UUID) -> Application:
        return await self._get_application_or_raise(app_id)

    # ── Staff: review (accept / reject / waitlist / mark under-review) ────────

    async def review_application(
        self,
        app_id: uuid.UUID,
        reviewing_staff: User,
        payload: ApplicationReviewRequest,
    ) -> Application:
        app = await self._get_application_or_raise(app_id)

        if payload.status not in _REVIEWABLE_TARGET_STATUSES:
            raise BadRequestError(
                f"Status '{payload.status.value}' cannot be set via review. "
                "Use the /complete endpoint to mark an application as completed."
            )

        # Guard: cannot review an already-terminal application
        terminal = {ApplicationStatus.WITHDRAWN, ApplicationStatus.COMPLETED}
        if app.status in terminal:
            raise InvalidStateTransitionError(
                f"Cannot review an application with status '{app.status.value}'."
            )

        opp = await self._get_opportunity_or_raise(app.opportunity_id)

        # Increment slot counter when accepting
        if (
            payload.status == ApplicationStatus.ACCEPTED
            and app.status != ApplicationStatus.ACCEPTED
        ):
            if opp.is_full:
                raise SlotCapacityExceededError(
                    "All slots are filled. Waitlist the applicant instead."
                )
            opp.slots_filled += 1
            self._db.add(opp)

        # Decrement slot counter if moving away from ACCEPTED
        if (
            app.status == ApplicationStatus.ACCEPTED
            and payload.status != ApplicationStatus.ACCEPTED
        ):
            if opp.slots_filled > 0:
                opp.slots_filled -= 1
            self._db.add(opp)

        app.status = payload.status
        app.staff_notes = payload.staff_notes
        app.rejection_reason = payload.rejection_reason
        app.reviewed_by_id = reviewing_staff.id
        app.reviewed_at = datetime.now(timezone.utc)
        self._db.add(app)
        return app

    # ── Staff: complete ────────────────────────────────────────────────────────

    async def complete_application(
        self,
        app_id: uuid.UUID,
        reviewing_staff: User,
        payload: ApplicationCompleteRequest,
    ) -> Application:
        app = await self._get_application_or_raise(app_id)

        if app.status != ApplicationStatus.ACCEPTED:
            raise InvalidStateTransitionError(
                "Only ACCEPTED applications can be marked as completed."
            )

        app.status = ApplicationStatus.COMPLETED
        app.outcome = payload.outcome
        app.hours_logged = payload.hours_logged
        app.rating = payload.rating
        app.feedback = payload.feedback
        app.completed_at = datetime.now(timezone.utc)
        app.reviewed_by_id = reviewing_staff.id
        app.reviewed_at = datetime.now(timezone.utc)

        # Credit hours to the volunteer's running total
        profile = app.volunteer_profile
        profile.total_volunteer_hours += payload.hours_logged
        self._db.add(profile)
        self._db.add(app)
        return app

    # ── Staff: list all applications across all opportunities ─────────────────

    async def list_all_applications(
        self,
        *,
        status: ApplicationStatus | None = None,
        opportunity_id: uuid.UUID | None = None,
    ):
        stmt = (
            select(Application)
            .options(
                selectinload(Application.volunteer_profile).selectinload(
                    VolunteerProfile.user
                ),
                selectinload(Application.opportunity),
            )
            .order_by(Application.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(Application.status == status)
        if opportunity_id is not None:
            stmt = stmt.where(Application.opportunity_id == opportunity_id)
        return stmt