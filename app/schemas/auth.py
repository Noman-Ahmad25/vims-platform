from __future__ import annotations

import re

from pydantic import EmailStr, Field, field_validator, model_validator

from app.models.enums import UserRole, UserStatus
from app.schemas.common import AppBaseModel, UUIDSchema

# ── Password rules ─────────────────────────────────────────────────────────────

_PASSWORD_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&^#\-_=+])[A-Za-z\d@$!%*?&^#\-_=+]{8,128}$"
)


def _validate_password(v: str) -> str:
    if not _PASSWORD_RE.match(v):
        raise ValueError(
            "Password must be 8–128 characters and contain at least one uppercase "
            "letter, one lowercase letter, one digit, and one special character."
        )
    return v


# ── Registration ───────────────────────────────────────────────────────────────


class RegisterRequest(AppBaseModel):
    """Payload for public user registration (always creates a VOLUNTEER account)."""

    email: EmailStr = Field(..., description="Unique email address.")
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "RegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class AdminCreateUserRequest(AppBaseModel):
    """Admin-only endpoint to create staff / admin accounts."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: UserRole = UserRole.STAFF

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("role")
    @classmethod
    def no_self_super_admin(cls, v: UserRole) -> UserRole:
        if v == UserRole.SUPER_ADMIN:
            raise ValueError("Cannot create SUPER_ADMIN via API.")
        return v


# ── Login / Token ──────────────────────────────────────────────────────────────


class LoginRequest(AppBaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(AppBaseModel):
    """Returned after a successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access-token TTL in seconds.")


class RefreshTokenRequest(AppBaseModel):
    refresh_token: str


class AccessTokenResponse(AppBaseModel):
    """Returned when rotating an access token via refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Password management ────────────────────────────────────────────────────────


class ForgotPasswordRequest(AppBaseModel):
    email: EmailStr


class ResetPasswordRequest(AppBaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class ChangePasswordRequest(AppBaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


# ── Current-user response ──────────────────────────────────────────────────────


class UserResponse(UUIDSchema):
    """Safe user representation — never exposes hashed_password."""

    email: str
    first_name: str
    last_name: str
    full_name: str
    role: UserRole
    status: UserStatus
    is_email_verified: bool
    created_at: str
    updated_at: str


class UserListResponse(AppBaseModel):
    """Slim representation for admin list views."""

    id: str
    email: str
    full_name: str
    role: UserRole
    status: UserStatus
    created_at: str


class AdminUpdateUserRequest(AppBaseModel):
    """Admin can update role and status of any user."""

    role: UserRole | None = None
    status: UserStatus | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("role")
    @classmethod
    def no_super_admin_grant(cls, v: UserRole | None) -> UserRole | None:
        if v == UserRole.SUPER_ADMIN:
            raise ValueError("Cannot promote to SUPER_ADMIN via API.")
        return v