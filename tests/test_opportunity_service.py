from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError 

from app.models.enums import OpportunityCategory, OpportunityStatus
from app.models.user import User
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.services.opportunity_service import OpportunityService
from app.utils.exceptions import (
    BadRequestError,
    InvalidStateTransitionError,
    OpportunityNotFoundError,
)


# ────────────────────────────────────────────────────────────────────────────
# Fixtures: Test Data
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def test_staff_user(db_session: AsyncSession) -> User:
    """Create a test staff user for opportunity ownership."""
    from app.models.enums import UserRole, UserStatus
    from app.models.user import User

    # Initialise the User object matching your exact model parameters
    user = User(
        email="staff@test.com",
        hashed_password="hashed_password_xyz",  # Maps directly to your Mapped[str] column
        first_name="Staff",
        last_name="User",
        role=UserRole.STAFF,
        status=UserStatus.ACTIVE,
        is_email_verified=True,  # Changed from email_verified to match your model
    )
    
    db_session.add(user)
    await db_session.flush()  # Populates user.id safely in the transaction
    return user



@pytest.fixture
def base_opportunity_create() -> dict:
    """Base data for opportunity creation."""
    now = datetime.now(timezone.utc)
    return {
        "title": "Beach Cleanup Initiative",
        "description": "Join us for a community beach cleanup event to remove plastic waste and protect marine life.",
        "short_description": "Help clean our beaches!",
        # ─── FIXED HERE ───
        "category": OpportunityCategory.ENVIRONMENT, 
        "start_date": now + timedelta(days=7),
        "end_date": now + timedelta(days=7, hours=4),
        "application_deadline": now + timedelta(days=5),
        "slots_total": 25,
        "location_name": "Crystal Cove",
        "location_address": "123 Beach Road",
        "city": "Newport Beach",
        "state_province": "California",
        "country": "USA",
        "is_remote": "False",
        "required_skills": ["Physical Fitness", "Teamwork"],
        "estimated_hours": 4,
    }



# ────────────────────────────────────────────────────────────────────────────
# Test: Create Opportunity
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_opportunity_success(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Create opportunity and verify all properties persisted to DB."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)

    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Verify all fields persisted
    assert opp.id is not None
    assert opp.title == "Beach Cleanup Initiative"
    assert opp.description == "Join us for a community beach cleanup event to remove plastic waste and protect marine life."
    assert opp.short_description == "Help clean our beaches!"
    assert opp.category == OpportunityCategory.ENVIRONMENT
    assert opp.status == OpportunityStatus.DRAFT
    assert opp.slots_total == 25
    assert opp.slots_filled == 0
    assert opp.location_name == "Crystal Cove"
    assert opp.location_address == "123 Beach Road"
    assert opp.city == "Newport Beach"
    assert opp.state_province == "California"
    assert opp.country == "USA"
    assert opp.is_remote is False
    assert opp.required_skills == ["Physical Fitness", "Teamwork"]
    assert opp.estimated_hours == 4
    assert opp.created_by_id == test_staff_user.id
    assert opp.created_at is not None
    assert opp.is_deleted is False


@pytest.mark.asyncio
async def test_create_opportunity_minimal(
    db_session: AsyncSession,
    test_staff_user: User,
) -> None:
    """Create opportunity with minimal required fields."""
    now = datetime.now(timezone.utc)
    payload = OpportunityCreate(
        title="Minimal Opportunity",
        description="This is a minimal opportunity with only required fields.",
        category=OpportunityCategory.EDUCATION,
        start_date=now + timedelta(days=1),
        end_date=now + timedelta(days=1, hours=2),
        slots_total=5,
    )

    svc = OpportunityService(db_session)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    assert opp.title == "Minimal Opportunity"
    assert opp.category == OpportunityCategory.EDUCATION
    assert opp.status == OpportunityStatus.DRAFT
    assert opp.slots_total == 5
    assert opp.slots_filled == 0
    assert opp.country == "India"  # default
    assert opp.is_remote is False  # default
    assert opp.required_skills is None


@pytest.mark.asyncio
async def test_create_opportunity_remote(
    db_session: AsyncSession,
    test_staff_user: User,
) -> None:
    """Create a remote opportunity."""
    now = datetime.now(timezone.utc)
    payload = OpportunityCreate(
        title="Remote Coding Mentorship",
        description="Mentor junior developers remotely.",
        category=OpportunityCategory.ENVIRONMENT,
        start_date=now + timedelta(days=1),
        end_date=now + timedelta(days=30),
        slots_total=10,
        is_remote="True",
    )

    svc = OpportunityService(db_session)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    assert opp.is_remote is True
    assert opp.location_name is None
    assert opp.city is None


# ────────────────────────────────────────────────────────────────────────────
# Test: Get Opportunity
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_opportunity_success(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Retrieve an opportunity by ID."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    created_opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    retrieved_opp = await svc.get_opportunity(created_opp.id)

    assert retrieved_opp.id == created_opp.id
    assert retrieved_opp.title == created_opp.title


@pytest.mark.asyncio
async def test_get_opportunity_not_found(db_session: AsyncSession) -> None:
    """Get opportunity raises OpportunityNotFoundError for invalid ID."""
    svc = OpportunityService(db_session)
    fake_id = uuid.uuid4()

    with pytest.raises(OpportunityNotFoundError):
        await svc.get_opportunity(fake_id)


# ────────────────────────────────────────────────────────────────────────────
# Test: State Machine - Valid Transitions
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transition_draft_to_published(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """DRAFT -> PUBLISHED transition succeeds."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    assert opp.status == OpportunityStatus.DRAFT

    published_opp = await svc.publish_opportunity(opp.id)
    await db_session.flush()

    assert published_opp.status == OpportunityStatus.PUBLISHED


@pytest.mark.asyncio
async def test_transition_draft_to_cancelled(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """DRAFT -> CANCELLED transition succeeds."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    cancelled_opp = await svc.cancel_opportunity(opp.id)
    await db_session.flush()

    assert cancelled_opp.status == OpportunityStatus.CANCELLED


@pytest.mark.asyncio
async def test_transition_published_to_closed(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """PUBLISHED -> CLOSED transition succeeds."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish first
    await svc.publish_opportunity(opp.id)
    await db_session.flush()

    # Then close
    closed_opp = await svc.close_opportunity(opp.id)
    await db_session.flush()

    assert closed_opp.status == OpportunityStatus.CLOSED


@pytest.mark.asyncio
async def test_transition_published_to_cancelled(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """PUBLISHED -> CANCELLED transition succeeds."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish first
    await svc.publish_opportunity(opp.id)
    await db_session.flush()

    # Then cancel
    cancelled_opp = await svc.cancel_opportunity(opp.id)
    await db_session.flush()

    assert cancelled_opp.status == OpportunityStatus.CANCELLED


@pytest.mark.asyncio
async def test_transition_published_to_completed(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """PUBLISHED -> COMPLETED transition via update_opportunity."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish first
    await svc.publish_opportunity(opp.id)
    await db_session.flush()

    # Update to COMPLETED
    update_payload = OpportunityUpdate(status=OpportunityStatus.COMPLETED)
    completed_opp = await svc.update_opportunity(opp.id, update_payload)
    await db_session.flush()

    assert completed_opp.status == OpportunityStatus.COMPLETED


@pytest.mark.asyncio
async def test_transition_closed_to_published(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """CLOSED -> PUBLISHED transition succeeds (reopen opportunity)."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish -> Close
    await svc.publish_opportunity(opp.id)
    await db_session.flush()
    await svc.close_opportunity(opp.id)
    await db_session.flush()

    # Reopen to PUBLISHED
    reopened_opp = await svc.publish_opportunity(opp.id)
    await db_session.flush()

    assert reopened_opp.status == OpportunityStatus.PUBLISHED


# ────────────────────────────────────────────────────────────────────────────
# Test: State Machine - Invalid Transitions
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transition_draft_to_closed_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """DRAFT -> CLOSED transition raises InvalidStateTransitionError."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    assert opp.status == OpportunityStatus.DRAFT

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        await svc.close_opportunity(opp.id)

    assert "Cannot close" in str(exc_info.value.detail)
    assert "draft" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_transition_published_to_draft_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """PUBLISHED -> DRAFT transition (invalid) raises error."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish first
    await svc.publish_opportunity(opp.id)
    await db_session.flush()

    # Try to transition to DRAFT (invalid)
    update_payload = OpportunityUpdate(status=OpportunityStatus.DRAFT)

    with pytest.raises(InvalidStateTransitionError):
        await svc.update_opportunity(opp.id, update_payload)


@pytest.mark.asyncio
async def test_transition_cancelled_to_any_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """CANCELLED is terminal; any transition fails."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Cancel
    await svc.cancel_opportunity(opp.id)
    await db_session.flush()

    # Try to transition from CANCELLED to PUBLISHED
    with pytest.raises(InvalidStateTransitionError):
        await svc.publish_opportunity(opp.id)


@pytest.mark.asyncio
async def test_transition_completed_to_any_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """COMPLETED is terminal; any transition fails."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish first (required before COMPLETED)
    await svc.publish_opportunity(opp.id)
    await db_session.flush()

    # Transition to COMPLETED
    update_payload = OpportunityUpdate(status=OpportunityStatus.COMPLETED)
    await svc.update_opportunity(opp.id, update_payload)
    await db_session.flush()

    # Try to close a COMPLETED opportunity
    with pytest.raises(InvalidStateTransitionError):
        await svc.close_opportunity(opp.id)


# ────────────────────────────────────────────────────────────────────────────
# Test: Update Opportunity
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_opportunity_title(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Update opportunity title while in DRAFT."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    update_payload = OpportunityUpdate(title="Updated Beach Cleanup")
    updated_opp = await svc.update_opportunity(opp.id, update_payload)
    await db_session.flush()

    assert updated_opp.title == "Updated Beach Cleanup"
    assert updated_opp.description == base_opportunity_create["description"]


@pytest.mark.asyncio
async def test_update_opportunity_slots_total(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Update slots_total while slots_filled validation passes."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Manually set slots_filled (simulating accepted applications)
    opp.slots_filled = 10
    await db_session.flush()

    # Increase slots_total (should succeed)
    update_payload = OpportunityUpdate(slots_total=30)
    updated_opp = await svc.update_opportunity(opp.id, update_payload)
    await db_session.flush()

    assert updated_opp.slots_total == 30
    assert updated_opp.slots_filled == 10



@pytest.mark.asyncio
async def test_update_opportunity_slots_total_below_filled_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Reducing slots_total below slots_filled triggers database constraint failure."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    
    # 1. Force state simulation where slots are already filled
    opp.slots_filled = 5
    await db_session.flush()

    # 2. Try to reduce slots_total below slots_filled
    update_payload = OpportunityUpdate(slots_total=2)

    # 3. FIXED HERE: Catch the actual database IntegrityError thrown by the CHECK constraint
    with pytest.raises(IntegrityError):
        await svc.update_opportunity(opp.id, update_payload)
        await db_session.flush()  # Force SQLite to process the invalid write



@pytest.mark.asyncio
async def test_update_cancelled_opportunity_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Updating a CANCELLED opportunity raises InvalidStateTransitionError."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Cancel the opportunity
    await svc.cancel_opportunity(opp.id)
    await db_session.flush()

    # Try to update
    update_payload = OpportunityUpdate(title="Updated Title")

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        await svc.update_opportunity(opp.id, update_payload)

    assert "Cannot update" in str(exc_info.value.detail)
    assert "cancelled" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_completed_opportunity_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Updating a COMPLETED opportunity raises InvalidStateTransitionError."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Publish -> Complete
    await svc.publish_opportunity(opp.id)
    await db_session.flush()
    update_payload = OpportunityUpdate(status=OpportunityStatus.COMPLETED)
    await svc.update_opportunity(opp.id, update_payload)
    await db_session.flush()

    # Try to update
    update_payload = OpportunityUpdate(title="Updated Title")

    with pytest.raises(InvalidStateTransitionError):
        await svc.update_opportunity(opp.id, update_payload)


# ────────────────────────────────────────────────────────────────────────────
# Test: Error Paths - Not Found
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_nonexistent_opportunity_fails(db_session: AsyncSession) -> None:
    """Updating non-existent opportunity raises OpportunityNotFoundError."""
    svc = OpportunityService(db_session)
    fake_id = uuid.uuid4()
    update_payload = OpportunityUpdate(title="New Title")

    with pytest.raises(OpportunityNotFoundError):
        await svc.update_opportunity(fake_id, update_payload)


@pytest.mark.asyncio
async def test_publish_nonexistent_opportunity_fails(db_session: AsyncSession) -> None:
    """Publishing non-existent opportunity raises OpportunityNotFoundError."""
    svc = OpportunityService(db_session)
    fake_id = uuid.uuid4()

    with pytest.raises(OpportunityNotFoundError):
        await svc.publish_opportunity(fake_id)


@pytest.mark.asyncio
async def test_close_nonexistent_opportunity_fails(db_session: AsyncSession) -> None:
    """Closing non-existent opportunity raises OpportunityNotFoundError."""
    svc = OpportunityService(db_session)
    fake_id = uuid.uuid4()

    with pytest.raises(OpportunityNotFoundError):
        await svc.close_opportunity(fake_id)


@pytest.mark.asyncio
async def test_cancel_nonexistent_opportunity_fails(db_session: AsyncSession) -> None:
    """Cancelling non-existent opportunity raises OpportunityNotFoundError."""
    svc = OpportunityService(db_session)
    fake_id = uuid.uuid4()

    with pytest.raises(OpportunityNotFoundError):
        await svc.cancel_opportunity(fake_id)


# ────────────────────────────────────────────────────────────────────────────
# Test: Slot Helpers
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slots_available_calculation(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """slots_available property reflects correct available slots."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    assert opp.slots_available == 25
    assert opp.is_full is False

    # Simulate filling 20 slots
    opp.slots_filled = 20
    assert opp.slots_available == 5
    assert opp.is_full is False

    # Fill all slots
    opp.slots_filled = 25
    assert opp.slots_available == 0
    assert opp.is_full is True


# ────────────────────────────────────────────────────────────────────────────
# Test: Soft Delete
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_soft_deleted_opportunity_fails(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Getting a soft-deleted opportunity raises OpportunityNotFoundError."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # Soft delete
    opp.is_deleted = True
    await db_session.flush()

    # Try to retrieve
    with pytest.raises(OpportunityNotFoundError):
        await svc.get_opportunity(opp.id)


# ────────────────────────────────────────────────────────────────────────────
# Test: Multiple Updates in Sequence
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sequential_updates_in_draft(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Multiple updates to a DRAFT opportunity succeed."""
    svc = OpportunityService(db_session)
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()

    # First update: title
    update1 = OpportunityUpdate(title="Updated Title")
    opp = await svc.update_opportunity(opp.id, update1)
    await db_session.flush()
    assert opp.title == "Updated Title"

    # Second update: description
    update2 = OpportunityUpdate(description="Updated description with more details.")
    opp = await svc.update_opportunity(opp.id, update2)
    await db_session.flush()
    assert opp.description == "Updated description with more details."

    # Third update: slots
    update3 = OpportunityUpdate(slots_total=50)
    opp = await svc.update_opportunity(opp.id, update3)
    await db_session.flush()
    assert opp.slots_total == 50
    assert opp.title == "Updated Title"  # Previous updates still in place


# ────────────────────────────────────────────────────────────────────────────
# Test: Complete Workflow
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_opportunity_workflow(
    db_session: AsyncSession,
    test_staff_user: User,
    base_opportunity_create: dict,
) -> None:
    """Full workflow: create -> update -> publish -> close -> complete."""
    svc = OpportunityService(db_session)

    # Create in DRAFT
    payload = OpportunityCreate(**base_opportunity_create)
    opp = await svc.create_opportunity(payload, test_staff_user)
    await db_session.flush()
    assert opp.status == OpportunityStatus.DRAFT

    # Update while in DRAFT
    update1 = OpportunityUpdate(title="Updated for Publication")
    opp = await svc.update_opportunity(opp.id, update1)
    await db_session.flush()
    assert opp.title == "Updated for Publication"

    # Publish
    opp = await svc.publish_opportunity(opp.id)
    await db_session.flush()
    assert opp.status == OpportunityStatus.PUBLISHED

    # Close
    opp = await svc.close_opportunity(opp.id)
    await db_session.flush()
    assert opp.status == OpportunityStatus.CLOSED

    # Reopen
    opp = await svc.publish_opportunity(opp.id)
    await db_session.flush()
    assert opp.status == OpportunityStatus.PUBLISHED

    # Mark as completed
    update2 = OpportunityUpdate(status=OpportunityStatus.COMPLETED)
    opp = await svc.update_opportunity(opp.id, update2)
    await db_session.flush()
    assert opp.status == OpportunityStatus.COMPLETED

    # Verify cannot update completed
    with pytest.raises(InvalidStateTransitionError):
        await svc.update_opportunity(opp.id, OpportunityUpdate(title="Should Fail"))
