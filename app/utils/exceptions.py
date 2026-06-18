from __future__ import annotations


class VIMSBaseException(Exception):
    """Base for all domain-level exceptions in this application."""

    status_code: int = 500
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


# ── 400 Bad Request ────────────────────────────────────────────────────────────


class BadRequestError(VIMSBaseException):
    status_code = 400
    detail = "Bad request."


class DuplicateResourceError(VIMSBaseException):
    status_code = 409
    detail = "Resource already exists."


class InvalidStateTransitionError(VIMSBaseException):
    status_code = 409
    detail = "This state transition is not permitted."


class SlotCapacityExceededError(VIMSBaseException):
    status_code = 409
    detail = "No slots remaining for this opportunity."


# ── 401 / 403 ─────────────────────────────────────────────────────────────────


class AuthenticationError(VIMSBaseException):
    status_code = 401
    detail = "Authentication failed."


class PermissionDeniedError(VIMSBaseException):
    status_code = 403
    detail = "You do not have permission to perform this action."


class EmailNotVerifiedError(VIMSBaseException):
    status_code = 403
    detail = "Email address has not been verified."


# ── 404 Not Found ─────────────────────────────────────────────────────────────


class NotFoundError(VIMSBaseException):
    status_code = 404
    detail = "Resource not found."


class UserNotFoundError(NotFoundError):
    detail = "User not found."


class ProfileNotFoundError(NotFoundError):
    detail = "Volunteer profile not found."


class OpportunityNotFoundError(NotFoundError):
    detail = "Opportunity not found."


class ApplicationNotFoundError(NotFoundError):
    detail = "Application not found."


# ── 422 Validation ────────────────────────────────────────────────────────────


class ValidationError(VIMSBaseException):
    status_code = 422
    detail = "Validation error."


# ── 410 Gone ──────────────────────────────────────────────────────────────────


class ExpiredTokenError(VIMSBaseException):
    status_code = 410
    detail = "Token has expired or is no longer valid."