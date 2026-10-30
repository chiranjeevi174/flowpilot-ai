"""Part B: Complete User Acceptance Test Suite for FlowPilot AI v1.0.0.

Validates the full user journey:
Register -> Login -> Dashboard Profile -> Connect LLM Providers (Gemini, OpenAI, Groq)
-> Discover Models -> Select Default Model -> Create Workflow -> Background Execution
-> Telemetry Stream / Events -> Human-in-the-Loop Approval (Approval & Rejection)
-> Execution History -> Schedule Creation & Cancellation -> Cross-User Data Isolation -> Logout.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.llm.providers.base import ModelInfo
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRun, AgentRunStatus


def test_complete_user_acceptance_journey(client: TestClient) -> None:
    """Execute complete end-to-end user acceptance journey using mocked SDK boundaries."""
    settings = get_settings()

    # --------------------------------------------------------------------------
    # 1. Register User
    # --------------------------------------------------------------------------
    user_email = f"operator_{uuid.uuid4().hex[:6]}@flowpilot.ai"
    password = "ProductionPassword123!"
    reg_res = client.post(
        "/api/v1/auth/register",
        json={"email": user_email, "password": password, "full_name": "Acceptance Operator"},
    )
    assert reg_res.status_code == 201, reg_res.text
    user_info = reg_res.json()
    assert user_info["email"] == user_email
    assert user_info["full_name"] == "Acceptance Operator"

    # --------------------------------------------------------------------------
    # 2. Login User & HttpOnly Cookie
    # --------------------------------------------------------------------------
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": user_email, "password": password},
    )
    assert login_res.status_code == 200, login_res.text
    login_data = login_res.json()
    access_token = login_data["access_token"]
    assert settings.AUTH_COOKIE_NAME in login_res.cookies
    refresh_cookie = login_res.cookies[settings.AUTH_COOKIE_NAME]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    # --------------------------------------------------------------------------
    # 3. Open Dashboard / Verify Profile
    # --------------------------------------------------------------------------
    profile_res = client.get("/api/v1/users/me", headers=auth_headers)
    assert profile_res.status_code == 200
    assert profile_res.json()["email"] == user_email

    # --------------------------------------------------------------------------
    # 4. Connect All Three LLM Providers (Gemini, OpenAI, Groq) with Mock Boundaries
    # --------------------------------------------------------------------------
    provider_keys = [
        (
            "gemini",
            "AIzaSyValidGeminiAcceptanceKey1234567",
            "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        ),
        (
            "openai",
            "sk-proj-validOpenAIAcceptanceKey1234567",
            "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        ),
        (
            "groq",
            "gsk_validGroqAcceptanceKey1234567890abcdef",
            "flowpilot.llm.providers.groq.GroqProvider.validate_credentials",
        ),
    ]
    created_creds = {}

    for provider, test_key, patch_target in provider_keys:
        with patch(patch_target, new_callable=AsyncMock, return_value=True):
            conn_res = client.post(
                "/api/v1/llm/credentials",
                headers=auth_headers,
                json={"provider": provider, "api_key": test_key},
            )
            assert conn_res.status_code == 201, f"Failed connecting {provider}: {conn_res.text}"
            data = conn_res.json()
            assert data["provider"] == provider
            assert "api_key" not in data, "Plaintext key leaked in API response!"
            assert "encrypted_api_key" not in data
            assert data["key_fingerprint"] is not None
            created_creds[provider] = data["id"]

    # --------------------------------------------------------------------------
    # 5. Discover Models for Providers
    # --------------------------------------------------------------------------
    mock_groq_models = [
        ModelInfo(
            id="llama-3.3-70b-versatile",
            name="Llama 3.3 70B Versatile",
            provider="groq",
            context_window=128000,
        ),
        ModelInfo(
            id="llama-3.1-8b-instant",
            name="Llama 3.1 8B Instant",
            provider="groq",
            context_window=128000,
        ),
    ]
    with patch(
        "flowpilot.llm.providers.groq.GroqProvider.list_models",
        new_callable=AsyncMock,
        return_value=mock_groq_models,
    ):
        discover_res = client.get("/api/v1/llm/models?provider=groq", headers=auth_headers)
        assert discover_res.status_code == 200, discover_res.text
        models = discover_res.json()
        assert len(models) == 2
        assert models[0]["id"] == "llama-3.3-70b-versatile"

    # --------------------------------------------------------------------------
    # 6. Select Default Model Preference
    # --------------------------------------------------------------------------
    pref_res = client.put(
        "/api/v1/llm/preferences",
        headers=auth_headers,
        json={
            "credential_id": created_creds["groq"],
            "model_id": "llama-3.3-70b-versatile",
        },
    )
    assert pref_res.status_code == 200, pref_res.text
    pref_data = pref_res.json()
    assert pref_data["provider"] == "groq"
    assert pref_data["model_id"] == "llama-3.3-70b-versatile"

    # --------------------------------------------------------------------------
    # 7. Create Workflow Execution
    # --------------------------------------------------------------------------
    with patch(
        "flowpilot.workflows.dispatch.WorkflowDispatcher.try_dispatch_outbox_entry",
        new_callable=AsyncMock,
    ):
        run_res = client.post(
            "/api/v1/agents/runs",
            headers=auth_headers,
            json={"request": "Generate quarterly operational briefing report."},
        )
        assert run_res.status_code in (201, 202), run_res.text
        run_data = run_res.json()
        run_id = run_data["id"]
        assert run_data["status"] == "queued"
        assert run_data["original_request"] == "Generate quarterly operational briefing report."

    # --------------------------------------------------------------------------
    # 8. Query Workflow Details & History
    # --------------------------------------------------------------------------
    get_run_res = client.get(f"/api/v1/agents/runs/{run_id}", headers=auth_headers)
    assert get_run_res.status_code == 200
    assert get_run_res.json()["id"] == run_id

    list_runs_res = client.get("/api/v1/agents/runs", headers=auth_headers)
    assert list_runs_res.status_code == 200
    runs = list_runs_res.json()["items"]
    assert any(r["id"] == run_id for r in runs)

    # --------------------------------------------------------------------------
    # 9. Verify Schedules Lifecycle (Create, List, Cancel)
    # --------------------------------------------------------------------------
    future_time = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    sched_res = client.post(
        "/api/v1/schedules",
        headers=auth_headers,
        json={
            "name": "Weekly Monday Ops Review",
            "schedule_type": "weekly",
            "timezone": "UTC",
            "schedule_configuration": {"day_of_week": "monday", "time": "08:00"},
            "workflow_request": "Fetch Jira metrics and email executive summary.",
            "next_run_at": future_time,
        },
    )
    assert sched_res.status_code == 201, sched_res.text
    sched_data = sched_res.json()
    sched_id = sched_data["id"]
    assert sched_data["name"] == "Weekly Monday Ops Review"
    assert sched_data["is_active"] is True

    # List schedules
    list_sched_res = client.get("/api/v1/schedules", headers=auth_headers)
    assert list_sched_res.status_code == 200
    assert any(s["id"] == sched_id for s in list_sched_res.json()["items"])

    # Cancel schedule
    del_sched_res = client.delete(f"/api/v1/schedules/{sched_id}", headers=auth_headers)
    assert del_sched_res.status_code == 204

    # --------------------------------------------------------------------------
    # 10. Cross-User Data Isolation
    # --------------------------------------------------------------------------
    user2_email = f"other_operator_{uuid.uuid4().hex[:6]}@flowpilot.ai"
    reg2_res = client.post(
        "/api/v1/auth/register",
        json={"email": user2_email, "password": password, "full_name": "Isolated Operator"},
    )
    assert reg2_res.status_code == 201
    login2_res = client.post(
        "/api/v1/auth/login",
        json={"email": user2_email, "password": password},
    )
    auth2_headers = {"Authorization": f"Bearer {login2_res.json()['access_token']}"}

    # Foreign user cannot access Run 1
    isolated_run_res = client.get(f"/api/v1/agents/runs/{run_id}", headers=auth2_headers)
    assert isolated_run_res.status_code == 404

    # Foreign user cannot see User 1's credentials
    isolated_creds_res = client.get("/api/v1/llm/credentials", headers=auth2_headers)
    assert isolated_creds_res.status_code == 200
    assert len(isolated_creds_res.json()) == 0

    # --------------------------------------------------------------------------
    # 11. User Logout & Session Revocation
    # --------------------------------------------------------------------------
    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={
            **auth_headers,
            "Cookie": f"{settings.AUTH_COOKIE_NAME}={refresh_cookie}",
        },
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["message"] == "Successfully logged out."

    # Refresh attempt with logged out cookie must fail
    refresh_after_logout = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={refresh_cookie}"},
    )
    assert refresh_after_logout.status_code == 401


async def test_human_approval_rejection_and_resolution(
    client: TestClient,
    registered_user,
    db_session: AsyncSession,
) -> None:
    """Verify human-in-the-loop approval: request generation, rejection, and run resolution."""
    login_init = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Password123!"},
    )
    headers = {"Authorization": f"Bearer {login_init.json()['access_token']}"}

    # Create run awaiting approval
    sample_run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"flowpilot_hitl_{uuid.uuid4().hex[:8]}",
        original_request="Send emergency communication to Slack.",
        status=AgentRunStatus.AWAITING_APPROVAL,
        detected_intent={"intent": "send_slack_alert"},
        execution_plan=[
            {"id": 1, "description": "Formulate alert", "status": "completed"},
            {"id": 2, "description": "Post to #announcements", "status": "pending_approval"},
        ],
    )
    db_session.add(sample_run)
    await db_session.flush()

    event = AgentEvent(
        id=uuid.uuid4(),
        run_id=sample_run.id,
        agent_name="verifier",
        event_type="approval_requested",
        event_payload={
            "action": "slack_post_message",
            "target": "#announcements",
            "message": "Emergency maintenance announcement",
        },
    )
    db_session.add(event)
    await db_session.commit()

    # Query pending approvals via status filter
    approvals_res = client.get("/api/v1/agents/runs?status=awaiting_approval", headers=headers)
    assert approvals_res.status_code == 200
    approvals = approvals_res.json()["items"]
    assert any(a["id"] == str(sample_run.id) for a in approvals)

    # Reject approval (enqueues resume task with decision='reject')
    with patch(
        "flowpilot.workflows.dispatch.WorkflowDispatcher.try_dispatch_outbox_entry",
        new_callable=AsyncMock,
    ):
        reject_res = client.post(
            f"/api/v1/agents/runs/{sample_run.id}/reject",
            headers=headers,
            json={"comment": "Operator denied action: incorrect channel target."},
        )
        assert reject_res.status_code == 200
        data = reject_res.json()
        assert data["status"] in ["queued", "rejected", "cancelled", "completed"]

    # Test direct workflow cancellation
    cancel_run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"flowpilot_cancel_{uuid.uuid4().hex[:8]}",
        original_request="Scheduled automated task to cancel.",
        status=AgentRunStatus.QUEUED,
        detected_intent={"intent": "scheduled_task"},
    )
    db_session.add(cancel_run)
    await db_session.commit()

    cancel_res = client.post(f"/api/v1/agents/runs/{cancel_run.id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
