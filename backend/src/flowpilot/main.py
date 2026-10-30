import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from flowpilot.api.v1.router import api_v1_router
from flowpilot.core.config import Settings, get_settings
from flowpilot.core.logging import get_logger, setup_logging
from flowpilot.workflows.engine import close_checkpointer, init_checkpointer

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle events."""
    settings = get_settings()
    logger.info(
        "FlowPilot API initialized [env=%s, debug=%s, version=%s]",
        settings.ENVIRONMENT,
        settings.DEBUG,
        settings.APP_VERSION,
    )

    # Initialize LangGraph persistent checkpointer storage if not in test mode
    if not settings.is_testing:
        try:
            await init_checkpointer()
        except Exception as exc:
            logger.warning(
                "LangGraph checkpointer initialization warning (will retry on demand): %s", exc
            )

    yield

    if not settings.is_testing:
        try:
            await close_checkpointer()
        except Exception as exc:
            logger.warning("Error during LangGraph checkpointer pool shutdown: %s", exc)

    logger.info("FlowPilot API shut down completed")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance."""
    app_settings = settings or get_settings()

    # Initialize centralized logging
    setup_logging(log_level=app_settings.LOG_LEVEL)

    application = FastAPI(
        title=app_settings.APP_NAME,
        version=app_settings.APP_VERSION,
        debug=app_settings.DEBUG,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS middleware
    if app_settings.CORS_ORIGINS:
        # Prevent unrestricted wildcard with credentialed CORS
        allow_credentials = "*" not in app_settings.CORS_ORIGINS
        application.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.CORS_ORIGINS,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Mount versioned API routes
    application.include_router(api_v1_router, prefix=app_settings.API_V1_PREFIX)

    return application


# Global application instance for ASGI servers (e.g. uvicorn flowpilot.main:app)
app = create_app()

if __name__ == "__main__":
    import asyncio
    import sys

    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    config = uvicorn.Config(
        "flowpilot.main:app",
        host="127.0.0.1",
        port=8000,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
