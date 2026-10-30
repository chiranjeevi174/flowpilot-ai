"""Pytest fixtures for database testing and FastAPI TestClient."""

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import flowpilot.models  # noqa: F401
from flowpilot.api.dependencies import get_db
from flowpilot.core.config import get_settings
from flowpilot.core.security import create_access_token, hash_password
from flowpilot.db.base import Base
from flowpilot.db.session import get_engine
from flowpilot.main import app
from flowpilot.models.user import User

# On Windows, psycopg async requires the Selector event loop policy instead of ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Point application-wide database configuration to the test database for the entire test session
_settings = get_settings()
_settings.ENVIRONMENT = "testing"
_settings.DATABASE_URL = _settings.TEST_DATABASE_URL
get_engine.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def setup_test_schema() -> None:
    """Ensure all database tables exist in the test database for the entire test session."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    settings = get_settings()

    async def _init_schema() -> None:
        engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_init_schema())


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Truncate tables between test runs for strict test isolation."""
    settings = get_settings()
    settings.ENVIRONMENT = "testing"
    yield
    settings.ENVIRONMENT = "testing"

    async def _truncate_tables() -> None:
        engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE integration_events, external_actions, "
                    "integration_connections, workflow_outbox, agent_events, "
                    "agent_runs, scheduled_workflows, llm_usage, llm_preferences, "
                    "llm_credentials, refresh_tokens, password_reset_tokens, "
                    "notifications, users RESTART IDENTITY CASCADE;"
                )
            )
        await engine.dispose()

    asyncio.run(_truncate_tables())


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Direct async database session fixture for test assertions and setup."""
    settings = get_settings()
    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def client() -> TestClient:
    """TestClient with get_db dependency overridden to target the isolated test database."""
    settings = get_settings()
    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
async def registered_user(db_session: AsyncSession) -> User:
    """Fixture providing an active registered user in the test database."""
    user = User(
        id=uuid.uuid4(),
        email="testuser@example.com",
        full_name="Test User",
        password_hash=hash_password("Password123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """Fixture providing an inactive user in the test database."""
    user = User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        full_name="Inactive User",
        password_hash=hash_password("Password123!"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


TEST_FERNET_KEY = "g60pQb_nsFa1G3auxkWTFE9RDev64bbI2fwDIepxvMY="


@pytest.fixture(autouse=True)
def configure_test_encryption_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure LLM encryption keys are configured for all automated test runs."""
    settings = get_settings()
    if not settings.LLM_ENCRYPTION_KEYS:
        monkeypatch.setattr(settings, "LLM_ENCRYPTION_KEYS", [TEST_FERNET_KEY])


@pytest.fixture
async def second_user(db_session: AsyncSession) -> User:
    """Fixture providing a second distinct registered user for isolation testing."""
    user = User(
        id=uuid.uuid4(),
        email="seconduser@example.com",
        full_name="Second User",
        password_hash=hash_password("Password123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(registered_user: User) -> dict[str, str]:
    """Return Authorization headers for the primary test user."""
    token = create_access_token(registered_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_auth_headers(second_user: User) -> dict[str, str]:
    """Return Authorization headers for the second test user."""
    token = create_access_token(second_user.id)
    return {"Authorization": f"Bearer {token}"}
