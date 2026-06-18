from app.schemas.auth import (
    AccessTokenResponse,
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserListResponse,
    UserResponse,
)
from app.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    MessageResponse,
    PaginatedResponse,
    PaginationParams,
)
from app.schemas.opportunity import (
    ApplicationCompleteRequest,
    ApplicationCreate,
    ApplicationResponse,
    ApplicationReviewRequest,
    ApplicationSummaryResponse,
    ApplicationWithdrawRequest,
    OpportunityCreate,
    OpportunityResponse,
    OpportunitySummaryResponse,
    OpportunityUpdate,
)
from app.schemas.volunteer import (
    AdminVolunteerHoursUpdate,
    VolunteerProfileCreate,
    VolunteerProfileResponse,
    VolunteerProfileUpdate,
    VolunteerSummaryResponse,
)

__all__ = [
    # auth
    "RegisterRequest",
    "AdminCreateUserRequest",
    "LoginRequest",
    "TokenResponse",
    "RefreshTokenRequest",
    "AccessTokenResponse",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "ChangePasswordRequest",
    "UserResponse",
    "UserListResponse",
    "AdminUpdateUserRequest",
    # volunteer
    "VolunteerProfileCreate",
    "VolunteerProfileUpdate",
    "VolunteerProfileResponse",
    "VolunteerSummaryResponse",
    "AdminVolunteerHoursUpdate",
    # opportunity
    "OpportunityCreate",
    "OpportunityUpdate",
    "OpportunityResponse",
    "OpportunitySummaryResponse",
    "ApplicationCreate",
    "ApplicationReviewRequest",
    "ApplicationCompleteRequest",
    "ApplicationWithdrawRequest",
    "ApplicationResponse",
    "ApplicationSummaryResponse",
    # common
    "PaginationParams",
    "PaginatedResponse",
    "MessageResponse",
    "ErrorDetail",
    "ErrorResponse",
]