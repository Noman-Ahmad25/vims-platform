from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, require_roles
from app.models.enums import (
    ApplicationStatus,
    AvailabilityType,
    OpportunityCategory,
    OpportunityStatus,
    SkillLevel,
    UserRole,
    UserStatus,
)
from app.models.user import User
from app.schemas.auth import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    UserListResponse,
    UserResponse,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.opportunity import (
    ApplicationCompleteRequest,
    ApplicationResponse,
    ApplicationReviewRequest,
    OpportunityCreate,
    OpportunityResponse,
    OpportunitySummaryResponse,
    OpportunityUpdate,
)
from app.schemas.volunteer import (
    AdminVolunteerHoursUpdate,
    VolunteerProfileResponse,
    VolunteerProfileUpdate,
    VolunteerSummaryResponse,
)
from app.services.application_service import ApplicationService
from app.services.opportunity_service import OpportunityService
from app.services.user_service import UserService
from app.services.volunteer_service import VolunteerService
from app.utils.pagination import build_paginated_response, paginate

# ── Sub-routers ────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/admin", tags=["Admin"])

_staff_dep = Depends(require_roles(UserRole.STAFF, UserRole.ADMIN, UserRole.SUPER_ADMIN))
_admin_dep = Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))

# ═══════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT  (admin only)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/users",
    response_model=PaginatedResponse[UserListResponse],
    dependencies=[_admin_dep],
    summary="[Admin] List all platform users",
)
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[UserRole | None, Query()] = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[UserListResponse]:
    svc = UserService(db)
    stmt = await svc.list_users(role=role, status=user_status, search=search)
    items, total = await paginate(db, stmt, page=page, page_size=page_size)
    return PaginatedResponse[UserListResponse](
        **build_paginated_response(
            items=[
                UserListResponse(
                    id=str(u.id),
                    email=u.email,
                    full_name=u.full_name,
                    role=u.role,
                    status=u.status,
                    created_at=str(u.created_at),
                )
                for u in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin_dep],
    summary="[Admin] Create a staff or admin account",
)
async def create_user(
    payload: AdminCreateUserRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    svc = UserService(db)
    user = await svc.admin_create_user(payload)
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        is_email_verified=user.is_email_verified,
        created_at=str(user.created_at),
        updated_at=str(user.updated_at),
    )


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[_admin_dep],
    summary="[Admin] Get a user by ID",
)
async def get_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    svc = UserService(db)
    user = await svc.get_user_by_id(user_id)
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        is_email_verified=user.is_email_verified,
        created_at=str(user.created_at),
        updated_at=str(user.updated_at),
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[_admin_dep],
    summary="[Admin] Update a user's role or status",
)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUpdateUserRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    svc = UserService(db)
    user = await svc.admin_update_user(user_id, payload)
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        is_email_verified=user.is_email_verified,
        created_at=str(user.created_at),
        updated_at=str(user.updated_at),
    )


@router.delete(
    "/users/{user_id}",
    response_model=MessageResponse,
    dependencies=[_admin_dep],
    summary="[Admin] Soft-delete a user account",
)
async def delete_user(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    from fastapi import HTTPException
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account via the admin endpoint.",
        )
    svc = UserService(db)
    await svc.soft_delete_user(user_id)
    return MessageResponse(message="User account deactivated successfully.")


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUNTEER MANAGEMENT  (staff + admin)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/volunteers",
    response_model=PaginatedResponse[VolunteerSummaryResponse],
    dependencies=[_staff_dep],
    summary="[Staff] List and search volunteer profiles",
)
async def list_volunteers(
    db: Annotated[AsyncSession, Depends(get_db)],
    city: Annotated[str | None, Query(max_length=100)] = None,
    country: Annotated[str | None, Query(max_length=100)] = None,
    skill: Annotated[str | None, Query(max_length=100)] = None,
    availability: Annotated[AvailabilityType | None, Query()] = None,
    skill_level: Annotated[SkillLevel | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[VolunteerSummaryResponse]:
    svc = VolunteerService(db)
    stmt = await svc.list_volunteers(
        city=city,
        country=country,
        skill=skill,
        availability=availability,
        skill_level=skill_level,
        search=search,
    )
    items, total = await paginate(db, stmt, page=page, page_size=page_size)
    return PaginatedResponse[VolunteerSummaryResponse](
        **build_paginated_response(
            items=[
                VolunteerSummaryResponse(
                    id=str(p.id),
                    user_id=str(p.user_id),
                    full_name=p.user.full_name,
                    email=p.user.email,
                    city=p.city,
                    country=p.country,
                    skills=p.skills,
                    total_volunteer_hours=p.total_volunteer_hours,
                    availability=p.availability,
                )
                for p in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get(
    "/volunteers/{profile_id}",
    response_model=VolunteerProfileResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Get a volunteer profile by profile ID",
)
async def get_volunteer_profile(
    profile_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VolunteerProfileResponse:
    svc = VolunteerService(db)
    profile = await svc.get_profile_by_id(profile_id)
    return VolunteerProfileResponse.model_validate(profile)


@router.patch(
    "/volunteers/{profile_id}",
    response_model=VolunteerProfileResponse,
    dependencies=[_admin_dep],
    summary="[Admin] Update a volunteer profile",
)
async def admin_update_volunteer_profile(
    profile_id: uuid.UUID,
    payload: VolunteerProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VolunteerProfileResponse:
    svc = VolunteerService(db)
    profile = await svc.admin_update_profile(profile_id, payload)
    return VolunteerProfileResponse.model_validate(profile)


@router.post(
    "/volunteers/{profile_id}/credit-hours",
    response_model=VolunteerProfileResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Manually credit volunteer hours to a profile",
)
async def credit_volunteer_hours(
    profile_id: uuid.UUID,
    payload: AdminVolunteerHoursUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VolunteerProfileResponse:
    svc = VolunteerService(db)
    profile = await svc.credit_hours(profile_id, payload.hours_to_add)
    return VolunteerProfileResponse.model_validate(profile)


# ═══════════════════════════════════════════════════════════════════════════════
# OPPORTUNITY MANAGEMENT  (staff + admin)
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/opportunities",
    response_model=OpportunityResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_staff_dep],
    summary="[Staff] Create a new opportunity (starts as DRAFT)",
)
async def create_opportunity(
    payload: OpportunityCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.create_opportunity(payload, created_by=current_user)
    return OpportunityResponse.model_validate(opp)


@router.get(
    "/opportunities",
    response_model=PaginatedResponse[OpportunitySummaryResponse],
    dependencies=[_staff_dep],
    summary="[Staff] List all opportunities (all statuses)",
)
async def list_all_opportunities(
    db: Annotated[AsyncSession, Depends(get_db)],
    opp_status: Annotated[OpportunityStatus | None, Query(alias="status")] = None,
    category: Annotated[OpportunityCategory | None, Query()] = None,
    city: Annotated[str | None, Query(max_length=100)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[OpportunitySummaryResponse]:
    svc = OpportunityService(db)
    stmt = await svc.list_opportunities(
        status=opp_status,
        category=category,
        city=city,
        search=search,
        include_drafts=True,
    )
    items, total = await paginate(db, stmt, page=page, page_size=page_size)
    return PaginatedResponse[OpportunitySummaryResponse](
        **build_paginated_response(
            items=[
                OpportunitySummaryResponse(
                    id=o.id,
                    title=o.title,
                    category=o.category,
                    status=o.status,
                    city=o.city,
                    country=o.country,
                    start_date=o.start_date,
                    slots_available=o.slots_available,
                    is_remote=o.is_remote,
                )
                for o in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get(
    "/opportunities/{opportunity_id}",
    response_model=OpportunityResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Get full details of any opportunity",
)
async def get_opportunity(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.get_opportunity(opportunity_id)
    return OpportunityResponse.model_validate(opp)


@router.patch(
    "/opportunities/{opportunity_id}",
    response_model=OpportunityResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Update opportunity fields or status",
)
async def update_opportunity(
    opportunity_id: uuid.UUID,
    payload: OpportunityUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.update_opportunity(opportunity_id, payload)
    return OpportunityResponse.model_validate(opp)


@router.post(
    "/opportunities/{opportunity_id}/publish",
    response_model=OpportunityResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Publish a DRAFT opportunity",
)
async def publish_opportunity(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.publish_opportunity(opportunity_id)
    return OpportunityResponse.model_validate(opp)


@router.post(
    "/opportunities/{opportunity_id}/close",
    response_model=OpportunityResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Close a PUBLISHED opportunity",
)
async def close_opportunity(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.close_opportunity(opportunity_id)
    return OpportunityResponse.model_validate(opp)


@router.post(
    "/opportunities/{opportunity_id}/cancel",
    response_model=OpportunityResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Cancel an opportunity",
)
async def cancel_opportunity(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.cancel_opportunity(opportunity_id)
    return OpportunityResponse.model_validate(opp)


@router.delete(
    "/opportunities/{opportunity_id}",
    response_model=MessageResponse,
    dependencies=[_admin_dep],
    summary="[Admin] Soft-delete a non-published opportunity",
)
async def delete_opportunity(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = OpportunityService(db)
    await svc.soft_delete_opportunity(opportunity_id)
    return MessageResponse(message="Opportunity deleted successfully.")


# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATION MANAGEMENT  (staff + admin)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/opportunities/{opportunity_id}/applications",
    response_model=PaginatedResponse[ApplicationResponse],
    dependencies=[_staff_dep],
    summary="[Staff] List applications for a specific opportunity",
)
async def list_opportunity_applications(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    app_status: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ApplicationResponse]:
    svc = ApplicationService(db)
    stmt = await svc.list_applications_for_opportunity(
        opportunity_id, status=app_status
    )
    items, total = await paginate(db, stmt, page=page, page_size=page_size)
    return PaginatedResponse[ApplicationResponse](
        **build_paginated_response(
            items=[ApplicationResponse.model_validate(a) for a in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get(
    "/applications",
    response_model=PaginatedResponse[ApplicationResponse],
    dependencies=[_staff_dep],
    summary="[Staff] List all applications across all opportunities",
)
async def list_all_applications(
    db: Annotated[AsyncSession, Depends(get_db)],
    app_status: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ApplicationResponse]:
    svc = ApplicationService(db)
    stmt = await svc.list_all_applications(
        status=app_status, opportunity_id=opportunity_id
    )
    items, total = await paginate(db, stmt, page=page, page_size=page_size)
    return PaginatedResponse[ApplicationResponse](
        **build_paginated_response(
            items=[ApplicationResponse.model_validate(a) for a in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Get a single application by ID",
)
async def get_application(
    application_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationResponse:
    svc = ApplicationService(db)
    app = await svc.get_application_by_id(application_id)
    return ApplicationResponse.model_validate(app)


@router.patch(
    "/applications/{application_id}/review",
    response_model=ApplicationResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Accept, reject, waitlist, or mark under-review",
)
async def review_application(
    application_id: uuid.UUID,
    payload: ApplicationReviewRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationResponse:
    svc = ApplicationService(db)
    app = await svc.review_application(application_id, current_user, payload)
    return ApplicationResponse.model_validate(app)


@router.post(
    "/applications/{application_id}/complete",
    response_model=ApplicationResponse,
    dependencies=[_staff_dep],
    summary="[Staff] Mark an ACCEPTED application as completed and log hours",
)
async def complete_application(
    application_id: uuid.UUID,
    payload: ApplicationCompleteRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationResponse:
    svc = ApplicationService(db)
    app = await svc.complete_application(application_id, current_user, payload)
    return ApplicationResponse.model_validate(app)