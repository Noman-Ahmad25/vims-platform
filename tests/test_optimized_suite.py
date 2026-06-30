from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.v1.endpoints import admin as admin_endpoints
from app.core import database
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_password_reset_token,
    hash_password,
)
from app.main import app, lifespan
from app.models.enums import (
    ApplicationOutcome,
    ApplicationStatus,
    AvailabilityType,
    OpportunityCategory,
    OpportunityStatus,
    SkillLevel,
    UserRole,
    UserStatus,
)
from app.models.opportunity import Application, Opportunity
from app.models.user import User, VolunteerProfile
from app.schemas.auth import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    ChangePasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.opportunity import (
    ApplicationCompleteRequest,
    ApplicationCreate,
    ApplicationReviewRequest,
    OpportunityCreate,
    OpportunityUpdate,
)
from app.schemas.volunteer import VolunteerProfileCreate, VolunteerProfileUpdate
from app.services.application_service import ApplicationService
from app.services.opportunity_service import OpportunityService
from app.services.user_service import UserService
from app.services.volunteer_service import VolunteerService
from app.utils.exceptions import (
    ApplicationNotFoundError,
    AuthenticationError,
    BadRequestError,
    DuplicateResourceError,
    EmailNotVerifiedError,
    ExpiredTokenError,
    InvalidStateTransitionError,
    OpportunityNotFoundError,
    ProfileNotFoundError,
    SlotCapacityExceededError,
    UserNotFoundError,
    VIMSBaseException,
)
from app.utils.pagination import build_paginated_response, paginate

PASSWORD = "SecurePass123!@#"


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    role: UserRole = UserRole.VOLUNTEER,
    status: UserStatus = UserStatus.ACTIVE,
    verified: bool = True,
    deleted: bool = False,
) -> User:
    marker = uuid.uuid4().hex[:8]
    user = User(
        email=email or f"{role.value}-{marker}@example.com",
        hashed_password=hash_password(PASSWORD),
        first_name=role.value.title(),
        last_name="User",
        role=role,
        status=status,
        is_email_verified=verified,
        is_deleted=deleted,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def make_profile(
    db: AsyncSession,
    user: User,
    **overrides,
) -> VolunteerProfile:
    data = {
        "user_id": user.id,
        "phone_number": "+15551234567",
        "bio": "Experienced community volunteer.",
        "city": "Mumbai",
        "country": "India",
        "skills": ["Teaching", "First Aid"],
        "languages_spoken": ["English", "Hindi"],
        "availability": AvailabilityType.WEEKENDS,
        "skill_level": SkillLevel.INTERMEDIATE,
        "hours_per_week": 8,
    }
    data.update(overrides)
    profile = VolunteerProfile(**data)
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


def opportunity_data(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    data = {
        "title": "Community Reading Program",
        "description": "Help children build reading confidence through weekly sessions.",
        "short_description": "Read with children.",
        "category": OpportunityCategory.EDUCATION,
        "start_date": now + timedelta(days=10),
        "end_date": now + timedelta(days=10, hours=3),
        "application_deadline": now + timedelta(days=5),
        "slots_total": 2,
        "location_name": "Central Library",
        "location_address": "123 Library Road",
        "city": "Mumbai",
        "state_province": "Maharashtra",
        "country": "India",
        "is_remote": False,
        "required_skills": ["Teaching"],
        "minimum_age": 18,
        "estimated_hours": 3,
    }
    data.update(overrides)
    return data


def json_ready(payload: dict) -> dict:
    encoded = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            encoded[key] = value.isoformat()
        elif hasattr(value, "value"):
            encoded[key] = value.value
        else:
            encoded[key] = value
    return encoded


def review_request(status: ApplicationStatus, **kwargs) -> ApplicationReviewRequest:
    payload = ApplicationReviewRequest(status=status, **kwargs)
    payload.status = status
    return payload


async def make_opportunity(
    db: AsyncSession,
    creator: User,
    *,
    status: OpportunityStatus = OpportunityStatus.PUBLISHED,
    **overrides,
) -> Opportunity:
    slots_filled = overrides.pop("slots_filled", 0)
    data = opportunity_data(**overrides)
    opportunity = Opportunity(
        **data,
        status=status,
        slots_filled=slots_filled,
        created_by_id=creator.id,
    )
    db.add(opportunity)
    await db.flush()
    await db.refresh(opportunity)
    return opportunity


async def make_application(
    db: AsyncSession,
    profile: VolunteerProfile,
    opportunity: Opportunity,
    *,
    status: ApplicationStatus = ApplicationStatus.SUBMITTED,
) -> Application:
    application = Application(
        volunteer_profile_id=profile.id,
        opportunity_id=opportunity.id,
        status=status,
        cover_letter="I can help.",
        motivation="This mission matters.",
    )
    db.add(application)
    await db.flush()
    await db.refresh(application, attribute_names=["opportunity", "volunteer_profile"])
    return application


@pytest.mark.asyncio
async def test_public_auth_profile_and_token_happy_path(client: AsyncClient) -> None:
    register_payload = {
        "email": "alice@example.com",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        "first_name": "Alice",
        "last_name": "Wonder",
    }
    registered = await client.post("/api/v1/auth/register", json=register_payload)
    assert registered.status_code == 201
    verify_token = registered.json()["detail"]["email_verification_token"]

    verified = await client.get(f"/api/v1/auth/verify-email?token={verify_token}")
    assert verified.status_code == 200

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": PASSWORD},
    )
    assert login.status_code == 200
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["email"] == "alice@example.com"

    created_profile = await client.post(
        "/api/v1/volunteer/profile",
        json={
            "phone_number": "+1-555-123-4567",
            "bio": "Passionate about education.",
            "city": "San Francisco",
            "country": "USA",
            "skills": ["Teaching", "Mentoring"],
            "languages_spoken": ["English", "Spanish"],
            "hours_per_week": 10,
        },
        headers=headers,
    )
    assert created_profile.status_code == 201
    assert created_profile.json()["phone_number"] == "+15551234567"

    assert (await client.get("/api/v1/volunteer/profile", headers=headers)).status_code == 200
    patched = await client.patch(
        "/api/v1/volunteer/profile",
        json={"bio": "Updated bio.", "hours_per_week": 1},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["bio"] == "Updated bio."

    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 200
    revoked = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert revoked.status_code == 401


@pytest.mark.asyncio
async def test_auth_error_partitions_and_boundaries(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    invalid_register_payloads = [
        {
            "email": "not-an-email",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
            "first_name": "A",
            "last_name": "B",
        },
        {
            "email": "weak@example.com",
            "password": "short",
            "confirm_password": "short",
            "first_name": "A",
            "last_name": "B",
        },
        {
            "email": "mismatch@example.com",
            "password": PASSWORD,
            "confirm_password": "Different123!",
            "first_name": "A",
            "last_name": "B",
        },
        {
            "email": "missing@example.com",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
            "last_name": "B",
        },
    ]
    for payload in invalid_register_payloads:
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 422

    duplicate_payload = {
        "email": "duplicate@example.com",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        "first_name": "Dupe",
        "last_name": "User",
    }
    assert (await client.post("/api/v1/auth/register", json=duplicate_payload)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=duplicate_payload)).status_code == 409

    assert (await client.get("/api/v1/auth/verify-email")).status_code == 422
    assert (await client.get("/api/v1/auth/verify-email?token=invalid_token_xyz")).status_code == 410
    assert (await client.post("/api/v1/auth/login", json={"email": "bad", "password": PASSWORD})).status_code == 422
    assert (await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": "duplicate@example.com", "password": PASSWORD})).status_code == 403
    assert (await client.post("/api/v1/auth/login", json={"email": "duplicate@example.com", "password": "WrongPass123!"})).status_code == 401

    user = await make_user(db_session, email="change-password@example.com")
    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    wrong_current = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "WrongPassword123!",
            "new_password": "NewSecurePassword123!",
            "confirm_password": "NewSecurePassword123!",
        },
        headers=headers,
    )
    assert wrong_current.status_code == 401
    assert (await client.get("/api/v1/volunteer/profile")).status_code == 401
    assert (await client.get("/api/v1/volunteer/profile", headers={"Authorization": "Bearer nope"})).status_code == 401

    user.is_deleted = True
    await db_session.flush()
    deleted_login = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert deleted_login.status_code == 401


@pytest.mark.asyncio
async def test_admin_user_management_decision_table(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    admin = await make_user(db_session, role=UserRole.ADMIN, email="admin@example.com")
    volunteer = await make_user(db_session, role=UserRole.VOLUNTEER, email="plain@example.com")
    admin_headers = auth_headers(admin)

    assert (await client.get("/api/v1/admin/users", headers=auth_headers(volunteer))).status_code == 403

    create_payload = {
        "email": "new-staff@example.com",
        "password": PASSWORD,
        "first_name": "New",
        "last_name": "Staff",
        "role": "staff",
    }
    created = await client.post("/api/v1/admin/users", json=create_payload, headers=admin_headers)
    assert created.status_code == 201
    created_user_id = created.json()["id"]
    assert (await client.post("/api/v1/admin/users", json=create_payload, headers=admin_headers)).status_code == 409

    listed = await client.get(
        "/api/v1/admin/users?role=staff&search=new&page=1&page_size=10",
        headers=admin_headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    fetched = await client.get(f"/api/v1/admin/users/{created_user_id}", headers=admin_headers)
    assert fetched.status_code == 200
    assert fetched.json()["email"] == "new-staff@example.com"

    patched = await client.patch(
        f"/api/v1/admin/users/{created_user_id}",
        json={"status": "suspended", "first_name": "Updated", "role": "admin"},
        headers=admin_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "suspended"

    assert (await client.delete(f"/api/v1/admin/users/{admin.id}", headers=admin_headers)).status_code == 400
    assert (await client.delete(f"/api/v1/admin/users/{created_user_id}", headers=admin_headers)).status_code == 200
    assert (await client.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=admin_headers)).status_code == 404


@pytest.mark.asyncio
async def test_admin_volunteer_management_pairwise(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    staff = await make_user(db_session, role=UserRole.STAFF)
    admin = await make_user(db_session, role=UserRole.ADMIN)
    volunteer = await make_user(db_session, role=UserRole.VOLUNTEER, email="find-me@example.com")
    profile = await make_profile(db_session, volunteer)

    listed = await client.get(
        "/api/v1/admin/volunteers?city=mum&country=india&availability=weekends"
        "&skill_level=intermediate&search=find",
        headers=auth_headers(staff),
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    fetched = await client.get(f"/api/v1/admin/volunteers/{profile.id}", headers=auth_headers(staff))
    assert fetched.status_code == 200
    assert fetched.json()["city"] == "Mumbai"

    patched = await client.patch(
        f"/api/v1/admin/volunteers/{profile.id}",
        json={"city": "Pune", "bio": "Updated by admin."},
        headers=auth_headers(admin),
    )
    assert patched.status_code == 200
    assert patched.json()["city"] == "Pune"

    credited = await client.post(
        f"/api/v1/admin/volunteers/{profile.id}/credit-hours",
        json={"hours_to_add": 4, "note": "Training"},
        headers=auth_headers(staff),
    )
    assert credited.status_code == 200
    assert credited.json()["total_volunteer_hours"] == 4

    missing_id = uuid.uuid4()
    assert (await client.get(f"/api/v1/admin/volunteers/{missing_id}", headers=auth_headers(staff))).status_code == 404


@pytest.mark.asyncio
async def test_admin_opportunity_lifecycle_pairwise(
    db_session: AsyncSession,
) -> None:
    staff = await make_user(db_session, role=UserRole.STAFF, email="staff-flow@example.com")
    admin = await make_user(db_session, role=UserRole.ADMIN, email="admin-flow@example.com")

    created = await admin_endpoints.create_opportunity(
        OpportunityCreate(**opportunity_data(slots_total=1)),
        staff,
        db_session,
    )
    opportunity_id = created.id
    assert created.status == "draft"

    listed = await admin_endpoints.list_all_opportunities(
        db_session,
        opp_status=OpportunityStatus.DRAFT,
        category=OpportunityCategory.EDUCATION,
        city="mum",
        search="reading",
    )
    assert listed.total == 1

    fetched = await admin_endpoints.get_opportunity(opportunity_id, db_session)
    assert fetched.id == opportunity_id
    patched = await admin_endpoints.update_opportunity(
        opportunity_id,
        OpportunityUpdate(title="Updated Reading Program", slots_total=2),
        db_session,
    )
    assert patched.slots_total == 2

    published = await admin_endpoints.publish_opportunity(opportunity_id, db_session)
    assert published.status == "published"
    closed = await admin_endpoints.close_opportunity(opportunity_id, db_session)
    assert closed.status == "closed"
    reopened = await admin_endpoints.publish_opportunity(opportunity_id, db_session)
    assert reopened.status == "published"

    completed = await admin_endpoints.update_opportunity(
        opportunity_id,
        OpportunityUpdate(status=OpportunityStatus.COMPLETED),
        db_session,
    )
    assert completed.status == "completed"
    with pytest.raises(InvalidStateTransitionError):
        await admin_endpoints.update_opportunity(
            opportunity_id,
            OpportunityUpdate(title="Too Late"),
            db_session,
        )

    cancellable = await admin_endpoints.create_opportunity(
        OpportunityCreate(**opportunity_data(title="Cancellable Reading Program")),
        staff,
        db_session,
    )
    cancellable_id = cancellable.id
    cancelled = await admin_endpoints.cancel_opportunity(cancellable_id, db_session)
    assert cancelled.status == "cancelled"
    deleted = await admin_endpoints.delete_opportunity(cancellable_id, db_session)
    assert deleted.message == "Opportunity deleted successfully."
    with pytest.raises(OpportunityNotFoundError):
        await admin_endpoints.get_opportunity(uuid.uuid4(), db_session)

    assert admin.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_volunteer_application_and_staff_review_workflow(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    staff = await make_user(db_session, role=UserRole.STAFF)
    volunteer = await make_user(db_session, role=UserRole.VOLUNTEER)
    profile = await make_profile(db_session, volunteer)
    opportunity = await make_opportunity(db_session, staff)
    staff_headers = auth_headers(staff)
    volunteer_headers = auth_headers(volunteer)

    browsed = await client.get("/api/v1/volunteer/opportunities?city=mum&page_size=5", headers=volunteer_headers)
    assert browsed.status_code == 200
    assert browsed.json()["total"] == 1
    detail = await client.get(f"/api/v1/volunteer/opportunities/{opportunity.id}", headers=volunteer_headers)
    assert detail.status_code == 200

    submitted = await client.post(
        "/api/v1/volunteer/applications",
        json={"opportunity_id": str(opportunity.id), "cover_letter": "Hello", "motivation": "Help"},
        headers=volunteer_headers,
    )
    assert submitted.status_code == 201
    application_id = submitted.json()["id"]
    duplicate = await client.post(
        "/api/v1/volunteer/applications",
        json={"opportunity_id": str(opportunity.id)},
        headers=volunteer_headers,
    )
    assert duplicate.status_code == 409

    mine = await client.get("/api/v1/volunteer/applications?status=submitted", headers=volunteer_headers)
    assert mine.status_code == 200
    assert mine.json()["total"] == 1
    own_detail = await client.get(f"/api/v1/volunteer/applications/{application_id}", headers=volunteer_headers)
    assert own_detail.status_code == 200

    reviewed = await client.patch(
        f"/api/v1/admin/applications/{application_id}/review",
        json={"status": "accepted", "staff_notes": "Great fit."},
        headers=staff_headers,
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "accepted"

    by_opp = await client.get(
        f"/api/v1/admin/opportunities/{opportunity.id}/applications?status=accepted",
        headers=staff_headers,
    )
    assert by_opp.status_code == 200
    assert by_opp.json()["total"] == 1
    all_apps = await client.get(
        f"/api/v1/admin/applications?opportunity_id={opportunity.id}",
        headers=staff_headers,
    )
    assert all_apps.status_code == 200
    assert all_apps.json()["total"] == 1
    admin_detail = await client.get(f"/api/v1/admin/applications/{application_id}", headers=staff_headers)
    assert admin_detail.status_code == 200

    completed = await client.post(
        f"/api/v1/admin/applications/{application_id}/complete",
        json={"outcome": "outstanding", "hours_logged": 3, "rating": 5, "feedback": "Excellent."},
        headers=staff_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    withdraw_opp = await make_opportunity(
        db_session,
        staff,
        title="Withdrawable Reading Program",
        start_date=datetime.now(timezone.utc) + timedelta(days=20),
        end_date=datetime.now(timezone.utc) + timedelta(days=20, hours=2),
        application_deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )
    withdraw_app = await make_application(db_session, profile, withdraw_opp)
    withdrawn = await client.post(
        f"/api/v1/volunteer/applications/{withdraw_app.id}/withdraw",
        json={"reason": "Schedule conflict."},
        headers=volunteer_headers,
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"


@pytest.mark.asyncio
async def test_application_service_equivalence_classes(db_session: AsyncSession) -> None:
    service = ApplicationService(db_session)
    staff = await make_user(db_session, role=UserRole.STAFF)
    volunteer = await make_user(db_session)
    await make_profile(db_session, volunteer)
    no_profile_user = await make_user(db_session, email="no-profile@example.com")
    open_opp = await make_opportunity(db_session, staff)

    with pytest.raises(ProfileNotFoundError):
        await service.submit_application(no_profile_user, ApplicationCreate(opportunity_id=open_opp.id))

    draft_opp = await make_opportunity(db_session, staff, status=OpportunityStatus.DRAFT, title="Draft Program")
    with pytest.raises(BadRequestError):
        await service.submit_application(volunteer, ApplicationCreate(opportunity_id=draft_opp.id))

    past_deadline = await make_opportunity(
        db_session,
        staff,
        title="Past Deadline Program",
        start_date=datetime.now(timezone.utc) + timedelta(days=2),
        end_date=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
        application_deadline=datetime.now(timezone.utc) - timedelta(days=1),
    )
    with pytest.raises(BadRequestError):
        await service.submit_application(volunteer, ApplicationCreate(opportunity_id=past_deadline.id))

    full_opp = await make_opportunity(
        db_session,
        staff,
        title="Full Program",
        slots_total=1,
        slots_filled=1,
    )
    with pytest.raises(SlotCapacityExceededError):
        await service.submit_application(volunteer, ApplicationCreate(opportunity_id=full_opp.id))

    application = await service.submit_application(
        volunteer,
        ApplicationCreate(opportunity_id=open_opp.id, cover_letter="Hello", motivation="Help"),
    )
    await db_session.flush()
    with pytest.raises(DuplicateResourceError):
        await service.submit_application(volunteer, ApplicationCreate(opportunity_id=open_opp.id))

    listed = await db_session.execute(await service.list_my_applications(volunteer))
    assert listed.scalars().all()[0].id == application.id
    no_profile_list = await db_session.execute(await service.list_my_applications(no_profile_user))
    assert no_profile_list.scalars().all() == []
    assert (await service.get_my_application(volunteer, application.id)).id == application.id
    with pytest.raises(ApplicationNotFoundError):
        await service.get_my_application(no_profile_user, application.id)
    with pytest.raises(ApplicationNotFoundError):
        await service.get_application_by_id(uuid.uuid4())

    with pytest.raises(BadRequestError):
        await service.review_application(
            application.id,
            staff,
            review_request(ApplicationStatus.COMPLETED),
        )
    accepted = await service.review_application(
        application.id,
        staff,
        review_request(ApplicationStatus.ACCEPTED, staff_notes="Approved."),
    )
    assert accepted.status == ApplicationStatus.ACCEPTED
    assert accepted.opportunity.slots_filled == 1

    waitlisted = await service.review_application(
        application.id,
        staff,
        review_request(ApplicationStatus.WAITLISTED),
    )
    assert waitlisted.opportunity.slots_filled == 0
    with pytest.raises(InvalidStateTransitionError):
        await service.complete_application(
            application.id,
            staff,
            ApplicationCompleteRequest(outcome=ApplicationOutcome.INCOMPLETE, hours_logged=0),
        )

    accepted_again = await service.review_application(
        application.id,
        staff,
        review_request(ApplicationStatus.ACCEPTED),
    )
    completed = await service.complete_application(
        accepted_again.id,
        staff,
        ApplicationCompleteRequest(
            outcome=ApplicationOutcome.OUTSTANDING,
            hours_logged=2,
            rating=5,
            feedback="Great.",
        ),
    )
    assert completed.status == ApplicationStatus.COMPLETED
    assert completed.volunteer_profile.total_volunteer_hours == 2
    with pytest.raises(InvalidStateTransitionError):
        await service.review_application(
            completed.id,
            staff,
            review_request(ApplicationStatus.REJECTED, rejection_reason="No"),
        )

    filtered = await db_session.execute(
        await service.list_applications_for_opportunity(open_opp.id, status=ApplicationStatus.COMPLETED)
    )
    assert filtered.scalars().all()[0].id == application.id
    all_filtered = await db_session.execute(
        await service.list_all_applications(status=ApplicationStatus.COMPLETED, opportunity_id=open_opp.id)
    )
    assert all_filtered.scalars().all()[0].id == application.id


@pytest.mark.asyncio
async def test_user_service_account_lifecycle_and_errors(db_session: AsyncSession) -> None:
    service = UserService(db_session)

    registered, raw_verify = await service.register_volunteer(
        RegisterRequest(
            email="MixedCase@example.com",
            password=PASSWORD,
            confirm_password=PASSWORD,
            first_name="Mixed",
            last_name="Case",
        )
    )
    assert registered.email == "mixedcase@example.com"
    with pytest.raises(EmailNotVerifiedError):
        await service.authenticate("mixedcase@example.com", PASSWORD)
    with pytest.raises(DuplicateResourceError):
        await service.register_volunteer(
            RegisterRequest(
                email="mixedcase@example.com",
                password=PASSWORD,
                confirm_password=PASSWORD,
                first_name="M",
                last_name="C",
            )
        )

    verified = await service.verify_email(raw_verify)
    assert verified.status == UserStatus.ACTIVE
    with pytest.raises(ExpiredTokenError):
        await service.verify_email(raw_verify)
    with pytest.raises(AuthenticationError):
        await service.authenticate("mixedcase@example.com", "WrongPass123!")
    assert (await service.authenticate("mixedcase@example.com", PASSWORD)).id == registered.id

    refresh = create_refresh_token(subject=registered.id, role=registered.role)
    await service.store_refresh_token_hash(registered, refresh)
    assert (await service.validate_refresh_token(registered.id, refresh)).id == registered.id
    with pytest.raises(AuthenticationError):
        await service.validate_refresh_token(registered.id, "bad-token")
    await service.revoke_refresh_token(registered)
    with pytest.raises(AuthenticationError):
        await service.validate_refresh_token(registered.id, refresh)

    assert await service.initiate_password_reset("unknown@example.com") == (None, None)
    reset_user, reset_token = await service.initiate_password_reset("mixedcase@example.com")
    assert reset_user is not None
    assert reset_token is not None
    with pytest.raises(ExpiredTokenError):
        await service.complete_password_reset("not-a-real-reset-token", "NewSecurePassword123!")

    expired_token, expired_hash = generate_password_reset_token()
    registered.password_reset_token = expired_hash
    registered.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.flush()
    with pytest.raises(ExpiredTokenError):
        await service.complete_password_reset(expired_token, "NewSecurePassword123!")

    _, fresh_token = await service.initiate_password_reset("mixedcase@example.com")
    reset = await service.complete_password_reset(fresh_token, "NewSecurePassword123!")
    assert reset.refresh_token_hash is None
    assert (await service.authenticate("mixedcase@example.com", "NewSecurePassword123!")).id == registered.id

    staff = await service.admin_create_user(
        AdminCreateUserRequest(
            email="staff-created@example.com",
            password=PASSWORD,
            first_name="Staff",
            last_name="Created",
            role=UserRole.STAFF,
        )
    )
    with pytest.raises(DuplicateResourceError):
        await service.admin_create_user(
            AdminCreateUserRequest(
                email="staff-created@example.com",
                password=PASSWORD,
                first_name="Staff",
                last_name="Created",
                role=UserRole.STAFF,
            )
        )
    listed = await db_session.execute(await service.list_users(role=UserRole.STAFF, search="created"))
    assert listed.scalars().all()[0].id == staff.id
    assert (await service.get_user_by_id(staff.id)).id == staff.id
    with pytest.raises(UserNotFoundError):
        await service.get_user_by_id(uuid.uuid4())

    updated = await service.admin_update_user(
        staff.id,
        AdminUpdateUserRequest(role=UserRole.ADMIN, status=UserStatus.SUSPENDED, first_name="Updated"),
    )
    assert updated.role == UserRole.ADMIN
    await service.soft_delete_user(staff.id)
    assert staff.status == UserStatus.DEACTIVATED


@pytest.mark.asyncio
async def test_volunteer_service_equivalence_and_boundaries(db_session: AsyncSession) -> None:
    service = VolunteerService(db_session)
    volunteer = await make_user(db_session)

    profile = await service.create_profile(
        volunteer,
        VolunteerProfileCreate(
            phone_number="+1 (555) 123-4567",
            date_of_birth=date(1990, 1, 1),
            bio="Original bio.",
            profile_photo_url="https://example.com/photo.png",
            city="Mumbai",
            country="India",
            skills=[" Teaching ", "", "First Aid"],
            languages_spoken=[" English ", "Hindi"],
            availability=AvailabilityType.WEEKENDS,
            skill_level=SkillLevel.INTERMEDIATE,
            hours_per_week=1,
        ),
    )
    assert profile.phone_number == "+15551234567"
    assert profile.skills == ["Teaching", "First Aid"]
    with pytest.raises(DuplicateResourceError):
        await service.create_profile(volunteer, VolunteerProfileCreate())

    updated = await service.update_my_profile(
        volunteer,
        VolunteerProfileUpdate(bio="Updated bio.", profile_photo_url="https://example.com/new.png"),
    )
    assert updated.bio == "Updated bio."
    assert updated.city == "Mumbai"

    assert (await service.get_my_profile(volunteer)).id == profile.id
    assert (await service.get_profile_by_id(profile.id)).id == profile.id
    assert (await service.get_profile_by_user_id(volunteer.id)).id == profile.id

    query = await service.list_volunteers(
        city="mum",
        country="india",
        availability=AvailabilityType.WEEKENDS,
        skill_level=SkillLevel.INTERMEDIATE,
        search=volunteer.email.split("@")[0],
    )
    result = await db_session.execute(query)
    assert result.scalars().all()[0].id == profile.id

    credited = await service.credit_hours(profile.id, 5)
    assert credited.total_volunteer_hours == 5
    admin_updated = await service.admin_update_profile(profile.id, VolunteerProfileUpdate(city="Pune"))
    assert admin_updated.city == "Pune"

    other = await make_user(db_session, email="no-volunteer-profile@example.com")
    with pytest.raises(ProfileNotFoundError):
        await service.get_my_profile(other)
    with pytest.raises(ProfileNotFoundError):
        await service.get_profile_by_id(uuid.uuid4())
    with pytest.raises(ProfileNotFoundError):
        await service.get_profile_by_user_id(uuid.uuid4())

    invalid_profiles = [
        {"phone_number": "bad"},
        {"date_of_birth": date.today() + timedelta(days=1)},
        {"hours_per_week": 0},
        {"hours_per_week": 169},
    ]
    for payload in invalid_profiles:
        with pytest.raises(ValidationError):
            VolunteerProfileCreate(**payload)


@pytest.mark.asyncio
async def test_opportunity_service_state_matrix_and_filters(db_session: AsyncSession) -> None:
    service = OpportunityService(db_session)
    staff = await make_user(db_session, role=UserRole.STAFF)
    payload = OpportunityCreate(**opportunity_data())
    opportunity = await service.create_opportunity(payload, staff)
    assert opportunity.status == OpportunityStatus.DRAFT
    assert opportunity.slots_available == 2
    assert opportunity.is_full is False

    published = await service.publish_opportunity(opportunity.id)
    assert published.status == OpportunityStatus.PUBLISHED
    with pytest.raises(InvalidStateTransitionError):
        await service.publish_opportunity(opportunity.id)

    public_query = await service.list_opportunities(
        category=OpportunityCategory.EDUCATION,
        city="mum",
        country="india",
        is_remote=False,
        search="reading",
    )
    public_result = await db_session.execute(public_query)
    assert public_result.scalars().all()[0].id == opportunity.id

    admin_query = await service.list_opportunities(
        status=OpportunityStatus.PUBLISHED,
        include_drafts=True,
    )
    admin_result = await db_session.execute(admin_query)
    assert admin_result.scalars().all()[0].id == opportunity.id

    closed = await service.close_opportunity(opportunity.id)
    assert closed.status == OpportunityStatus.CLOSED
    reopened = await service.publish_opportunity(opportunity.id)
    assert reopened.status == OpportunityStatus.PUBLISHED
    completed = await service.update_opportunity(
        opportunity.id,
        OpportunityUpdate(status=OpportunityStatus.COMPLETED),
    )
    assert completed.status == OpportunityStatus.COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        await service.update_opportunity(opportunity.id, OpportunityUpdate(title="Blocked"))
    with pytest.raises(InvalidStateTransitionError):
        await service.close_opportunity(opportunity.id)

    cancellable = await service.create_opportunity(
        OpportunityCreate(**opportunity_data(title="Cancellable Program")),
        staff,
    )
    cancelled = await service.cancel_opportunity(cancellable.id)
    assert cancelled.status == OpportunityStatus.CANCELLED
    with pytest.raises(InvalidStateTransitionError):
        await service.cancel_opportunity(cancelled.id)
    with pytest.raises(OpportunityNotFoundError):
        await service.get_opportunity(uuid.uuid4())

    published_for_delete = await service.create_opportunity(
        OpportunityCreate(**opportunity_data(title="Published Delete Blocker")),
        staff,
    )
    await service.publish_opportunity(published_for_delete.id)
    with pytest.raises(InvalidStateTransitionError):
        await service.soft_delete_opportunity(published_for_delete.id)

    draft_for_delete = await service.create_opportunity(
        OpportunityCreate(**opportunity_data(title="Draft Delete Target")),
        staff,
    )
    await service.soft_delete_opportunity(draft_for_delete.id)
    with pytest.raises(OpportunityNotFoundError):
        await service.get_opportunity(draft_for_delete.id)


@pytest.mark.asyncio
async def test_schema_security_pagination_and_model_boundaries(
    db_session: AsyncSession,
) -> None:
    naive_start = datetime.utcnow() + timedelta(days=3)
    created = OpportunityCreate(
        title="Boundary Opportunity",
        description="Description long enough for validation.",
        category=OpportunityCategory.OTHER,
        start_date=naive_start,
        end_date=naive_start + timedelta(hours=1),
        application_deadline=naive_start - timedelta(days=1),
        slots_total=1,
    )
    assert created.start_date.tzinfo == timezone.utc

    invalid_schema_inputs = [
        lambda: OpportunityCreate(
            **opportunity_data(
                title="Bad Date Program",
                end_date=datetime.now(timezone.utc) - timedelta(days=1),
            )
        ),
        lambda: ApplicationReviewRequest(status=ApplicationStatus.REJECTED),
        lambda: ResetPasswordRequest(token="short", new_password=PASSWORD, confirm_password=PASSWORD),
        lambda: ResetPasswordRequest(token="long-enough", new_password=PASSWORD, confirm_password="Different123!"),
        lambda: ChangePasswordRequest(
            current_password=PASSWORD,
            new_password=PASSWORD,
            confirm_password="Different123!",
        ),
        lambda: AdminCreateUserRequest(
            email="super@example.com",
            password=PASSWORD,
            first_name="Super",
            last_name="Admin",
            role=UserRole.SUPER_ADMIN,
        ),
        lambda: AdminUpdateUserRequest(role=UserRole.SUPER_ADMIN),
    ]
    for factory in invalid_schema_inputs:
        with pytest.raises(ValidationError):
            factory()

    volunteer = await make_user(db_session, role=UserRole.VOLUNTEER)
    admin = await make_user(db_session, role=UserRole.ADMIN)
    assert volunteer.full_name.endswith("User")
    assert volunteer.is_active is True
    assert volunteer.is_admin is False
    assert admin.is_admin is True

    query = select(User).where(User.id == uuid.uuid4())
    items, total = await paginate(db_session, query, page=1, page_size=10)
    assert items == []
    assert total == 0
    assert build_paginated_response(items=[], total=0, page=1, page_size=0)["pages"] == 0
    assert PaginationParams(page=2, page_size=5).offset == 5
    assert PaginationParams(page=2, page_size=5).limit == 5
    assert PaginatedResponse.from_items(items=[1], total=1, page=1, page_size=10).pages == 1

    access = create_access_token(subject=volunteer.id, role=volunteer.role)
    refresh = create_refresh_token(subject=volunteer.id, role=volunteer.role)
    assert decode_token(access).type == "access"
    assert decode_token(refresh).type == "refresh"
    with pytest.raises(Exception):
        decode_token("not-a-jwt")

    app_row = Application(
        volunteer_profile_id=uuid.uuid4(),
        opportunity_id=uuid.uuid4(),
        status=ApplicationStatus.SUBMITTED,
    )
    assert "Application" in repr(app_row)
    opp_row = Opportunity(
        **opportunity_data(),
        status=OpportunityStatus.DRAFT,
        slots_filled=0,
        created_by_id=admin.id,
    )
    assert "Opportunity" in repr(opp_row)
    assert "User" in repr(volunteer)


@pytest.mark.asyncio
async def test_infrastructure_endpoints_and_exception_handlers(
    client: AsyncClient,
) -> None:
    assert (await client.get("/")).status_code == 200
    health = await client.get("/health")
    assert health.status_code in {200, 503}

    assert await database.check_db_connection() is True
    await database.create_all_tables()
    await database.drop_all_tables()
    await database.create_all_tables()

    async with lifespan(app):
        pass

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/handled",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("testclient", 50000),
        }
    )
    domain_response = await app.exception_handlers[VIMSBaseException](request, BadRequestError("bad"))
    assert domain_response.status_code == 400

    integrity_response = await app.exception_handlers[IntegrityError](
        request,
        IntegrityError("insert", {}, Exception("UNIQUE constraint failed")),
    )
    assert integrity_response.status_code == 409

    sqlalchemy_response = await app.exception_handlers[SQLAlchemyError](
        request,
        SQLAlchemyError("database unavailable"),
    )
    assert sqlalchemy_response.status_code == 503

    generic_response = await app.exception_handlers[Exception](request, RuntimeError("boom"))
    assert generic_response.status_code == 500
