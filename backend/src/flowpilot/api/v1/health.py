"""Health check endpoint definition."""

from fastapi import APIRouter, status

from flowpilot.core.config import get_settings
from flowpilot.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Returns current operational status, service identifier, and version.",
)
async def get_health() -> HealthResponse:
    """Return service health status."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
        version=settings.APP_VERSION,
    )
