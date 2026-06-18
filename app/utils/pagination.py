from __future__ import annotations

import math
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import PaginatedResponse

T = TypeVar("T")


async def paginate(
    db: AsyncSession,
    query: Select,
    *,
    page: int,
    page_size: int,
    scalar_result: bool = True,
) -> tuple[list, int]:
    """
    Execute *query* with LIMIT/OFFSET and return ``(items, total_count)``.

    ``scalar_result=True`` calls ``.scalars().all()`` (ORM models).
    ``scalar_result=False`` calls ``.mappings().all()`` (row dicts / projections).
    """
    # Count sub-query — wrap the caller's query in a COUNT
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total: int = total_result.scalar_one()

    offset = (page - 1) * page_size
    paginated_query = query.offset(offset).limit(page_size)
    result = await db.execute(paginated_query)

    if scalar_result:
        items = list(result.scalars().all())
    else:
        items = list(result.mappings().all())

    return items, total


def build_paginated_response(
    *,
    items: list,
    total: int,
    page: int,
    page_size: int,
) -> dict:
    """Return the raw dict consumed by ``PaginatedResponse``."""
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if page_size else 0,
    }