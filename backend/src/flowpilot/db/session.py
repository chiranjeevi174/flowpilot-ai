"""Database engine, session factory, and session lifecycle management."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from flowpilot.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Return a cached application-wide asynchronous SQLAlchemy engine."""
    settings = get_settings()
    if settings.is_testing:
        return create_async_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
            echo=settings.DB_ECHO,
        )
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        echo=settings.DB_ECHO,
    )


def async_session_factory(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    """Return an async sessionmaker bound to the provided or default engine."""
    target_engine = engine or get_engine()
    return async_sessionmaker(
        bind=target_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency providing a transactional AsyncSession per request.

    Commits upon successful route execution and rolls back on unhandled exceptions.
    """
    factory = async_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
