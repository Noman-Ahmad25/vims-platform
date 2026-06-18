from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_email_verification_token,
    generate_password_reset_token,
    hash_password,
    hash_token,
    verify_hashed_token,
    verify_password,
)
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest, RegisterRequest
from app.utils.exceptions import (
    AuthenticationError,
    DuplicateResourceError,
    EmailNotVerifiedError,
    ExpiredTokenError,
    UserNotFoundError,
)

_RESET_TOKEN_TTL_HOURS = 2


class UserService:
    """
    Encapsulates all user-account business logic:
    registration, authentication, password management,
    email verification, and admin user operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User).where(User.email == email.lower(), User.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def _get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(
            select(User).where(User.id == user_id, User.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def _get_by_id_or_raise(self, user_id: uuid.UUID) -> User:
        user = await self._get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    # ── Registration ───────────────────────────────────────────────────────────

    async def register_volunteer(self, payload: RegisterRequest) -> tuple[User, str]:
        """
        Create a new VOLUNTEER account.

        Returns ``(user, raw_verification_token)`` so the caller can
        dispatch a verification email without storing the raw token.
        """
        email = payload.email.lower()
        existing = await self._get_by_email(email)
        if existing is not None:
            raise DuplicateResourceError("An account with this email already exists.")

        raw_token, hashed = generate_email_verification_token()
        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            role=UserRole.VOLUNTEER,
            status=UserStatus.PENDING_VERIFICATION,
            is_email_verified=False,
            email_verification_token=hashed,
        )
        self._db.add(user)
        await self._db.flush()  # populate user.id without committing
        return user, raw_token

    # ── Admin: create staff / admin accounts ──────────────────────────────────

    async def admin_create_user(self, payload: AdminCreateUserRequest) -> User:
        email = payload.email.lower()
        existing = await self._get_by_email(email)
        if existing is not None:
            raise DuplicateResourceError("An account with this email already exists.")

        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            role=payload.role,
            status=UserStatus.ACTIVE,  # staff accounts are immediately active
            is_email_verified=True,
        )
        self._db.add(user)
        await self._db.flush()
        return user

    # ── Email verification ────────────────────────────────────────────────────

    async def verify_email(self, raw_token: str) -> User:
        """
        Find the user whose ``email_verification_token`` matches *raw_token*,
        mark them verified, and activate their account.
        """
        hashed = hash_token(raw_token)
        result = await self._db.execute(
            select(User).where(
                User.email_verification_token == hashed,
                User.is_deleted.is_(False),
            )
        )
        user: User | None = result.scalar_one_or_none()
        if user is None:
            raise ExpiredTokenError("Verification token is invalid or has already been used.")

        user.is_email_verified = True
        user.status = UserStatus.ACTIVE
        user.email_verification_token = None
        self._db.add(user)
        return user

    async def resend_verification_email(self, email: str) -> tuple[User, str]:
        """Re-issue a verification token for an unverified account."""
        user = await self._get_by_email(email.lower())
        if user is None:
            # Security: don't reveal whether the account exists
            raise UserNotFoundError("If that email is registered, a new link will be sent.")
        if user.is_email_verified:
            raise DuplicateResourceError("Email address is already verified.")

        raw_token, hashed = generate_email_verification_token()
        user.email_verification_token = hashed
        self._db.add(user)
        return user, raw_token

    # ── Authentication ────────────────────────────────────────────────────────

    async def authenticate(self, email: str, password: str) -> User:
        """
        Validate credentials.

        Raises ``AuthenticationError`` on any failure so the caller
        cannot distinguish between "no account" and "wrong password".
        """
        user = await self._get_by_email(email.lower())
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password.")
        if user.is_deleted:
            raise AuthenticationError("This account has been deactivated.")
        if user.status == UserStatus.SUSPENDED:
            raise AuthenticationError("This account is suspended. Contact support.")
        if not user.is_email_verified:
            raise EmailNotVerifiedError(
                "Please verify your email address before logging in."
            )
        return user

    async def store_refresh_token_hash(self, user: User, raw_refresh_token: str) -> None:
        """Persist the SHA-256 hash of the issued refresh token."""
        user.refresh_token_hash = hash_token(raw_refresh_token)
        self._db.add(user)

    async def validate_refresh_token(self, user_id: uuid.UUID, raw_token: str) -> User:
        """
        Verify *raw_token* matches the stored hash.
        Returns the user on success, raises ``AuthenticationError`` on failure.
        """
        user = await self._get_by_id_or_raise(user_id)
        if user.refresh_token_hash is None or not verify_hashed_token(
            raw_token, user.refresh_token_hash
        ):
            raise AuthenticationError("Refresh token is invalid or has been revoked.")
        return user

    async def revoke_refresh_token(self, user: User) -> None:
        """Invalidate the stored refresh token (logout)."""
        user.refresh_token_hash = None
        self._db.add(user)

    # ── Password reset ────────────────────────────────────────────────────────

    async def initiate_password_reset(self, email: str) -> tuple[User | None, str | None]:
        """
        Issue a password-reset token.

        Always returns ``(None, None)`` when the email is not found so the
        HTTP layer can respond identically whether or not the account exists.
        """
        user = await self._get_by_email(email.lower())
        if user is None:
            return None, None

        raw_token, hashed = generate_password_reset_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=_RESET_TOKEN_TTL_HOURS)

        user.password_reset_token = hashed
        user.password_reset_expires_at = expires_at
        self._db.add(user)
        return user, raw_token

    async def complete_password_reset(self, raw_token: str, new_password: str) -> User:
        hashed = hash_token(raw_token)
        result = await self._db.execute(
            select(User).where(
                User.password_reset_token == hashed,
                User.is_deleted.is_(False),
            )
        )
        user: User | None = result.scalar_one_or_none()
        if user is None:
            raise ExpiredTokenError("Password reset token is invalid or has already been used.")

        expires_at = user.password_reset_expires_at
        if expires_at is not None:
            # expires_at may be stored as naive UTC from DB — normalise
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_at:
                raise ExpiredTokenError("Password reset token has expired.")

        user.hashed_password = hash_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires_at = None
        user.refresh_token_hash = None  # invalidate all sessions
        self._db.add(user)
        return user

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> User:
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect.")
        user.hashed_password = hash_password(new_password)
        user.refresh_token_hash = None  # force re-login
        self._db.add(user)
        return user

    # ── Admin operations ──────────────────────────────────────────────────────

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        return await self._get_by_id_or_raise(user_id)

    async def list_users(
        self,
        *,
        role: UserRole | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ):
        """Return a base SELECT for user listing; pagination applied in router."""
        stmt = select(User).where(User.is_deleted.is_(False))
        if role is not None:
            stmt = stmt.where(User.role == role)
        if status is not None:
            stmt = stmt.where(User.status == status)
        if search:
            pattern = f"%{search.lower()}%"
            from sqlalchemy import or_, func as safunc
            stmt = stmt.where(
                or_(
                    safunc.lower(User.email).like(pattern),
                    safunc.lower(User.first_name).like(pattern),
                    safunc.lower(User.last_name).like(pattern),
                )
            )
        return stmt.order_by(User.created_at.desc())

    async def admin_update_user(
        self, user_id: uuid.UUID, payload: AdminUpdateUserRequest
    ) -> User:
        user = await self._get_by_id_or_raise(user_id)
        if payload.role is not None:
            user.role = payload.role
        if payload.status is not None:
            user.status = payload.status
        if payload.first_name is not None:
            user.first_name = payload.first_name.strip()
        if payload.last_name is not None:
            user.last_name = payload.last_name.strip()
        self._db.add(user)
        return user

    async def soft_delete_user(self, user_id: uuid.UUID) -> None:
        user = await self._get_by_id_or_raise(user_id)
        user.is_deleted = True
        user.deleted_at = datetime.now(timezone.utc)
        user.status = UserStatus.DEACTIVATED
        user.refresh_token_hash = None
        self._db.add(user)