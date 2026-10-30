"""FastAPI router endpoints for managing user-scoped in-app notifications."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.db.session import get_db
from flowpilot.models.user import User
from flowpilot.schemas.notifications import (
    NotificationCreateRequest,
    NotificationListResponse,
    NotificationResponse,
)
from flowpilot.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["In-App Notifications"])


@router.get(
    "",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List notifications for authenticated user",
    description="Returns recent notifications and the current unread count.",
)
async def list_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    include_dismissed: Annotated[bool, Query()] = False,
) -> NotificationListResponse:
    """Retrieve notifications scoped strictly to the authenticated user."""
    items = await NotificationService.list_notifications(
        db=db,
        user_id=current_user.id,
        limit=limit,
        include_dismissed=include_dismissed,
    )
    unread_count = await NotificationService.get_unread_count(db=db, user_id=current_user.id)
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        unread_count=unread_count,
        total=len(items),
    )


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update an in-app notification",
    description="Persists a notification with idempotent deduplication key.",
)
async def create_notification(
    payload: NotificationCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    """Record an in-app notification for the current user."""
    notification = await NotificationService.create_or_update_notification(
        db=db,
        user_id=current_user.id,
        type=payload.type,
        title=payload.title,
        message=payload.message,
        dedup_key=payload.dedup_key,
        category=payload.category,
        link_url=payload.link_url,
        meta_data=payload.meta_data,
    )
    return NotificationResponse.model_validate(notification)


@router.patch(
    "/{id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a notification as read",
)
async def mark_as_read(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    """Mark owned notification as read."""
    notification = await NotificationService.mark_as_read(
        db=db,
        notification_id=id,
        user_id=current_user.id,
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return NotificationResponse.model_validate(notification)


@router.post(
    "/mark-all-read",
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications as read",
)
async def mark_all_read(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    """Mark all active notifications as read for current user."""
    updated = await NotificationService.mark_all_read(db=db, user_id=current_user.id)
    return {"updated": updated}


@router.post(
    "/{id}/dismiss",
    status_code=status.HTTP_200_OK,
    summary="Dismiss a notification",
)
async def dismiss_notification(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    """Dismiss a notification from active view."""
    success = await NotificationService.dismiss_notification(
        db=db,
        notification_id=id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return {"dismissed": True}


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification",
)
async def delete_notification(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a notification permanently."""
    success = await NotificationService.dismiss_notification(
        db=db,
        notification_id=id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
