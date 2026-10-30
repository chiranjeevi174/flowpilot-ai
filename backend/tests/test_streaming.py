"""Automated integration tests for Server-Sent Events (SSE) real-time streaming."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.events import record_event
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User


@pytest.fixture
async def sample_run_with_events(db_session: AsyncSession, registered_user: User) -> AgentRun:
    """Create a sample run with sequenced audit events in terminal completed state."""
    run_id = uuid.uuid4()
    run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{run_id}",
        original_request="Real-time telemetry stream test.",
        status=AgentRunStatus.COMPLETED,
    )
    db_session.add(run)

    # Sequence of audit events
    await record_event(
        db=db_session,
        run_id=run_id,
        agent_name="dispatcher",
        event_type="run_queued",
        event_payload={"step": 0},
    )
    await record_event(
        db=db_session,
        run_id=run_id,
        agent_name="intent",
        event_type="intent_completed",
        event_payload={"intent": "analysis"},
    )
    await record_event(
        db=db_session,
        run_id=run_id,
        agent_name="planner",
        event_type="plan_created",
        event_payload={"total_steps": 1},
    )
    await record_event(
        db=db_session,
        run_id=run_id,
        agent_name="engine",
        event_type="run_completed",
        event_payload={"status": "success"},
    )
    await db_session.commit()
    return run


def test_sse_stream_authentication_and_event_delivery(
    client: TestClient,
    sample_run_with_events: AgentRun,
    auth_headers: dict[str, str],
) -> None:
    """Verify authenticated SSE stream delivers formatted events and closes on terminal run."""
    run_id = sample_run_with_events.id

    response = client.get(
        f"/api/v1/agents/runs/{run_id}/stream",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    # Parse SSE text output
    content = response.text
    assert "event: run_queued" in content
    assert "event: intent_completed" in content
    assert "event: plan_created" in content
    assert "event: run_completed" in content


def test_sse_stream_unauthenticated_rejected(
    client: TestClient,
    sample_run_with_events: AgentRun,
) -> None:
    """Verify unauthenticated SSE stream request is rejected with 401 Unauthorized."""
    run_id = sample_run_with_events.id
    response = client.get(f"/api/v1/agents/runs/{run_id}/stream")
    assert response.status_code == 401


def test_sse_stream_cross_user_isolation(
    client: TestClient,
    sample_run_with_events: AgentRun,
    second_user: User,
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot stream telemetry events from User A's execution run."""
    run_id = sample_run_with_events.id

    response = client.get(
        f"/api/v1/agents/runs/{run_id}/stream",
        headers=second_auth_headers,
    )
    assert response.status_code in (403, 404)


def test_sse_stream_last_event_id_reconnection(
    client: TestClient,
    sample_run_with_events: AgentRun,
    auth_headers: dict[str, str],
) -> None:
    """Verify reconnecting with Last-Event-ID delivers only subsequent events."""
    run_id = sample_run_with_events.id

    # First fetch all events to get an ID
    events_res = client.get(f"/api/v1/agents/runs/{run_id}/events", headers=auth_headers)
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 2

    # Pick the second event's ID as Last-Event-ID
    last_id = events[1]["id"]

    reconnect_headers = {**auth_headers, "Last-Event-ID": str(last_id)}
    stream_res = client.get(
        f"/api/v1/agents/runs/{run_id}/stream",
        headers=reconnect_headers,
    )
    assert stream_res.status_code == 200
    content = stream_res.text

    # The earlier event (run_queued) should not be yielded
    assert "event: run_queued" not in content
    # Subsequent events should be yielded
    assert "event: run_completed" in content


def test_sse_stream_query_param_token_rejected(
    client: TestClient,
    sample_run_with_events: AgentRun,
    auth_headers: dict[str, str],
) -> None:
    """Verify that passing JWT token in URL query parameter is rejected (Phase 5 hardening)."""
    run_id = sample_run_with_events.id
    token = auth_headers["Authorization"].split(" ")[1]

    # Without Authorization header, query param token must be rejected with 401
    response = client.get(f"/api/v1/agents/runs/{run_id}/stream?token={token}")
    assert response.status_code == 401


def test_sse_stream_cookie_authentication(
    client: TestClient,
    sample_run_with_events: AgentRun,
    auth_headers: dict[str, str],
) -> None:
    """Verify that authenticated SSE stream works via HttpOnly access_token cookie."""
    run_id = sample_run_with_events.id
    token = auth_headers["Authorization"].split(" ")[1]

    # Send request with Cookie header instead of Authorization header
    response = client.get(
        f"/api/v1/agents/runs/{run_id}/stream",
        headers={"Cookie": f"access_token={token}"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "event: run_completed" in response.text
