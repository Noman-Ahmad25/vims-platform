from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedColumn
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

# ── Engine ─────────────────────────────────────────────────────────────────────

# app/core/database.py

def _build_engine(*, testing: bool = False) -> AsyncEngine:
    # Neon is serverless; let's allow a managed pool in production
    # but keep NullPool for tests if desired.
    pool_class = NullPool if testing else None 

    engine_kwargs: dict[str, Any] = {
        "echo": settings.SQLALCHEMY_ECHO,
        "pool_pre_ping": True, # Crucial for serverless reconnections
        "connect_args": {
            "server_settings": {"application_name": settings.APP_NAME}
        },
    }

    if pool_class:
        engine_kwargs["poolclass"] = pool_class
    else:
        # Use Neon-friendly defaults for production
        engine_kwargs["pool_size"] = settings.SQLALCHEMY_POOL_SIZE
        engine_kwargs["max_overflow"] = settings.SQLALCHEMY_MAX_OVERFLOW
        engine_kwargs["pool_timeout"] = settings.SQLALCHEMY_POOL_TIMEOUT

    # Use the variable name from your updated config.py
    engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
    return engine


engine: AsyncEngine = _build_engine()

# ── Session factory ───────────────────────────────────────────────────────────

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ── Declarative base ──────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """
    Shared declarative base for all ORM models.

    All metadata lives here so that `Base.metadata.create_all()` touches
    every registered table in one call.
    """

    pass


# ── Database lifecycle helpers ────────────────────────────────────────────────


async def create_all_tables(connection: AsyncConnection | None = None) -> None:
    """Create all tables that have not yet been created in the database."""
    if connection is not None:
        await connection.run_sync(Base.metadata.create_all)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables(connection: AsyncConnection | None = None) -> None:
    """Drop every table known to the metadata — intended for test teardown only."""
    if connection is not None:
        await connection.run_sync(Base.metadata.drop_all)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


async def check_db_connection() -> bool:
    """
    Ping the database.  Returns *True* on success, *False* on failure.
    Used by the /health endpoint to report database readiness.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


async def close_db_connections() -> None:
    """Dispose the engine connection pool — call on application shutdown."""
    await engine.dispose()


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a per-request ``AsyncSession`` and guarantee clean-up.

    Usage in a route::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise
        finally:
            await session.close()
