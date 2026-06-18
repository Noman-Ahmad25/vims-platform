from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
    get_current_user,
)
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import MessageResponse
from app.services.user_service import UserService
from app.core.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Register ───────────────────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new volunteer account",
)
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    user, raw_token = await svc.register_volunteer(payload)
    # In production this raw_token would be emailed. We surface it here only
    # so that development / integration tests can complete the flow without SMTP.
    if settings.ENVIRONMENT == "development":
        return MessageResponse(
            message="Registration successful. Please verify your email.",
            detail={"email_verification_token": raw_token, "user_id": str(user.id)},
        )
    return MessageResponse(
        message="Registration successful. A verification link has been sent to your email."
    )


# ── Verify email ───────────────────────────────────────────────────────────────


@router.get(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email address using the token sent by email",
)
async def verify_email(
    token: Annotated[str, Query(min_length=10, description="Email verification token")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    await svc.verify_email(token)
    return MessageResponse(message="Email verified successfully. You can now log in.")


# ── Resend verification ────────────────────────────────────────────────────────


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    summary="Resend the email verification link",
)
async def resend_verification(
    payload: ForgotPasswordRequest,  # reuses {email} body
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    user, raw_token = await svc.resend_verification_email(payload.email)
    if settings.ENVIRONMENT == "development":
        return MessageResponse(
            message="Verification email resent.",
            detail={"email_verification_token": raw_token},
        )
    return MessageResponse(
        message="If that email is registered and unverified, a new link has been sent."
    )


# ── Login (JSON body) ──────────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password (JSON)",
)
async def login(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    svc = UserService(db)
    user = await svc.authenticate(payload.email, payload.password)

    access_token = create_access_token(subject=user.id, role=user.role)
    refresh_token = create_refresh_token(subject=user.id, role=user.role)
    await svc.store_refresh_token_hash(user, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Login (form — satisfies OAuth2PasswordBearer Swagger UI) ──────────────────


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Log in via OAuth2 form (Swagger UI compatible)",
    include_in_schema=True,
)
async def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    svc = UserService(db)
    user = await svc.authenticate(form_data.username, form_data.password)

    access_token = create_access_token(subject=user.id, role=user.role)
    refresh_token = create_refresh_token(subject=user.id, role=user.role)
    await svc.store_refresh_token_hash(user, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Refresh access token ───────────────────────────────────────────────────────


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Exchange a refresh token for a new access token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccessTokenResponse:
    import uuid as _uuid

    token_data = decode_token(payload.refresh_token)
    if token_data.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. A refresh token is required.",
        )

    svc = UserService(db)
    user = await svc.validate_refresh_token(
        _uuid.UUID(token_data.sub), payload.refresh_token
    )
    access_token = create_access_token(subject=user.id, role=user.role)
    return AccessTokenResponse(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Logout ─────────────────────────────────────────────────────────────────────


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Invalidate the current refresh token (logout)",
)
async def logout(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    await svc.revoke_refresh_token(current_user)
    return MessageResponse(message="Logged out successfully.")


# ── Forgot password ────────────────────────────────────────────────────────────


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset email",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    user, raw_token = await svc.initiate_password_reset(payload.email)
    if settings.ENVIRONMENT == "development" and raw_token:
        return MessageResponse(
            message="Password reset email sent.",
            detail={"password_reset_token": raw_token},
        )
    # Always return 200 to prevent email enumeration
    return MessageResponse(
        message="If that email is registered, a password reset link has been sent."
    )


# ── Reset password ─────────────────────────────────────────────────────────────


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password using a token from email",
)
async def reset_password(
    payload: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    await svc.complete_password_reset(payload.token, payload.new_password)
    return MessageResponse(
        message="Password reset successfully. Please log in with your new password."
    )


# ── Change password (authenticated) ───────────────────────────────────────────


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password while authenticated",
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    svc = UserService(db)
    await svc.change_password(current_user, payload.current_password, payload.new_password)
    return MessageResponse(
        message="Password changed successfully. Please log in again."
    )


# ── Get current user ───────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        full_name=current_user.full_name,
        role=current_user.role,
        status=current_user.status,
        is_email_verified=current_user.is_email_verified,
        created_at=str(current_user.created_at),
        updated_at=str(current_user.updated_at),
    )