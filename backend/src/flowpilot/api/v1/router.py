"""API v1 centralized route registration."""

from fastapi import APIRouter

from flowpilot.api.v1.agents import router as agents_router
from flowpilot.api.v1.auth import router as auth_router
from flowpilot.api.v1.health import router as health_router
from flowpilot.api.v1.integrations import router as integrations_router
from flowpilot.api.v1.llm import router as llm_router
from flowpilot.api.v1.monitoring import router as monitoring_router
from flowpilot.api.v1.notifications import router as notifications_router
from flowpilot.api.v1.schedules import router as schedules_router
from flowpilot.api.v1.users import router as users_router
from flowpilot.api.v1.webhooks import router as webhooks_router

api_v1_router = APIRouter()

# Register individual endpoint routers
api_v1_router.include_router(health_router, tags=["Health"])
api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(llm_router)
api_v1_router.include_router(agents_router)
api_v1_router.include_router(schedules_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(monitoring_router)
api_v1_router.include_router(integrations_router)
api_v1_router.include_router(webhooks_router)
