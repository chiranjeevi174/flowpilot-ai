"""Business logic service for managing persistent user notifications."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.models.notification import Notification, NotificationType

logger = get_logger("services.notifications")


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class NotificationService:
    """Provides user-isolated operations and lifecycle transitions for in-app notifications."""

    @classmethod
    async def create_or_update_notification(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        type: str,
        title: str,
        message: str,
        dedup_key: str,
        category: str = "general",
        link_url: str | None = None,
        meta_data: dict[str, Any] | None = None,
    ) -> Notification:
        """Create a notification or update an existing one matching the dedup_key for this user."""
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.dedup_key == dedup_key,
        )
        result = await db.execute(stmt)
        notification = result.scalar_one_or_none()

        metadata_dict = meta_data or {}

        if notification:
            notification.type = type
            notification.category = category
            notification.title = title
            notification.message = message
            notification.link_url = link_url
            notification.meta_data = metadata_dict
            notification.is_dismissed = False
            notification.updated_at = get_utc_now()
            logger.info("Updated existing notification %s (dedup=%s)", notification.id, dedup_key)
        else:
            notification = Notification(
                user_id=user_id,
                type=type,
                category=category,
                title=title,
                message=message,
                link_url=link_url,
                meta_data=metadata_dict,
                dedup_key=dedup_key,
                is_read=False,
                is_dismissed=False,
            )
            db.add(notification)
            logger.info("Created new notification for user %s (dedup=%s)", user_id, dedup_key)

        await db.commit()
        await db.refresh(notification)
        return notification

    @classmethod
    async def list_notifications(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        include_dismissed: bool = False,
    ) -> list[Notification]:
        """List user-scoped notifications ordered by creation time descending."""
        stmt = select(Notification).where(Notification.user_id == user_id)
        if not include_dismissed:
            stmt = stmt.where(Notification.is_dismissed.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def get_unread_count(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> int:
        """Count unread non-dismissed notifications for the user."""
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.is_dismissed.is_(False),
            )
        )
        return await db.scalar(stmt) or 0

    @classmethod
    async def mark_as_read(
        cls,
        db: AsyncSession,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notification | None:
        """Mark a single notification as read if owned by the user."""
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await db.execute(stmt)
        notification = result.scalar_one_or_none()
        if notification:
            notification.is_read = True
            notification.updated_at = get_utc_now()
            await db.commit()
            await db.refresh(notification)
        return notification

    @classmethod
    async def mark_all_read(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> int:
        """Mark all unread notifications as read for the user."""
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.is_dismissed.is_(False),
            )
            .values(is_read=True, updated_at=get_utc_now())
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0

    @classmethod
    async def dismiss_notification(
        cls,
        db: AsyncSession,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Dismiss a notification from active view."""
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await db.execute(stmt)
        notification = result.scalar_one_or_none()
        if notification:
            notification.is_dismissed = True
            notification.updated_at = get_utc_now()
            await db.commit()
            return True
        return False

    @classmethod
    async def resolve_approval_notification(
        cls,
        db: AsyncSession,
        run_id: str | uuid.UUID,
        decision: str,
    ) -> None:
        """Mark approval-required notifications as resolved when human decision is submitted."""
        run_id_str = str(run_id)
        stmt = select(Notification).where(
            Notification.type == NotificationType.APPROVAL_REQUIRED,
            Notification.is_dismissed.is_(False),
        )
        result = await db.execute(stmt)
        notifications = list(result.scalars().all())

        for notif in notifications:
            if notif.meta_data and notif.meta_data.get("run_id") == run_id_str:
                notif.is_read = True
                notif.title = f"Approval {decision.capitalize()}"
                notif.message = f"Workflow execution {run_id_str[:8]} was {decision}."
                notif.updated_at = get_utc_now()

        await db.commit()
