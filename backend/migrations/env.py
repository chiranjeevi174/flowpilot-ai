"""Alembic async environment configuration for FlowPilot AI."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure all models are registered on Base.metadata
import flowpilot.models  # noqa: F401
from flowpilot.core.config import get_settings
from flowpilot.db.base import Base

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for autogenerate support
target_metadata = Base.metadata


def get_database_url() -> str:
    """Retrieve database URL from application settings."""
    settings = get_settings()
    return settings.DATABASE_URL


def include_object(object, name, type_, reflected, compare_to):
    """Filter out LangGraph checkpointer tables from Alembic autogenerate tracking."""
    return not (type_ == "table" and name and name.startswith("checkpoint"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without an active DBAPI connection."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations within a transactional database connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create async engine and execute migrations asynchronously."""
    url = get_database_url()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with async connection handling."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
