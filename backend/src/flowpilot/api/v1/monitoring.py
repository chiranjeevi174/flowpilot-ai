"""FastAPI router endpoints for operational worker health and diagnostic monitoring."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.db.session import get_db
from flowpilot.models.user import User
from flowpilot.schemas.monitoring import MonitoringHealthResponse
from flowpilot.services.monitoring import MonitoringService

router = APIRouter(prefix="/monitoring", tags=["System Monitoring"])


@router.get(
    "/health",
    response_model=MonitoringHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Operational health and readiness diagnostics",
    description="Returns readiness for DB and Redis, Celery queue depths, and run metrics.",
)
async def get_monitoring_health(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MonitoringHealthResponse:
    """Retrieve operational diagnostics and metrics scoped to the authenticated user."""
    return await MonitoringService.get_system_health(db, user_id=current_user.id)
