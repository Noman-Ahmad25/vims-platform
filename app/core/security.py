from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import DecodeError, ExpiredSignatureError, InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.enums import UserRole, UserStatus
from app.models.user import User

settings = get_settings()

# ── Password hashing ──────────────────────────────────────────────────────────

_pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__time_cost=3,
    argon2__memory_cost=65536,
    argon2__parallelism=4,
)


def hash_password(plain: str) -> str:
    """Return an Argon2id hash of *plain*."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return *True* if *plain* matches *hashed*, *False* otherwise."""
    return _pwd_context.verify(plain, hashed)


def hash_token(token: str) -> str:
    """SHA-256 hash a refresh / reset token for safe DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_secure_token(nbytes: int = 48) -> str:
    """Return a URL-safe secure random token string."""
    return secrets.token_urlsafe(nbytes)


# ── JWT helpers ───────────────────────────────────────────────────────────────

_ALGORITHM = settings.ALGORITHM
_SECRET = settings.SECRET_KEY


class TokenPayload(BaseModel):
    """Validated payload extracted from a JWT."""

    sub: str = Field(..., description="User UUID as string.")
    role: UserRole
    type: str = Field(..., description="'access' or 'refresh'.")
    jti: str = Field(..., description="Unique token identifier.")
    exp: datetime
    iat: datetime


def _build_jwt(
    *,
    subject: str | uuid.UUID,
    role: UserRole,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role.value,
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def create_access_token(
    *,
    subject: str | uuid.UUID,
    role: UserRole,
    expires_delta: timedelta | None = None,
) -> str:
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _build_jwt(
        subject=subject, role=role, token_type="access", expires_delta=delta
    )


def create_refresh_token(
    *,
    subject: str | uuid.UUID,
    role: UserRole,
    expires_delta: timedelta | None = None,
) -> str:
    delta = expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _build_jwt(
        subject=subject, role=role, token_type="refresh", expires_delta=delta
    )


def decode_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT.

    Raises ``HTTPException 401`` on any token problem so callers never
    need to handle raw JWT exceptions.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        raw = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        return TokenPayload(**raw)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (DecodeError, InvalidTokenError, Exception):
        raise credentials_exc


# ── OAuth2 scheme ─────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    scheme_name="JWT",
    description="Enter your **Bearer** token (obtained from /auth/login).",
)

# ── Dependency: resolve current user ─────────────────────────────────────────


async def _get_user_from_token(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    *,
    expected_token_type: str = "access",
) -> User:
    payload = decode_token(token)

    if payload.type != expected_token_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type. Expected '{expected_token_type}'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(payload.sub))
    )
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account has been deactivated.",
        )
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended. Contact support.",
        )
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """FastAPI dependency — resolves to the authenticated ``User``."""
    return await _get_user_from_token(token, db, expected_token_type="access")


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Extends ``get_current_user`` with ACTIVE status check."""
    if current_user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active.",
        )
    return current_user


# ── RBAC factory ──────────────────────────────────────────────────────────────


def require_roles(*allowed_roles: UserRole):
    """
    Return a FastAPI dependency that asserts the current user holds one of the
    *allowed_roles*.

    Usage::

        @router.delete("/users/{user_id}")
        async def delete_user(
            user: User = Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN)),
        ):
            ...
    """

    async def _rbac_guard(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied. Required roles: "
                    f"{[r.value for r in allowed_roles]}."
                ),
            )
        return current_user

    return _rbac_guard


# ── Pre-wired RBAC shortcuts ──────────────────────────────────────────────────

RequireVolunteer = Depends(
    require_roles(
        UserRole.VOLUNTEER,
        UserRole.STAFF,
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
    )
)

RequireStaff = Depends(
    require_roles(
        UserRole.STAFF,
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
    )
)

RequireAdmin = Depends(
    require_roles(
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
    )
)

RequireSuperAdmin = Depends(require_roles(UserRole.SUPER_ADMIN))


# ── Email verification / password-reset token helpers ─────────────────────────


def generate_email_verification_token() -> tuple[str, str]:
    """
    Return (raw_token, hashed_token).

    Store only *hashed_token* in the database; email *raw_token* to the user.
    """
    raw = generate_secure_token()
    return raw, hash_token(raw)


def generate_password_reset_token() -> tuple[str, str]:
    """Return (raw_token, hashed_token) for password-reset flow."""
    raw = generate_secure_token()
    return raw, hash_token(raw)


def verify_hashed_token(raw: str, stored_hash: str) -> bool:
    """Constant-time comparison of a raw token against its stored SHA-256 hash."""
    return secrets.compare_digest(hash_token(raw), stored_hash)