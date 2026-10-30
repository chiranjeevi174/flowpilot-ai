"""FastAPI router endpoints for multi-agent execution, telemetry, and approvals."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory, get_db
from flowpilot.llm.gateway import CredentialNotFoundError, NoPreferenceConfiguredError
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.schemas.agents import (
    AgentEventResponse,
    AgentRunCreateRequest,
    AgentRunListResponse,
    AgentRunResponse,
    ApprovalDecisionRequest,
)
from flowpilot.services.agents import (
    AgentService,
    InvalidRunStateError,
    RunAccessDeniedError,
    RunNotFoundError,
)

logger = get_logger("api.v1.agents")
router = APIRouter(prefix="/agents", tags=["Agents Orchestration"])


@router.post(
    "/runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an agent execution run",
    description=(
        "Initiates multi-agent orchestration for a natural language request. "
        "Durable outbox record is persisted and execution is dispatched to background workers."
    ),
)
async def create_agent_run(
    payload: AgentRunCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> AgentRunResponse:
    """Start an agent execution run asynchronously."""
    try:
        run = await AgentService.start_run(
            db=db,
            user_id=current_user.id,
            request_data=payload,
        )
        response.headers["Location"] = f"/api/v1/agents/runs/{run.id}"
        run_resp = AgentRunResponse.model_validate(run)
        run_resp.location = f"/api/v1/agents/runs/{run.id}"
        return run_resp
    except (NoPreferenceConfiguredError, CredentialNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/runs",
    response_model=AgentRunListResponse,
    status_code=status.HTTP_200_OK,
    summary="List user's agent executions",
    description="Returns a paginated list of agent runs initiated by the authenticated user.",
)
async def list_agent_runs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> AgentRunListResponse:
    """Retrieve paginated runs for the current user."""
    runs, total = await AgentService.list_runs(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return AgentRunListResponse(
        items=[AgentRunResponse.model_validate(r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/runs/{id}",
    response_model=AgentRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve agent run status and result",
    description="Fetch full status, execution plan, and results for a specific agent run.",
)
async def get_agent_run(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    """Retrieve run details by ID with strict ownership validation."""
    try:
        run = await AgentService.get_run(db=db, run_id=id, user_id=current_user.id)
        return AgentRunResponse.model_validate(run)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RunAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/runs/{id}/events",
    response_model=list[AgentEventResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve execution events for a run",
    description="Fetch chronological telemetry and audit events recorded by agent nodes.",
)
async def get_agent_run_events(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentEventResponse]:
    """Retrieve audit events for an owned agent run."""
    try:
        events = await AgentService.get_run_events(db=db, run_id=id, user_id=current_user.id)
        return [AgentEventResponse.model_validate(e) for e in events]
    except (RunNotFoundError, RunAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/runs/{id}/approve",
    response_model=AgentRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve pending sensitive operation",
    description="Approves a sensitive step paused in awaiting_approval and resumes execution.",
)
async def approve_agent_run(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: ApprovalDecisionRequest | None = None,
) -> AgentRunResponse:
    """Approve and resume an execution run."""
    comment = payload.comment if payload else None
    try:
        run = await AgentService.approve_run(
            db=db,
            run_id=id,
            user_id=current_user.id,
            comment=comment,
        )
        return AgentRunResponse.model_validate(run)
    except (RunNotFoundError, RunAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidRunStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/runs/{id}/reject",
    response_model=AgentRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject pending sensitive operation",
    description="Rejects a proposed operation in awaiting_approval and terminates the run.",
)
async def reject_agent_run(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: ApprovalDecisionRequest | None = None,
) -> AgentRunResponse:
    """Reject and abort an execution run."""
    comment = payload.comment if payload else None
    try:
        run = await AgentService.reject_run(
            db=db,
            run_id=id,
            user_id=current_user.id,
            comment=comment,
        )
        return AgentRunResponse.model_validate(run)
    except (RunNotFoundError, RunAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidRunStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/runs/{id}/cancel",
    response_model=AgentRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an active or queued workflow run",
    description="Cooperatively signals cancellation to an active or queued run.",
)
async def cancel_agent_run(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    """Cancel an active or queued execution run."""
    try:
        run = await AgentService.cancel_run(db=db, run_id=id, user_id=current_user.id)
        return AgentRunResponse.model_validate(run)
    except (RunNotFoundError, RunAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


async def _authenticate_sse_user(
    request: Request,
    db: AsyncSession,
) -> User:
    """Extract and validate bearer token from Authorization header or cookie.

    HttpOnly 'access_token' cookie or Bearer header are supported.
    Query parameter tokens are strictly rejected to avoid credential leakage in logs or URLs.
    """
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to stream execution events.",
        )

    from flowpilot.core.security import decode_token

    try:
        payload = decode_token(token, expected_type="access")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
        ) from exc

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject claim.",
        )

    user = await db.get(User, uuid.UUID(user_id_str))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found.",
        )

    return user


def _format_sse(ev_id: Any, ev_type: str, data: Any) -> str:
    """Format structured payload into a standard SSE message string."""
    payload_str = json.dumps(data, default=str)
    return f"id: {ev_id}\nevent: {ev_type}\ndata: {payload_str}\n\n"


@router.get(
    "/runs/{id}/stream",
    summary="Stream real-time agent execution events via Server-Sent Events (SSE)",
    description=(
        "Yields structured execution telemetry events in real time. Supports Last-Event-ID."
    ),
)
async def stream_agent_run_events(
    id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Stream execution telemetry events in real time using authenticated SSE."""
    import asyncio
    import contextlib

    import redis.asyncio as aioredis

    from flowpilot.core.config import get_settings

    current_user = await _authenticate_sse_user(request, db)
    try:
        await AgentService.get_run(db, id, current_user.id)
    except (RunNotFoundError, RunAccessDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    last_event_id_str = request.headers.get("Last-Event-ID") or request.query_params.get(
        "last_event_id"
    )

    async def sse_event_generator():
        emitted_event_ids: set[str] = set()

        # 1. Emit existing historical events in chronological order
        past_events = await AgentService.get_run_events(db=db, run_id=id, user_id=current_user.id)
        seeking = last_event_id_str is not None
        for ev in past_events:
            ev_id_str = str(ev.id)
            if seeking:
                if ev_id_str == last_event_id_str:
                    seeking = False
                continue
            emitted_event_ids.add(ev_id_str)
            yield _format_sse(ev.id, ev.event_type, ev.event_payload)

        # Check if run is already terminal
        session_maker = async_session_factory()
        async with session_maker() as poll_db:
            refreshed = await poll_db.get(AgentRun, id)
            if refreshed and refreshed.status in AgentRunStatus.TERMINAL:
                return

        # 2. Subscribe to Redis Pub/Sub for real-time notification
        settings = get_settings()
        pubsub = None
        r = None
        try:
            r = aioredis.from_url(settings.REDIS_URL)
            pubsub = r.pubsub()
            await pubsub.subscribe(f"run:{id}:events")
        except Exception as exc:
            logger.debug("Redis Pub/Sub unavailable (%s); using polling fallback for SSE", exc)
            pubsub = None

        heartbeat_counter = 0
        try:
            while True:
                if await request.is_disconnected():
                    break

                event_emitted = False
                if pubsub:
                    try:
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.5)
                        if msg and msg.get("type") == "message":
                            raw = json.loads(
                                msg["data"].decode("utf-8")
                                if isinstance(msg["data"], bytes)
                                else msg["data"]
                            )
                            ev_id = str(raw.get("id"))
                            if ev_id not in emitted_event_ids:
                                emitted_event_ids.add(ev_id)
                                ev_type = raw.get("event_type", "message")
                                ev_payload = raw.get("event_payload", {})
                                yield _format_sse(ev_id, ev_type, ev_payload)
                                event_emitted = True
                                if ev_type in (
                                    "run_completed",
                                    "run_failed",
                                    "run_cancelled",
                                    "approval_rejected",
                                ):
                                    break
                    except Exception as exc:
                        logger.debug("Error reading Redis pubsub message: %s", exc)

                if not pubsub or not event_emitted:
                    await asyncio.sleep(1.0)
                    heartbeat_counter += 1
                    async with session_maker() as poll_db:
                        fresh_events = await AgentService.get_run_events(
                            poll_db, id, current_user.id
                        )
                        for ev in fresh_events:
                            ev_id_str = str(ev.id)
                            if ev_id_str not in emitted_event_ids:
                                emitted_event_ids.add(ev_id_str)
                                yield _format_sse(ev.id, ev.event_type, ev.event_payload)
                                event_emitted = True
                                if ev.event_type in (
                                    "run_completed",
                                    "run_failed",
                                    "run_cancelled",
                                    "approval_rejected",
                                ):
                                    return

                        refreshed = await poll_db.get(AgentRun, id)
                        if refreshed and refreshed.status in AgentRunStatus.TERMINAL:
                            return

                # Send periodic heartbeat ping comment every 15 seconds
                if heartbeat_counter >= 15:
                    heartbeat_counter = 0
                    yield ": ping\n\n"

        finally:
            if pubsub:
                with contextlib.suppress(Exception):
                    await pubsub.unsubscribe(f"run:{id}:events")
                    await pubsub.close()
            if r:
                with contextlib.suppress(Exception):
                    await r.aclose()

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
