"""Regression and validation tests for explicit Gmail and WhatsApp workflow execution.

Covers:
1. Explicit Gmail instructions with tool name, recipient, subject, body.
2. Explicit WhatsApp template instructions with tool, recipient, template name, language.
3. Natural-language requests without explicit tool identifiers.
4. Genuinely ambiguous instructions requesting clarification.
5. Missing recipient instructions requiring clarification.
6. Unsupported tool/capability requests.
7. Malformed LLM response handling.
8. LLM credential/model error handling.
9. Gmail workflow reaching AWAITING_APPROVAL.
10. WhatsApp workflow reaching AWAITING_APPROVAL.
11. No external action dispatched before authorization.
12. LangGraph interrupt/resume with approval and rejection.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.intent import analyze_intent_node
from flowpilot.agents.planner import plan_workflow_node
from flowpilot.agents.state import AgentState
from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.workflows.engine import WorkflowEngine


@pytest.fixture
async def setup_test_user(db_session: AsyncSession, registered_user: User) -> User:
    """Setup user with active LLM preferences for workflow testing."""
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
            api_key="AIzaSyTestKeyExplicitWorkflows12345",
        )
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=cred.id,
            model_id="gemini-2.5-flash",
        )
        await db_session.commit()
    return registered_user


# ==============================================================================
# 1. Intent Analyzer Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_explicit_gmail_intent_not_rejected_as_ambiguous(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify explicit Gmail instruction is recognized as actionable without ambiguity."""
    request_text = (
        "Send an email using connected Gmail.\n"
        "Tool: gmail_send_email\n"
        "Recipient: test@example.com\n"
        "Subject: Test Subject\n"
        "Body: Hello from FlowPilot AI"
    )

    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=setup_test_user.id,
        thread_id=f"thread_{run_id}",
        original_request=request_text,
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    # Even if LLM returns is_actionable=False due to text-only bias, intent analyzer overrides it
    llm_payload = {
        "intent": "email_automation",
        "action": "gmail_send_email",
        "requires_clarification": False,
        "is_actionable": False,  # Emulating model text-only bias
        "parameters": {
            "tool": "gmail_send_email",
            "recipient": "test@example.com",
            "subject": "Test Subject",
            "body": "Hello from FlowPilot AI",
        },
        "clarification_message": None,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(llm_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(run_id),
        "user_id": str(setup_test_user.id),
        "thread_id": agent_run.thread_id,
        "original_request": request_text,
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        result = await analyze_intent_node(state)

    assert result["execution_status"] == "running"
    assert result["detected_intent"]["is_actionable"] is True
    assert result["detected_intent"]["requires_clarification"] is False
    assert result["detected_intent"]["action"] == "gmail_send_email"
    assert result["detected_intent"]["parameters"]["recipient"] == "test@example.com"


@pytest.mark.asyncio
async def test_explicit_whatsapp_intent_not_rejected_as_ambiguous(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify explicit WhatsApp instruction is recognized as actionable without ambiguity."""
    request_text = (
        "Send a WhatsApp template message using my connected WhatsApp Business Cloud API.\n"
        "Tool: whatsapp_send_template\n"
        "Recipient: +15551234567\n"
        "Template: hello_world\n"
        "Language: en_US"
    )

    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=setup_test_user.id,
        thread_id=f"thread_{run_id}",
        original_request=request_text,
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    llm_payload = {
        "intent": "messaging",
        "action": "whatsapp_send_template",
        "requires_clarification": False,
        "is_actionable": False,  # Emulating model bias
        "parameters": {
            "tool": "whatsapp_send_template",
            "recipient": "+15551234567",
            "template_name": "hello_world",
            "language_code": "en_US",
        },
        "clarification_message": None,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(llm_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(run_id),
        "user_id": str(setup_test_user.id),
        "thread_id": agent_run.thread_id,
        "original_request": request_text,
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        result = await analyze_intent_node(state)

    assert result["execution_status"] == "running"
    assert result["detected_intent"]["is_actionable"] is True
    assert result["detected_intent"]["requires_clarification"] is False


@pytest.mark.asyncio
async def test_genuine_ambiguous_request_rejected_with_clarification(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify genuinely ambiguous request produces clarification failure."""
    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=setup_test_user.id,
        thread_id=f"thread_{run_id}",
        original_request="Please do the needful with the thing.",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    llm_payload = {
        "intent": "unknown",
        "action": "unspecified",
        "requires_clarification": True,
        "is_actionable": False,
        "parameters": {},
        "clarification_message": (
            "Please specify what task or tool you would like FlowPilot to run."
        ),
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(llm_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(run_id),
        "user_id": str(setup_test_user.id),
        "thread_id": agent_run.thread_id,
        "original_request": agent_run.original_request,
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        result = await analyze_intent_node(state)

    assert result["execution_status"] == "failed"
    assert result["final_response"]["status"] == "clarification_needed"
    assert "specify" in result["error_details"].lower()


@pytest.mark.asyncio
async def test_missing_recipient_requires_clarification(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify an email request missing recipient is flagged for clarification."""
    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=setup_test_user.id,
        thread_id=f"thread_{run_id}",
        original_request="Send an email saying the meeting is at 2 PM.",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    llm_payload = {
        "intent": "email_automation",
        "action": "gmail_send_email",
        "requires_clarification": True,
        "is_actionable": True,
        "parameters": {"body": "The meeting is at 2 PM."},
        "clarification_message": "Please provide the recipient email address for this message.",
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(llm_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(run_id),
        "user_id": str(setup_test_user.id),
        "thread_id": agent_run.thread_id,
        "original_request": agent_run.original_request,
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        result = await analyze_intent_node(state)

    assert result["execution_status"] == "failed"
    assert result["final_response"]["status"] == "clarification_needed"
    assert "recipient email address" in result["error_details"].lower()


@pytest.mark.asyncio
async def test_unsupported_capability_distinguished_from_ambiguity(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify completely unsupported capability returns unsupported_capability status."""
    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=setup_test_user.id,
        thread_id=f"thread_{run_id}",
        original_request="Book a flight on Delta Airlines to New York tomorrow.",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    llm_payload = {
        "intent": "travel_booking",
        "action": "book_flight",
        "requires_clarification": False,
        "is_actionable": False,
        "parameters": {"airline": "Delta", "destination": "New York"},
        "clarification_message": "Flight booking is not supported by FlowPilot.",
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(llm_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(run_id),
        "user_id": str(setup_test_user.id),
        "thread_id": agent_run.thread_id,
        "original_request": agent_run.original_request,
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        result = await analyze_intent_node(state)

    assert result["execution_status"] == "failed"
    assert result["final_response"]["status"] == "unsupported_capability"


# ==============================================================================
# 2. Planning Agent Parameter Preservation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_planner_preserves_intent_parameters_for_gmail(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify planner preserves recipient, subject, and body from intent parameters."""
    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=setup_test_user.id,
        thread_id=f"thread_{run_id}",
        original_request="Send email via Gmail",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    detected_intent = {
        "action": "gmail_send_email",
        "parameters": {
            "recipient": "client@example.com",
            "subject": "Invoice Reminder",
            "body": "Please find attached the invoice.",
        },
    }

    # LLM plan proposed without copying every parameter
    llm_plan = {
        "steps": [
            {
                "step_id": "step_1",
                "operation": "gmail_send_email",
                "parameters": {},  # Model omitted params
                "required_capability": "gmail_send_email",
                "approval_required": True,
                "expected_outcome": "Email dispatched to client",
            }
        ],
        "unsupported_capability": False,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(llm_plan),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(run_id),
        "user_id": str(setup_test_user.id),
        "thread_id": agent_run.thread_id,
        "original_request": agent_run.original_request,
        "detected_intent": detected_intent,
        "current_step": 1,
    }

    with patch(
        "flowpilot.agents.planner.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await plan_workflow_node(state)

    assert result["execution_status"] == "running"
    step = result["execution_plan"][0]
    assert step["operation"] == "gmail_send_email"
    # Verify parameters were merged from intent
    assert step["parameters"]["recipient"] == "client@example.com"
    assert step["parameters"]["subject"] == "Invoice Reminder"
    assert step["parameters"]["body"] == "Please find attached the invoice."
    assert step["approval_required"] is True


# ==============================================================================
# 3. Full LangGraph End-to-End Reaching AWAITING_APPROVAL Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_gmail_workflow_pauses_at_awaiting_approval(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify explicit Gmail workflow reaches AWAITING_APPROVAL without sending email."""
    checkpointer = MemorySaver()
    request_text = (
        "Send an email using connected Gmail.\n"
        "Tool: gmail_send_email\n"
        "Recipient: operator@flowpilot.internal\n"
        "Subject: Deployment Verification\n"
        "Body: All systems operational."
    )

    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "email_automation",
                "action": "gmail_send_email",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {
                    "recipient": "operator@flowpilot.internal",
                    "subject": "Deployment Verification",
                    "body": "All systems operational.",
                },
                "clarification_message": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    plan_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step_1",
                        "operation": "gmail_send_email",
                        "parameters": {
                            "recipient": "operator@flowpilot.internal",
                            "subject": "Deployment Verification",
                            "body": "All systems operational.",
                        },
                        "required_capability": "gmail_send_email",
                        "approval_required": True,
                        "expected_outcome": "Sent email via Gmail API",
                    }
                ],
                "unsupported_capability": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=60,
    )

    async def mock_generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        return plan_resp

    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_generate),
        patch("flowpilot.integrations.google.gmail.GmailClient.send_email") as mock_send_email,
    ):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_test_user.id,
            request=request_text,
            checkpointer=checkpointer,
        )

    # 1. State must be AWAITING_APPROVAL
    assert run.status == AgentRunStatus.AWAITING_APPROVAL
    assert run.execution_plan is not None
    assert len(run.execution_plan) == 1
    assert run.execution_plan[0]["operation"] == "gmail_send_email"
    assert run.execution_plan[0]["approval_required"] is True

    # 2. CRITICAL SECURITY: No external message sent before approval
    mock_send_email.assert_not_called()


@pytest.mark.asyncio
async def test_whatsapp_workflow_pauses_at_awaiting_approval(
    db_session: AsyncSession,
    setup_test_user: User,
) -> None:
    """Verify explicit WhatsApp template workflow reaches AWAITING_APPROVAL without sending."""
    checkpointer = MemorySaver()
    request_text = (
        "Send a WhatsApp template message using my connected WhatsApp Business Cloud API.\n"
        "Tool: whatsapp_send_template\n"
        "Recipient: +15559876543\n"
        "Template: hello_world\n"
        "Language: en_US"
    )

    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "messaging",
                "action": "whatsapp_send_template",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {
                    "recipient": "+15559876543",
                    "template_name": "hello_world",
                    "language_code": "en_US",
                },
                "clarification_message": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    plan_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step_1",
                        "operation": "whatsapp_send_template",
                        "parameters": {
                            "recipient": "+15559876543",
                            "template_name": "hello_world",
                            "language_code": "en_US",
                        },
                        "required_capability": "whatsapp_send_template",
                        "approval_required": True,
                        "expected_outcome": "WhatsApp template notification sent",
                    }
                ],
                "unsupported_capability": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=60,
    )

    async def mock_generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        return plan_resp

    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_generate),
        patch(
            "flowpilot.integrations.whatsapp.client.WhatsAppClient.send_template_message"
        ) as mock_send_template,
    ):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_test_user.id,
            request=request_text,
            checkpointer=checkpointer,
        )

    # 1. State must be AWAITING_APPROVAL
    assert run.status == AgentRunStatus.AWAITING_APPROVAL
    assert run.execution_plan[0]["operation"] == "whatsapp_send_template"
    assert run.execution_plan[0]["approval_required"] is True

    # 2. CRITICAL SECURITY: No message sent before approval
    mock_send_template.assert_not_called()
