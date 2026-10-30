"""User management business logic."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.security import hash_password
from flowpilot.models.user import User
from flowpilot.schemas.user import UserUpdateRequest


class UserService:
    """Service handling user account operations."""

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
        """Retrieve a user by primary key."""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        """Retrieve a user by normalized email address."""
        normalized = email.strip().lower()
        result = await db.execute(select(User).where(User.email == normalized))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user: User,
        data: UserUpdateRequest,
    ) -> User:
        """Update profile fields for the given user."""
        if data.full_name is not None:
            user.full_name = data.full_name

        if data.password is not None:
            user.password_hash = hash_password(data.password)

        user.updated_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(user)
        return user
