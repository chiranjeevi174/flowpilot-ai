"""User management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.db.session import get_db
from flowpilot.models.user import User
from flowpilot.schemas.user import UserResponse, UserUpdateRequest
from flowpilot.services.users import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get authenticated user profile",
    description="Returns the profile details for the currently authenticated user.",
)
async def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return profile for the currently authenticated user."""
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update authenticated user profile",
    description=(
        "Updates optional profile fields (display name or password) for the authenticated user."
    ),
)
async def update_current_user_profile(
    data: UserUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Update profile details for the authenticated user."""
    updated = await UserService.update_profile(db, current_user, data)
    return UserResponse.model_validate(updated)
