from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class AppBaseModel(BaseModel):
    """
    Project-wide Pydantic base.

    * ``from_attributes=True``  — supports ORM-mode construction.
    * ``populate_by_name=True`` — allows both alias and field-name on input.
    * ``use_enum_values=True``  — serialises enums to their ``.value``.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        str_strip_whitespace=True,
    )


class TimestampSchema(AppBaseModel):
    created_at: datetime
    updated_at: datetime


class UUIDSchema(AppBaseModel):
    id: uuid.UUID


# ── Pagination ─────────────────────────────────────────────────────────────────


class PaginationParams(AppBaseModel):
    page: int = Field(default=1, ge=1, description="1-based page number.")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page.")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponse(AppBaseModel, Generic[T]):
    """Generic paginated response envelope."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def from_items(
        cls,
        *,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        import math

        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 0,
        )


# ── Generic response envelopes ─────────────────────────────────────────────────


class MessageResponse(AppBaseModel):
    """Generic success message response."""

    message: str
    detail: Any | None = None


class ErrorDetail(AppBaseModel):
    field: str | None = None
    message: str
    code: str | None = None


class ErrorResponse(AppBaseModel):
    """Standard error response body."""

    error: str
    details: list[ErrorDetail] | None = None
    request_id: str | None = None