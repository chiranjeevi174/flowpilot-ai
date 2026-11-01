"""Regression tests for dataset-specific numerical verification, pre-send verification,
and idempotent external action handling.

Tests:
1. Different spreadsheet ranges producing different totals.
2. Three or more data records (e.g. Chiru/Laptop/12/650, Chinnu/Monitor/10/180,
   Chintu/Mobile/5/200).
3. Rep/Item grouping and aggregation for repeated representatives and items.
4. No hardcoded dataset-specific totals in analysis, verifier, or approval logic.
5. Valid numerical content passing verification without false alarms.
6. Invalid numerical content being flagged before human approval.
7. Approval digest matching the exact email body (tamper protection).
8. Successful Gmail dispatch followed by internal verification failure does not trigger re-send.
9. No duplicate sending on retry or worker recovery (idempotent replay).
10. Gmail API acceptance versus confirmed delivery distinction.
11. Audit trail, monitoring, and reconciliation for post-send verification scenarios.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.analysis import (
    analyze_tabular_dataset,
    format_analysis_for_prompt,
    get_verified_numerical_totals,
    rectify_text_numbers,
    validate_summary_accuracy,
)
from flowpilot.agents.approval import approval_gate_node
from flowpilot.agents.graph import route_after_verifier
from flowpilot.agents.state import AgentState
from flowpilot.agents.verifier import verify_execution_node
from flowpilot.integrations.registry import (
    ParameterTamperedError,
    _execute_with_action_audit,
)
from flowpilot.integrations.security import compute_parameter_digest
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.user import User

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user."""
    user = User(
        id=uuid.uuid4(),
        email=f"user_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="test_hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def sample_run(db_session: AsyncSession, sample_user: User) -> AgentRun:
    """Create a sample AgentRun."""
    run = AgentRun(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        thread_id=f"flowpilot_run_{uuid.uuid4().hex[:8]}",
        original_request="Analyze sample spreadsheet and dispatch report to Gmail",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


# ==============================================================================
# 1. Dataset Analysis & Dynamic Numerical Derivation Tests
# ==============================================================================


def test_three_record_dataset_numerical_totals() -> None:
    """Verify exact dynamic numerical calculations for the 3-record production-like dataset."""
    sample_rows = [
        ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
        ["1001", "2026-01-05", "North", "Chiru", "Laptop", "12", "650"],
        ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
        ["1003", "2026-01-07", "South", "Chintu", "Mobile", "5", "200"],
    ]

    analysis = analyze_tabular_dataset(sample_rows, sheet_title="Sheet1!A1:G4")
    assert analysis.data_row_count == 3
    assert analysis.quantity_col == "Units"
    assert analysis.cost_col == "Cost"
    assert analysis.rep_col == "Rep"
    assert analysis.item_col == "Item"

    # Units: 12 + 10 + 5 = 27
    assert analysis.columns["Units"].sum_val == 27
    # Direct Cost sum: 650 + 180 + 200 = 1030
    assert analysis.columns["Cost"].sum_val == 1030
    # Unit Cost total: 12*650 + 10*180 + 5*200 = 7800 + 1800 + 1000 = 10,600
    assert analysis.per_unit_combined_total == 10600

    # Dynamic totals set must contain exact amounts and NOT have old hardcoded 9,600 or 830
    from decimal import Decimal

    totals = get_verified_numerical_totals(analysis)
    assert Decimal(10600) in totals
    assert Decimal(1030) in totals
    assert Decimal(27) in totals
    assert Decimal(9600) not in totals
    assert Decimal(830) not in totals


def test_different_ranges_produce_different_totals() -> None:
    """Verify different spreadsheet ranges and datasets produce their own dynamic totals."""
    # Dataset B: 4 records with distinct items and amounts
    dataset_b = [
        ["Order ID", "Rep", "Item", "Units", "Cost"],
        ["2001", "Alice", "Desk", "4", "250"],  # 4 * 250 = 1000
        ["2002", "Bob", "Chair", "8", "75"],  # 8 * 75 = 600
        ["2003", "Charlie", "Lamp", "15", "30"],  # 15 * 30 = 450
        ["2004", "Dana", "Pen", "50", "2"],  # 50 * 2 = 100
    ]

    analysis = analyze_tabular_dataset(dataset_b, sheet_title="Office_Supplies")
    assert analysis.data_row_count == 4
    # Units: 4 + 8 + 15 + 50 = 77
    assert analysis.columns["Units"].sum_val == 77
    # Direct cost sum: 250 + 75 + 30 + 2 = 357
    assert analysis.columns["Cost"].sum_val == 357
    # Unit cost total: 1000 + 600 + 450 + 100 = 2150
    assert analysis.per_unit_combined_total == 2150

    from decimal import Decimal

    totals = get_verified_numerical_totals(analysis)
    assert Decimal(2150) in totals
    assert Decimal(357) in totals
    assert Decimal(77) in totals
    assert Decimal(9600) not in totals


def test_rep_item_grouping_and_repeated_combinations() -> None:
    """Verify grouping and aggregation when representatives and items repeat across rows."""
    repeating_rows = [
        ["Date", "Rep", "Item", "Units", "Cost"],
        ["2026-01-01", "Sarah", "Laptop", "5", "500"],  # 5 * 500 = 2500
        ["2026-01-02", "Alex", "Monitor", "3", "200"],  # 3 * 200 = 600
        ["2026-01-03", "Sarah", "Laptop", "3", "500"],  # 3 * 500 = 1500 (repeated Rep & Item)
        [
            "2026-01-04",
            "Sarah",
            "Mouse",
            "10",
            "25",
        ],  # 10 * 25 = 250 (repeated Rep, different Item)
        ["2026-01-05", "Alex", "Monitor", "2", "200"],  # 2 * 200 = 400 (repeated Rep & Item)
    ]

    analysis = analyze_tabular_dataset(repeating_rows)

    # Check rep_item_totals
    sarah_laptop = next(
        (
            rit
            for rit in analysis.rep_item_totals
            if rit["rep"] == "Sarah" and rit["item"] == "Laptop"
        ),
        None,
    )
    assert sarah_laptop is not None
    assert sarah_laptop["units"] == 8.0  # 5 + 3
    assert sarah_laptop["unit_cost_total"] == 4000.0  # 2500 + 1500
    assert sarah_laptop["order_cost_total"] == 1000.0  # 500 + 500

    sarah_mouse = next(
        (
            rit
            for rit in analysis.rep_item_totals
            if rit["rep"] == "Sarah" and rit["item"] == "Mouse"
        ),
        None,
    )
    assert sarah_mouse is not None
    assert sarah_mouse["units"] == 10.0
    assert sarah_mouse["unit_cost_total"] == 250.0

    alex_monitor = next(
        (
            rit
            for rit in analysis.rep_item_totals
            if rit["rep"] == "Alex" and rit["item"] == "Monitor"
        ),
        None,
    )
    assert alex_monitor is not None
    assert alex_monitor["units"] == 5.0  # 3 + 2
    assert alex_monitor["unit_cost_total"] == 1000.0  # 600 + 400

    # Check rep_totals
    sarah_total = analysis.rep_totals["Sarah"]
    assert sarah_total["total_units"] == 18.0
    assert sarah_total["unit_cost_total"] == 4250.0

    alex_total = analysis.rep_totals["Alex"]
    assert alex_total["total_units"] == 5.0
    assert alex_total["unit_cost_total"] == 1000.0

    # Prompt format should include aggregated breakdown
    prompt_desc = format_analysis_for_prompt(analysis)
    assert "Sarah (Laptop):" in prompt_desc
    assert "Sarah (Mouse):" in prompt_desc
    assert "Alex (Monitor):" in prompt_desc


# ==============================================================================
# 2. Validation & Rectification Tests (No Stale Totals)
# ==============================================================================


def test_valid_numerical_content_passes_validation() -> None:
    """Valid summary for the 3-record dataset passes validation with zero errors."""
    sample_rows = [
        ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
        ["1001", "2026-01-05", "North", "Chiru", "Laptop", "12", "650"],
        ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
        ["1003", "2026-01-07", "South", "Chintu", "Mobile", "5", "200"],
    ]
    analysis = analyze_tabular_dataset(sample_rows)

    valid_text = (
        "Here is the requested breakdown: "
        "Chiru sold 12 Laptops with total cost 7,800. "
        "Chinnu sold 10 Monitors with total cost 1,800. "
        "Chintu sold 5 Mobiles with total cost 1,000. "
        "The overall combined unit cost total is 10,600 across 27 units."
    )

    errors = validate_summary_accuracy(valid_text, analysis)
    assert len(errors) == 0


def test_invalid_numerical_content_flagged_with_dynamic_expectations() -> None:
    """Inaccurate figures are flagged using current dataset totals, not old test numbers."""
    sample_rows = [
        ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
        ["1001", "2026-01-05", "North", "Chiru", "Laptop", "12", "650"],
        ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
        ["1003", "2026-01-07", "South", "Chintu", "Mobile", "5", "200"],
    ]
    analysis = analyze_tabular_dataset(sample_rows)

    inaccurate_text = "The dataset contains 27 units with a combined cost of $50,000."

    errors = validate_summary_accuracy(inaccurate_text, analysis)
    assert len(errors) >= 1
    # Check that error critiques use 10,600 / 1,030, NOT 9,600 / 830
    assert any("10,600" in e for e in errors)
    assert not any("9,600" in e for e in errors)


def test_rectify_text_numbers_applies_current_dataset_totals() -> None:
    """Rectification replaces inaccurate numbers with current dataset figures."""
    sample_rows = [
        ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
        ["1001", "2026-01-05", "North", "Chiru", "Laptop", "12", "650"],
        ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
        ["1003", "2026-01-07", "South", "Chintu", "Mobile", "5", "200"],
    ]
    analysis = analyze_tabular_dataset(sample_rows)

    flawed_text = "Summary: The 3 orders represent 27 units with total cost of $8,300."

    rectified = rectify_text_numbers(flawed_text, analysis)
    assert "8,300" not in rectified
    assert "$8,300" not in rectified
    # Should contain verified 10,600 or 1,030
    assert "10,600" in rectified or "1,030" in rectified


# ==============================================================================
# 3. Pre-Approval Validation & Approval Digest Integrity Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_pre_approval_validation_rectifies_and_digests(
    sample_user: User,
    sample_run: AgentRun,
) -> None:
    """approval_gate_node rectifies inaccurate numbers and computes approval digest
    on rectified body.
    """
    from unittest.mock import patch

    # Historical results containing step 1 rows
    step_results = [
        {
            "step_id": "step_1",
            "operation": "sheets_read_range",
            "result": {
                "rows": [
                    ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
                    ["1001", "2026-01-05", "North", "Chiru", "Laptop", "12", "650"],
                    ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
                    ["1003", "2026-01-07", "South", "Chintu", "Mobile", "5", "200"],
                ]
            },
        }
    ]

    state = {
        "run_id": str(sample_run.id),
        "user_id": str(sample_user.id),
        "execution_plan": [
            {
                "step_id": "step_1",
                "operation": "sheets_read_range",
                "approval_required": False,
            },
            {
                "step_id": "step_3",
                "operation": "gmail_send_email",
                "approval_required": True,
                "parameters": {
                    "to": "operator@flowpilot.ai",
                    "subject": "Sales Report",
                    "body": "The combined total cost across 27 units is $8,300.",
                },
            },
        ],
        "executed_step_ids": ["step_1"],
        "step_results": step_results,
        "approval_status": "pending",
    }

    with patch("flowpilot.agents.approval.interrupt") as mock_interrupt:
        await approval_gate_node(state)
        assert mock_interrupt.called
        payload = mock_interrupt.call_args[0][0]
        # Inaccurate $8,300 must have been rectified before reaching the human gate
        assert "8,300" not in payload["body"]
        assert "$8,300" not in payload["body"]
        # Verified total (10,600 or 1,030) must be present
        assert "10,600" in payload["body"] or "1,030" in payload["body"]
        # Parameter digest must match the rectified body
        expected_digest = compute_parameter_digest(payload["parameters"])
        assert payload["parameter_digest"] == expected_digest


def test_approval_digest_exact_body_matching() -> None:
    """Approval digest computation is strictly deterministic and detects body tampering."""
    original_params = {
        "to": "operator@flowpilot.ai",
        "subject": "Sales Summary",
        "body": "Rep: Alice, Item: Laptop, Total: 7,800. Verified total: 10,600.",
    }
    digest_orig = compute_parameter_digest(original_params)

    # Any modification (even an added space) produces a different digest
    tampered_params = dict(original_params)
    tampered_params["body"] = original_params["body"] + " "
    digest_tampered = compute_parameter_digest(tampered_params)

    assert digest_orig != digest_tampered


@pytest.mark.asyncio
async def test_tampered_payload_rejected_at_dispatch(
    db_session: AsyncSession,
    sample_user: User,
    sample_run: AgentRun,
) -> None:
    """Parameters modified after approval are rejected with ParameterTamperedError."""
    approved_params = {
        "to": "operator@flowpilot.ai",
        "subject": "Sales Summary",
        "body": "Approved Body Text",
    }
    digest = compute_parameter_digest(approved_params)

    dispatched_params = {
        "to": "operator@flowpilot.ai",
        "subject": "Sales Summary",
        "body": "MODIFIED Body Text",
        "approved": True,
        "approval_parameter_digest": digest,
    }

    mock_exec = AsyncMock()

    with pytest.raises(ParameterTamperedError, match="modified after approval"):
        await _execute_with_action_audit(
            db=db_session,
            user_id=sample_user.id,
            operation="gmail_send_email",
            parameters=dispatched_params,
            connection=None,
            run_id=sample_run.id,
            execution_fn=mock_exec,
        )

    # Execution function must NEVER have been called
    assert not mock_exec.called


# ==============================================================================
# 4. Post-Send Verification & LangGraph Routing Invariants
# ==============================================================================


@pytest.mark.asyncio
async def test_successful_dispatch_prevents_post_send_failure_loop(
    sample_user: User,
    sample_run: AgentRun,
) -> None:
    """When an external dispatch has succeeded, post-send verifier does not fail the workflow."""
    step_results = [
        {
            "step_id": "step_1",
            "operation": "sheets_read_range",
            "status": "success",
            "result": {"rows": [["Col1", "Col2"], ["A", "100"]]},
        },
        {
            "step_id": "step_2",
            "operation": "task_summary_generation",
            "status": "success",
            "result": {"summary": "Analysis completed"},
        },
        {
            "step_id": "step_3",
            "operation": "gmail_send_email",
            "status": "success",
            "result": {
                "status": "sent",
                "delivery_status": "api_accepted",
                "message_id": "1a191772baa36d49",
            },
        },
    ]

    state: AgentState = {
        "original_request": "Send email report",
        "run_id": str(sample_run.id),
        "user_id": str(sample_user.id),
        "execution_plan": [
            {"step_id": "step_1", "operation": "sheets_read_range", "description": "read"},
            {"step_id": "step_2", "operation": "task_summary_generation", "description": "gen"},
            {"step_id": "step_3", "operation": "gmail_send_email", "description": "send"},
        ],
        "current_step": 3,
        "step_results": step_results,
        "execution_status": "running",
        "correction_attempts": 0,
    }

    # Verify execution node
    result_update = await verify_execution_node(state)

    # Invariant: Since external dispatch succeeded, needs_correction must be False
    assert result_update["verification_result"]["needs_correction"] is False
    assert result_update.get("execution_status") == "completed"

    # Route after verifier must terminate to __end__, never route back to executor
    state["verification_result"] = result_update["verification_result"]
    state["execution_status"] = result_update["execution_status"]
    route = route_after_verifier(state)
    assert route == "__end__"

    # Even if execution_status was running, successful sensitive dispatch forces __end__
    state["execution_status"] = "running"
    assert route_after_verifier(state) == "__end__"


# ==============================================================================
# 5. Idempotent External Action & Provider Acceptance Distinction
# ==============================================================================


@pytest.mark.asyncio
async def test_idempotent_replay_prevents_duplicate_gmail_dispatch(
    db_session: AsyncSession,
    sample_user: User,
    sample_run: AgentRun,
) -> None:
    """Existing succeeded action returns cached result and does not call execution_fn."""
    idempotency_key = f"{sample_run.id}_step_3_gmail_send_email_abc123"

    # Pre-populate an existing succeeded ExternalAction
    prior_action = ExternalAction(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        run_id=sample_run.id,
        operation="gmail_send_email",
        parameter_digest="abc123digest",
        idempotency_key=idempotency_key,
        status=ExternalActionStatus.SUCCEEDED,
        provider_action_id="1a191772baa36d49",
        provider_response={
            "status": "sent",
            "delivery_status": "api_accepted",
            "message_id": "1a191772baa36d49",
            "recipient": "operator@flowpilot.ai",
        },
    )
    db_session.add(prior_action)
    await db_session.commit()

    # Attempt to execute with the same idempotency key
    mock_exec = AsyncMock()
    result = await _execute_with_action_audit(
        db=db_session,
        user_id=sample_user.id,
        operation="gmail_send_email",
        parameters={
            "to": "operator@flowpilot.ai",
            "subject": "Sales",
            "body": "Report",
            "idempotency_key": idempotency_key,
            "approved": True,
        },
        connection=None,
        run_id=sample_run.id,
        execution_fn=mock_exec,
    )

    # Must be recognized as an idempotent replay
    assert result["idempotent_replay"] is True
    assert result["status"] == "success"
    assert result["provider_action_id"] == "1a191772baa36d49"
    assert result["result"]["delivery_status"] == "api_accepted"
    # Gmail API execution function was NOT called
    assert not mock_exec.called


@pytest.mark.asyncio
async def test_gmail_api_acceptance_distinction_recorded_in_action(
    db_session: AsyncSession,
    sample_user: User,
    sample_run: AgentRun,
) -> None:
    """ExternalAction explicitly records delivery_status='api_accepted' and message_id."""
    expected_message_id = "gmail_msg_xyz_987"

    async def mock_gmail_send() -> tuple[str, dict]:
        return expected_message_id, {
            "status": "sent",
            "delivery_status": "api_accepted",
            "message_id": expected_message_id,
            "recipient": "recipient@example.com",
        }

    result = await _execute_with_action_audit(
        db=db_session,
        user_id=sample_user.id,
        operation="gmail_send_email",
        parameters={
            "to": "recipient@example.com",
            "subject": "Status",
            "body": "Hello",
            "step_id": "step_send",
            "approved": True,
        },
        connection=None,
        run_id=sample_run.id,
        execution_fn=mock_gmail_send,
    )

    assert result["status"] == "success"
    assert result["provider_action_id"] == expected_message_id

    # Verify ExternalAction record in database
    action = (
        await db_session.execute(
            select(ExternalAction).where(ExternalAction.run_id == sample_run.id)
        )
    ).scalar_one()

    assert action.status == ExternalActionStatus.SUCCEEDED
    assert action.provider_action_id == expected_message_id
    assert action.provider_response["delivery_status"] == "api_accepted"
    assert action.provider_response["message_id"] == expected_message_id
