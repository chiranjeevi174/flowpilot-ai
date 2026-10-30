"""Automated security and multi-user isolation tests for multi-agent execution."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.events import record_event
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User


@pytest.fixture
async def setup_security_user(db_session: AsyncSession, registered_user: User) -> User:
    """Setup active credential and preference for primary user."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        from flowpilot.services.llm import LLMService

        cred = await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="gemini",
            api_key="AIzaSyTestGeminiKey1234567890",
        )
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=cred.id,
            model_id="gemini-2.5-flash",
        )
        await db_session.commit()
    return registered_user


@pytest.fixture
async def sample_user_a_run(db_session: AsyncSession, registered_user: User) -> AgentRun:
    """Create a sample run owned by User A."""
    run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id="flowpilot_run_user_a_secret",
        original_request="Private business financial analysis.",
        status=AgentRunStatus.AWAITING_APPROVAL,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


def test_unauthenticated_agent_endpoints_rejected(client: TestClient) -> None:
    """Verify all agent orchestration endpoints reject unauthenticated calls with 401."""
    random_id = uuid.uuid4()
    assert client.post("/api/v1/agents/runs", json={"request": "test"}).status_code == 401
    assert client.get("/api/v1/agents/runs").status_code == 401
    assert client.get(f"/api/v1/agents/runs/{random_id}").status_code == 401
    assert client.get(f"/api/v1/agents/runs/{random_id}/events").status_code == 401
    assert client.post(f"/api/v1/agents/runs/{random_id}/approve").status_code == 401
    assert client.post(f"/api/v1/agents/runs/{random_id}/reject").status_code == 401


def test_cross_user_run_retrieval_isolation(
    client: TestClient,
    sample_user_a_run: AgentRun,
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot retrieve User A's agent run by ID (returns 404)."""
    res = client.get(
        f"/api/v1/agents/runs/{sample_user_a_run.id}",
        headers=second_auth_headers,
    )
    assert res.status_code == 404


def test_cross_user_list_runs_isolation(
    client: TestClient,
    sample_user_a_run: AgentRun,
    second_auth_headers: dict[str, str],
    auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot see User A's runs in their list results."""
    # User A sees their run
    res_a = client.get("/api/v1/agents/runs", headers=auth_headers)
    assert res_a.status_code == 200
    assert res_a.json()["total"] >= 1

    # User B sees 0 runs
    res_b = client.get("/api/v1/agents/runs", headers=second_auth_headers)
    assert res_b.status_code == 200
    assert res_b.json()["total"] == 0
    assert len(res_b.json()["items"]) == 0


def test_cross_user_events_isolation(
    client: TestClient,
    sample_user_a_run: AgentRun,
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot view audit events of User A's execution run."""
    res = client.get(
        f"/api/v1/agents/runs/{sample_user_a_run.id}/events",
        headers=second_auth_headers,
    )
    assert res.status_code == 404


def test_cross_user_approval_isolation(
    client: TestClient,
    sample_user_a_run: AgentRun,
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot approve or reject User A's pending run."""
    app_res = client.post(
        f"/api/v1/agents/runs/{sample_user_a_run.id}/approve",
        headers=second_auth_headers,
    )
    assert app_res.status_code == 404

    rej_res = client.post(
        f"/api/v1/agents/runs/{sample_user_a_run.id}/reject",
        headers=second_auth_headers,
    )
    assert rej_res.status_code == 404


@pytest.mark.asyncio
async def test_state_and_events_never_store_plaintext_secrets(
    db_session: AsyncSession,
    sample_user_a_run: AgentRun,
) -> None:
    """Verify event recording redacts any potential API keys, passwords, or tokens."""
    sensitive_payload = {
        "operation": "text_categorization",
        "api_key": "AIzaSySecretRawKey123",
        "user_password": "PlaintextPassword!",
        "auth_token": "Bearer eyJhbGciOi...",
        "safe_data": "Normal analytical text",
    }

    event = await record_event(
        db=db_session,
        run_id=sample_user_a_run.id,
        agent_name="test_security_agent",
        event_type="security_check",
        event_payload=sensitive_payload,
    )

    # Redactions must be present
    assert event.event_payload["api_key"] == "[REDACTED]"
    assert event.event_payload["user_password"] == "[REDACTED]"
    assert event.event_payload["auth_token"] == "[REDACTED]"
    assert event.event_payload["safe_data"] == "Normal analytical text"
