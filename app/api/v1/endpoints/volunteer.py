from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, require_roles
from app.models.enums import (
    ApplicationStatus,
    OpportunityCategory,
    OpportunityStatus,
    UserRole,
)
from app.models.user import User
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.opportunity import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationSummaryResponse,
    ApplicationWithdrawRequest,
    OpportunityResponse,
    OpportunitySummaryResponse,
)
from app.schemas.volunteer import VolunteerProfileCreate, VolunteerProfileResponse, VolunteerProfileUpdate
from app.services.application_service import ApplicationService
from app.services.opportunity_service import OpportunityService
from app.services.volunteer_service import VolunteerService
from app.utils.pagination import build_paginated_response, paginate

router = APIRouter(
    prefix="/volunteer",
    tags=["Volunteer"],
    dependencies=[Depends(require_roles(UserRole.VOLUNTEER, UserRole.STAFF, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
)

# ── Profile ────────────────────────────────────────────────────────────────────


@router.post(
    "/profile",
    response_model=VolunteerProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create my volunteer profile",
)
async def create_my_profile(
    payload: VolunteerProfileCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VolunteerProfileResponse:
    svc = VolunteerService(db)
    profile = await svc.create_profile(current_user, payload)
    return VolunteerProfileResponse.model_validate(profile)


@router.get(
    "/profile",
    response_model=VolunteerProfileResponse,
    summary="Get my volunteer profile",
)
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VolunteerProfileResponse:
    svc = VolunteerService(db)
    profile = await svc.get_my_profile(current_user)
    return VolunteerProfileResponse.model_validate(profile)


@router.patch(
    "/profile",
    response_model=VolunteerProfileResponse,
    summary="Update my volunteer profile",
)
async def update_my_profile(
    payload: VolunteerProfileUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VolunteerProfileResponse:
    svc = VolunteerService(db)
    profile = await svc.update_my_profile(current_user, payload)
    return VolunteerProfileResponse.model_validate(profile)


# ── Browse opportunities ───────────────────────────────────────────────────────


@router.get(
    "/opportunities",
    response_model=PaginatedResponse[OpportunitySummaryResponse],
    summary="Browse published volunteer opportunities",
)
async def list_opportunities(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Annotated[OpportunityCategory | None, Query()] = None,
    city: Annotated[str | None, Query(max_length=100)] = None,
    country: Annotated[str | None, Query(max_length=100)] = None,
    is_remote: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[OpportunitySummaryResponse]:
    svc = OpportunityService(db)
    stmt = await svc.list_opportunities(
        category=category,
        city=city,
        country=country,
        is_remote=is_remote,
        search=search,
        include_drafts=False,
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
    summary="Get full details of a published opportunity",
)
async def get_opportunity(
    opportunity_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpportunityResponse:
    svc = OpportunityService(db)
    opp = await svc.get_opportunity(opportunity_id)
    return OpportunityResponse.model_validate(opp)


# ── Applications ───────────────────────────────────────────────────────────────


@router.post(
    "/applications",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an application for an opportunity",
)
async def submit_application(
    payload: ApplicationCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationResponse:
    svc = ApplicationService(db)
    app = await svc.submit_application(current_user, payload)
    return ApplicationResponse.model_validate(app)


@router.get(
    "/applications",
    response_model=PaginatedResponse[ApplicationSummaryResponse],
    summary="List my submitted applications",
)
async def list_my_applications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ApplicationSummaryResponse]:
    svc = ApplicationService(db)
    stmt = await svc.list_my_applications(current_user)

    if status_filter is not None:
        from sqlalchemy import select
        from app.models.opportunity import Application
        stmt = stmt.where(Application.status == status_filter)

    items, total = await paginate(db, stmt, page=page, page_size=page_size)

    return PaginatedResponse[ApplicationSummaryResponse](
        **build_paginated_response(
            items=[
                ApplicationSummaryResponse(
                    id=a.id,
                    opportunity_id=a.opportunity_id,
                    opportunity_title=a.opportunity.title if a.opportunity else "",
                    status=a.status,
                    created_at=a.created_at,
                )
                for a in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationResponse,
    summary="Get details of one of my applications",
)
async def get_my_application(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationResponse:
    svc = ApplicationService(db)
    app = await svc.get_my_application(current_user, application_id)
    return ApplicationResponse.model_validate(app)


@router.post(
    "/applications/{application_id}/withdraw",
    response_model=ApplicationResponse,
    summary="Withdraw one of my pending applications",
)
async def withdraw_application(
    application_id: uuid.UUID,
    payload: ApplicationWithdrawRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationResponse:
    svc = ApplicationService(db)
    app = await svc.withdraw_application(current_user, application_id, payload.reason)
    return ApplicationResponse.model_validate(app)