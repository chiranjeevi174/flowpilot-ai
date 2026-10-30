"""FastAPI router endpoints for managing scheduled and recurring agent workflows."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.db.session import get_db
from flowpilot.models.user import User
from flowpilot.schemas.schedules import (
    ScheduledWorkflowCreateRequest,
    ScheduledWorkflowListResponse,
    ScheduledWorkflowResponse,
    ScheduledWorkflowUpdateRequest,
)
from flowpilot.services.scheduling import (
    ScheduleAccessDeniedError,
    ScheduleLimitExceededError,
    ScheduleNotFoundError,
    SchedulingService,
)

router = APIRouter(prefix="/schedules", tags=["Workflow Scheduling"])


@router.post(
    "",
    response_model=ScheduledWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scheduled workflow",
    description=(
        "Registers an automation request to execute at one-time, daily, or weekly intervals."
    ),
)
async def create_schedule(
    payload: ScheduledWorkflowCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledWorkflowResponse:
    """Create a new user-owned scheduled workflow."""
    try:
        schedule = await SchedulingService.create_schedule(
            db=db,
            user_id=current_user.id,
            request_data=payload,
        )
        return ScheduledWorkflowResponse.model_validate(schedule)
    except ScheduleLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=ScheduledWorkflowListResponse,
    status_code=status.HTTP_200_OK,
    summary="List user's scheduled workflows",
    description="Returns all active and paused schedules created by the authenticated user.",
)
async def list_schedules(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledWorkflowListResponse:
    """List all scheduled workflows for the authenticated user."""
    schedules = await SchedulingService.list_schedules(db=db, user_id=current_user.id)
    items = [ScheduledWorkflowResponse.model_validate(s) for s in schedules]
    return ScheduledWorkflowListResponse(items=items, total=len(items))


@router.get(
    "/{id}",
    response_model=ScheduledWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a scheduled workflow",
    description="Fetches an owned schedule definition and its next execution timestamp.",
)
async def get_schedule(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledWorkflowResponse:
    """Retrieve details for a single scheduled workflow."""
    try:
        schedule = await SchedulingService.get_schedule(
            db=db, schedule_id=id, user_id=current_user.id
        )
        return ScheduledWorkflowResponse.model_validate(schedule)
    except (ScheduleNotFoundError, ScheduleAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{id}",
    response_model=ScheduledWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a scheduled workflow",
    description="Updates configuration, name, or recurrence timing for an owned schedule.",
)
async def update_schedule(
    id: uuid.UUID,
    payload: ScheduledWorkflowUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledWorkflowResponse:
    """Partially update an owned scheduled workflow."""
    try:
        schedule = await SchedulingService.update_schedule(
            db=db,
            schedule_id=id,
            user_id=current_user.id,
            update_data=payload,
        )
        return ScheduledWorkflowResponse.model_validate(schedule)
    except (ScheduleNotFoundError, ScheduleAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scheduled workflow",
    description="Permanently deletes an owned scheduled workflow.",
)
async def delete_schedule(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a scheduled workflow."""
    try:
        await SchedulingService.delete_schedule(db=db, schedule_id=id, user_id=current_user.id)
    except (ScheduleNotFoundError, ScheduleAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{id}/pause",
    response_model=ScheduledWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause a recurring schedule",
    description="Temporarily halts execution of an active recurring schedule.",
)
async def pause_schedule(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledWorkflowResponse:
    """Pause an active scheduled workflow."""
    try:
        schedule = await SchedulingService.pause_schedule(
            db=db, schedule_id=id, user_id=current_user.id
        )
        return ScheduledWorkflowResponse.model_validate(schedule)
    except (ScheduleNotFoundError, ScheduleAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{id}/resume",
    response_model=ScheduledWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume a paused schedule",
    description="Resumes recurring execution, recalculating the next occurrence.",
)
async def resume_schedule(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledWorkflowResponse:
    """Resume a paused scheduled workflow."""
    try:
        schedule = await SchedulingService.resume_schedule(
            db=db, schedule_id=id, user_id=current_user.id
        )
        return ScheduledWorkflowResponse.model_validate(schedule)
    except (ScheduleNotFoundError, ScheduleAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
