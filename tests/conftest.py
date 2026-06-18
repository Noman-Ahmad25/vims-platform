from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any
import json  
import sqlite3

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport # Import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# ── OFFICIAL CODE FIX FOR SQLITE ARRAY TYPE COMPILATION ──────────────────────
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    """Force SQLite to treat PostgreSQL ARRAY types as standard TEXT columns."""
    return "TEXT"

# Teach the underlying sqlite3 driver to serialize Python lists into JSON strings
sqlite3.register_adapter(list, lambda l: json.dumps(l))
# ─────────────────────────────────────────────────────────────────────────────

from app.core.database import Base, get_db
from app.main import app




@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a persistent in-memory SQLite engine for testing using StaticPool."""
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        # CRITICAL: StaticPool preserves the exact same database connection 
        # across all sessions so the tables do not vanish
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create a clean database session for each test with manual rollback isolation."""
    TestingSessionLocal = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        class_=AsyncSession
    )
    
    # Provide the session directly to the test inside a clean transactional state
    async with TestingSessionLocal() as async_session:
        yield async_session
        # Explicitly rollback changes after each test to keep it pristine
        await async_session.rollback()




@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    # Use ASGITransport explicitly
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test"
    ) as async_client:
        yield async_client
    
    app.dependency_overrides.clear()
