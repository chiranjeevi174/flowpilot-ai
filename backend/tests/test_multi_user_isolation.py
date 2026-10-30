"""Comprehensive multi-user tenant isolation tests.

Verifies that User A cannot read, modify, execute, or enumerate resources
belonging to User B across all core system domains:
- Agent Runs & Executions
- Run Events & Telemetry
- Human Approvals
- Scheduled Workflows
- In-App Notifications
- LLM BYOK Credentials & Usage History
- App Connections & Credentials
- External Action Audit Records
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.encryption import encrypt_api_key, generate_key_fingerprint
from flowpilot.integrations.security import encrypt_oauth_token
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.llm_credential import LLMCredential
from flowpilot.models.llm_usage import LLMUsage
from flowpilot.models.notification import Notification, NotificationType
from flowpilot.models.scheduled_workflow import (
    ScheduledWorkflow,
    ScheduleType,
)
from flowpilot.models.user import User


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_agent_runs(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User A receives 404 for User B's agent run and cannot see it in run list."""
    user_b_run = AgentRun(
        id=uuid.uuid4(),
        user_id=second_user.id,
        thread_id=f"thread_{uuid.uuid4()}",
        original_request="Private confidential workflow for User B",
        status=AgentRunStatus.COMPLETED,
    )
    db_session.add(user_b_run)
    await db_session.commit()

    # User B can view their own run
    res_b = client.get(f"/api/v1/agents/runs/{user_b_run.id}", headers=second_auth_headers)
    assert res_b.status_code == 200
    assert res_b.json()["id"] == str(user_b_run.id)

    # User A attempting direct object reference (IDOR) receives 404
    res_a = client.get(f"/api/v1/agents/runs/{user_b_run.id}", headers=auth_headers)
    assert res_a.status_code == 404

    # User A listing runs does not see User B's run
    list_a = client.get("/api/v1/agents/runs", headers=auth_headers)
    assert list_a.status_code == 200
    run_ids = [r["id"] for r in list_a.json()["items"]]
    assert str(user_b_run.id) not in run_ids


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_telemetry_events(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User A cannot read audit events or execution telemetry for User B's run."""
    user_b_run = AgentRun(
        id=uuid.uuid4(),
        user_id=second_user.id,
        thread_id=f"thread_{uuid.uuid4()}",
        original_request="Telemetry test for User B",
        status=AgentRunStatus.RUNNING,
    )
    event = AgentEvent(
        id=uuid.uuid4(),
        run_id=user_b_run.id,
        agent_name="planner",
        event_type="plan_generated",
        event_payload={"secret_key": "confidential_data_b"},
    )
    db_session.add(user_b_run)
    db_session.add(event)
    await db_session.commit()

    # User B can read events
    res_b = client.get(f"/api/v1/agents/runs/{user_b_run.id}/events", headers=second_auth_headers)
    assert res_b.status_code == 200
    assert len(res_b.json()) == 1

    # User A receives 404
    res_a = client.get(f"/api/v1/agents/runs/{user_b_run.id}/events", headers=auth_headers)
    assert res_a.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_approve_or_reject_other_users_runs(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify User A cannot approve or reject a pending approval belonging to User B."""
    user_b_run = AgentRun(
        id=uuid.uuid4(),
        user_id=second_user.id,
        thread_id=f"thread_{uuid.uuid4()}",
        original_request="Sensitive operation awaiting approval",
        status=AgentRunStatus.AWAITING_APPROVAL,
    )
    db_session.add(user_b_run)
    await db_session.commit()

    # User A attempts to approve User B's run
    approve_res = client.post(
        f"/api/v1/agents/runs/{user_b_run.id}/approve",
        headers=auth_headers,
        json={"comment": "Malicious approval attempt"},
    )
    assert approve_res.status_code == 404

    # User A attempts to reject User B's run
    reject_res = client.post(
        f"/api/v1/agents/runs/{user_b_run.id}/reject",
        headers=auth_headers,
        json={"comment": "Malicious rejection attempt"},
    )
    assert reject_res.status_code == 404

    # Verify run remains in AWAITING_APPROVAL state in database
    await db_session.refresh(user_b_run)
    assert user_b_run.status == AgentRunStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_schedules(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify complete isolation for scheduled workflows (CRUD and control actions)."""
    user_b_schedule = ScheduledWorkflow(
        id=uuid.uuid4(),
        user_id=second_user.id,
        name="User B Daily Report",
        workflow_request="Generate and email daily summary",
        schedule_type=ScheduleType.DAILY,
        is_active=True,
        next_run_at=datetime.now(UTC),
    )
    db_session.add(user_b_schedule)
    await db_session.commit()

    # User B sees their schedule
    res_b = client.get(f"/api/v1/schedules/{user_b_schedule.id}", headers=second_auth_headers)
    assert res_b.status_code == 200

    # User A receives 404 on get
    res_a = client.get(f"/api/v1/schedules/{user_b_schedule.id}", headers=auth_headers)
    assert res_a.status_code == 404

    # User A list excludes User B's schedule
    list_a = client.get("/api/v1/schedules", headers=auth_headers)
    assert list_a.status_code == 200
    sched_ids = [s["id"] for s in list_a.json()["items"]]
    assert str(user_b_schedule.id) not in sched_ids

    # User A cannot pause User B's schedule
    pause_res = client.post(f"/api/v1/schedules/{user_b_schedule.id}/pause", headers=auth_headers)
    assert pause_res.status_code == 404

    # User A cannot resume User B's schedule
    resume_res = client.post(f"/api/v1/schedules/{user_b_schedule.id}/resume", headers=auth_headers)
    assert resume_res.status_code == 404

    # User A cannot delete User B's schedule
    del_res = client.delete(f"/api/v1/schedules/{user_b_schedule.id}", headers=auth_headers)
    assert del_res.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_notifications(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify User A cannot read, mark read, or dismiss User B's in-app notifications."""
    user_b_notif = Notification(
        id=uuid.uuid4(),
        user_id=second_user.id,
        type=NotificationType.APPROVAL_REQUIRED,
        title="Private Notification for B",
        message="Confidential action requires approval",
        dedup_key=f"user_b_test_{uuid.uuid4()}",
    )
    db_session.add(user_b_notif)
    await db_session.commit()

    # User A list does not include User B's notification
    list_a = client.get("/api/v1/notifications", headers=auth_headers)
    assert list_a.status_code == 200
    notif_ids = [n["id"] for n in list_a.json()["items"]]
    assert str(user_b_notif.id) not in notif_ids

    # User A cannot mark User B's notification as read
    read_res = client.patch(f"/api/v1/notifications/{user_b_notif.id}/read", headers=auth_headers)
    assert read_res.status_code == 404

    # User A cannot dismiss User B's notification
    dismiss_res = client.delete(f"/api/v1/notifications/{user_b_notif.id}", headers=auth_headers)
    assert dismiss_res.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_byok_credentials_or_usage(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify isolation for BYOK API keys and LLM usage telemetry."""
    user_b_cred = LLMCredential(
        id=uuid.uuid4(),
        user_id=second_user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk_secret_for_user_b_12345"),
        key_fingerprint=generate_key_fingerprint("gsk_secret_for_user_b_12345"),
    )
    user_b_usage = LLMUsage(
        id=uuid.uuid4(),
        user_id=second_user.id,
        provider="groq",
        model_id="llama-3.3-70b-versatile",
        input_tokens=150,
        output_tokens=50,
        total_tokens=200,
        estimated_cost=Decimal("0.0001"),
        latency_ms=350,
    )
    db_session.add(user_b_cred)
    db_session.add(user_b_usage)
    await db_session.commit()

    # User A cannot delete User B's credential
    del_cred = client.delete(f"/api/v1/llm/credentials/{user_b_cred.id}", headers=auth_headers)
    assert del_cred.status_code == 404

    # User A usage history excludes User B's record
    usage_res = client.get("/api/v1/llm/usage", headers=auth_headers)
    assert usage_res.status_code == 200
    usage_ids = [u["id"] for u in usage_res.json()]
    assert str(user_b_usage.id) not in usage_ids


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_app_connections(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify User A cannot inspect, test, default, or delete User B's App Connections."""
    user_b_conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=second_user.id,
        provider="slack",
        external_account_name="Acme Corp (User B Workspace)",
        config_method="custom_credentials",
        client_id="user_b_slack_client_id",
        encrypted_client_secret=encrypt_oauth_token("user_b_slack_secret"),
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(user_b_conn)
    await db_session.commit()

    # User A cannot get User B's connection details
    get_res = client.get(f"/api/v1/integrations/{user_b_conn.id}", headers=auth_headers)
    assert get_res.status_code == 404

    # User A cannot test User B's connection
    test_res = client.post(f"/api/v1/integrations/{user_b_conn.id}/test", headers=auth_headers)
    assert test_res.status_code == 404

    # User A cannot set User B's connection as default
    default_res = client.post(
        f"/api/v1/integrations/{user_b_conn.id}/default", headers=auth_headers
    )
    assert default_res.status_code == 404

    # User A cannot disconnect User B's connection
    del_res = client.delete(f"/api/v1/integrations/{user_b_conn.id}", headers=auth_headers)
    assert del_res.status_code == 404

    # User A's overview does not leak User B's connected account or client ID
    overview_res = client.get("/api/v1/integrations/overview", headers=auth_headers)
    assert overview_res.status_code == 200
    overview_items = overview_res.json()
    slack_card = next(item for item in overview_items if item["id"] == "slack")
    assert slack_card["status"] == "not_configured"
    assert slack_card["connected_account"] is None
    assert slack_card["client_id"] is None


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_external_action_audits(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify User A cannot see external actions executed by User B."""
    user_b_action = ExternalAction(
        id=uuid.uuid4(),
        user_id=second_user.id,
        operation="slack_send_message",
        parameter_digest="digest_user_b_action_123",
        idempotency_key="idemp_b_123",
        status=ExternalActionStatus.SUCCEEDED,
        provider_response={"channel": "C12345", "ok": True},
    )
    db_session.add(user_b_action)
    await db_session.commit()

    # User A listing external actions sees empty or only their own
    actions_res = client.get("/api/v1/integrations/actions", headers=auth_headers)
    assert actions_res.status_code == 200
    action_ids = [a["id"] for a in actions_res.json()]
    assert str(user_b_action.id) not in action_ids
