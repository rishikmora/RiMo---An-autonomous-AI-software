"""Async SQLAlchemy engine and session management."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# Tests run each case on a fresh event loop (pytest-asyncio function scope);
# pooled asyncpg connections are bound to the loop that created them, so reusing
# them across loops raises spurious errors. NullPool (opened when db_pool_size==0)
# hands out a fresh connection each time, which is correct for tests. Production
# keeps a real pool.
_use_null_pool = settings.db_pool_size == 0
_engine_kwargs: dict = {"pool_pre_ping": True, "echo": settings.db_echo}
if _use_null_pool:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow

engine: AsyncEngine = create_async_engine(str(settings.database_url), **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside of the request lifecycle (workers)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
