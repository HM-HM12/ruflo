"""Async SQLAlchemy engine/session factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import get_settings
from src.db.base import Base


def create_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)


_engine = None
_session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine()
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables. In production, use Alembic migrations
    (see src/db/migrations/) instead of this — it's provided for quick
    local/dev bootstrapping and for the test suite (SQLite in-memory)."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
