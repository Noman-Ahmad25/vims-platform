from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import OpportunityCategory, OpportunityStatus
from app.models.opportunity import Opportunity
from app.models.user import User
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.utils.exceptions import (
    BadRequestError,
    InvalidStateTransitionError,
    OpportunityNotFoundError,
    PermissionDeniedError,
)

# Valid status transitions that staff/admin may perform
_ALLOWED_TRANSITIONS: dict[OpportunityStatus, set[OpportunityStatus]] = {
    OpportunityStatus.DRAFT: {
        OpportunityStatus.PUBLISHED,
        OpportunityStatus.CANCELLED,
    },
    OpportunityStatus.PUBLISHED: {
        OpportunityStatus.CLOSED,
        OpportunityStatus.CANCELLED,
        OpportunityStatus.COMPLETED,
    },
    OpportunityStatus.CLOSED: {
        OpportunityStatus.PUBLISHED,
        OpportunityStatus.CANCELLED,
        OpportunityStatus.COMPLETED,
    },
    OpportunityStatus.CANCELLED: set(),
    OpportunityStatus.COMPLETED: set(),
}


class OpportunityService:
    """
    CRUD and state-machine logic for Opportunity records.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _get_by_id(self, opp_id: uuid.UUID) -> Opportunity | None:
        result = await self._db.execute(
            select(Opportunity)
            .where(Opportunity.id == opp_id, Opportunity.is_deleted.is_(False))
            .options(selectinload(Opportunity.created_by))
        )
        return result.scalar_one_or_none()

    async def _get_by_id_or_raise(self, opp_id: uuid.UUID) -> Opportunity:
        opp = await self._get_by_id(opp_id)
        if opp is None:
            raise OpportunityNotFoundError()
        return opp

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create_opportunity(
        self, payload: OpportunityCreate, created_by: User
    ) -> Opportunity:
        data = payload.model_dump()
        opp = Opportunity(
            **data,
            created_by_id=created_by.id,
            status=OpportunityStatus.DRAFT,
            slots_filled=0,
        )
        self._db.add(opp)
        await self._db.flush()
        return opp

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get_opportunity(self, opp_id: uuid.UUID) -> Opportunity:
        return await self._get_by_id_or_raise(opp_id)

    async def list_opportunities(
        self,
        *,
        status: OpportunityStatus | None = None,
        category: OpportunityCategory | None = None,
        city: str | None = None,
        country: str | None = None,
        is_remote: bool | None = None,
        search: str | None = None,
        include_drafts: bool = False,
    ):
        """
        Return a composable SELECT.  Callers add .offset()/.limit() before execute.
        """
        from sqlalchemy import func as safunc, or_

        stmt = select(Opportunity).where(Opportunity.is_deleted.is_(False))

        if not include_drafts:
            stmt = stmt.where(Opportunity.status == OpportunityStatus.PUBLISHED)
        elif status is not None:
            stmt = stmt.where(Opportunity.status == status)

        if category is not None:
            stmt = stmt.where(Opportunity.category == category)
        if city:
            stmt = stmt.where(
                safunc.lower(Opportunity.city).like(f"%{city.lower()}%")
            )
        if country:
            stmt = stmt.where(
                safunc.lower(Opportunity.country) == country.lower()
            )
        if is_remote is not None:
            stmt = stmt.where(Opportunity.is_remote == is_remote)
        if search:
            pattern = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    safunc.lower(Opportunity.title).like(pattern),
                    safunc.lower(Opportunity.description).like(pattern),
                )
            )
        return stmt.order_by(Opportunity.start_date.asc())

    # ── Update ─────────────────────────────────────────────────────────────────

    async def update_opportunity(
    self, opp_id: uuid.UUID, payload: OpportunityUpdate
) -> Opportunity:
        opp = await self._get_by_id_or_raise(opp_id)
        
        # 1. Safely extract current status value as a plain string string
        opp_status_str = opp.status.value if hasattr(opp.status, "value") else opp.status

        # 2. Prevent updating terminal opportunities
        if opp_status_str in ("cancelled", "completed"):
            raise InvalidStateTransitionError(
                f"Cannot update an opportunity with status '{opp_status_str}'."
            )

        update_data = payload.model_dump(exclude_unset=True)

        # 3. Validate status transition if caller is changing status
        if "status" in update_data:
            status_input = update_data["status"]
            new_status_str = status_input.value if hasattr(status_input, "value") else status_input
            
            # Map Enum key lookups safely using string values or native enums
            allowed = _ALLOWED_TRANSITIONS.get(opp.status, set())
            # Handle if the keys in _ALLOWED_TRANSITIONS are strings or enums
            allowed_strs = {s.value if hasattr(s, "value") else s for s in allowed}
            
            if new_status_str not in allowed_strs:
                raise InvalidStateTransitionError(
                    f"Cannot transition from '{opp_status_str}' to '{new_status_str}'."
                )

        # ─── CRITICAL CORRECTION: MUTATE THE ATTRIBUTES ───
        # This loops through your incoming dictionary fields and updates the DB object
        for key, value in update_data.items():
            setattr(opp, key, value)
            
        self._db.add(opp)
        await self._db.flush()
        await self._db.refresh(opp)
        
        return opp  # Returns the updated instance to get rid of NoneType errors




    # ── Publish / close shortcuts ──────────────────────────────────────────────

    async def publish_opportunity(self, opp_id: uuid.UUID) -> Opportunity:
        opp = await self._get_by_id_or_raise(opp_id)
        opp_status_str = opp.status.value if hasattr(opp.status, "value") else opp.status

        if opp_status_str != "draft" and opp_status_str != "closed":
            raise InvalidStateTransitionError(
                f"Cannot publish an opportunity with status '{opp_status_str}'."
            )

        opp.status = OpportunityStatus.PUBLISHED
        self._db.add(opp)
        await self._db.flush()
        await self._db.refresh(opp)
        return opp  # ── CRITICAL FIX ──

    async def close_opportunity(self, opp_id: uuid.UUID) -> Opportunity:
        opp = await self._get_by_id_or_raise(opp_id)
        opp_status_str = opp.status.value if hasattr(opp.status, "value") else opp.status

        if opp_status_str != "published":
            raise InvalidStateTransitionError(
                f"Cannot close an opportunity with status '{opp_status_str}'."
            )

        opp.status = OpportunityStatus.CLOSED
        self._db.add(opp)
        await self._db.flush()
        await self._db.refresh(opp)
        return opp  # ── CRITICAL FIX ──



    async def cancel_opportunity(self, opp_id: uuid.UUID) -> Opportunity:
        opp = await self._get_by_id_or_raise(opp_id)
        allowed = _ALLOWED_TRANSITIONS.get(opp.status, set())
        if OpportunityStatus.CANCELLED not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot cancel an opportunity with status '{opp.status.value}'."
            )
        opp.status = OpportunityStatus.CANCELLED
        self._db.add(opp)
        return opp

    # ── Soft delete ────────────────────────────────────────────────────────────

    async def soft_delete_opportunity(self, opp_id: uuid.UUID) -> None:
        opp = await self._get_by_id_or_raise(opp_id)
        if opp.status == OpportunityStatus.PUBLISHED:
            raise InvalidStateTransitionError(
                "Close or cancel the opportunity before deleting it."
            )
        opp.is_deleted = True
        opp.deleted_at = datetime.now(timezone.utc)
        self._db.add(opp)