"""Regression test suite for Google Sheets workflow planning and parameter resolution."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.resolution import format_step_output_as_text, resolve_step_placeholders
from flowpilot.integrations.google.sheets import (
    DuplicateSpreadsheetError,
    GoogleSheetsClient,
    SpreadsheetNotFoundError,
)
from flowpilot.integrations.oauth import OAuthScopeError
from flowpilot.integrations.registry import execute_sheets_read_range
from flowpilot.integrations.security import encrypt_oauth_token
from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_run import AgentRunStatus
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User
from flowpilot.workflows.engine import WorkflowEngine


@pytest.fixture
async def full_google_connection(
    db_session: AsyncSession,
    registered_user: User,
) -> IntegrationConnection:
    """Create an active Google integration connection with Sheets, Drive, and Gmail scopes."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="sheets",
        external_account_id="operator@flowpilot.ai",
        external_account_name="FlowPilot Operator",
        encrypted_access_token=encrypt_oauth_token("mock_google_full_token"),
        granted_scopes=[
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        status=ConnectionStatus.ACTIVE,
        is_default=True,
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return conn


@pytest.mark.asyncio
async def test_spreadsheet_name_resolution(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
) -> None:
    """1. Resolve spreadsheet by name using Google Drive API."""
    mock_drive_response = {
        "files": [
            {
                "id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
                "name": "Sample data",
                "mimeType": "application/vnd.google-apps.spreadsheet",
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_drive_response)

        sheet_id = await GoogleSheetsClient.find_spreadsheet_by_name(
            db=db_session,
            connection=full_google_connection,
            name="Sample data",
        )

        assert sheet_id == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        assert mock_get.called
        call_params = mock_get.call_args[1]["params"]
        assert "name = 'Sample data'" in call_params["q"]


@pytest.mark.asyncio
async def test_direct_spreadsheet_url_and_id_input(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
) -> None:
    """2. Direct spreadsheet URL and ID input handling."""
    direct_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    full_url = f"https://docs.google.com/spreadsheets/d/{direct_id}/edit#gid=0"

    # Direct ID extraction
    assert GoogleSheetsClient.extract_spreadsheet_id(direct_id) == direct_id
    # URL extraction
    assert GoogleSheetsClient.extract_spreadsheet_id(full_url) == direct_id

    # Execution with URL in spreadsheet_id
    mock_sheet_data = {
        "range": "Sheet1!A1:B2",
        "majorDimension": "ROWS",
        "values": [["Col1", "Col2"], ["Val1", "Val2"]],
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_sheet_data)

        res = await execute_sheets_read_range(
            db=db_session,
            user_id=full_google_connection.user_id,
            parameters={"spreadsheet_id": full_url, "range": "Sheet1!A1:B2"},
        )
        assert res["operation"] == "sheets_read_range"
        assert res["result"]["spreadsheet_id"] == direct_id
        assert len(res["result"]["rows"]) == 2


@pytest.mark.asyncio
async def test_duplicate_spreadsheet_names_rejection(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
) -> None:
    """3. Duplicate spreadsheet names must raise DuplicateSpreadsheetError."""
    mock_drive_response = {
        "files": [
            {"id": "doc_id_11111111111111111111", "name": "Sample data"},
            {"id": "doc_id_22222222222222222222", "name": "Sample data"},
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_drive_response)

        with pytest.raises(DuplicateSpreadsheetError) as exc_info:
            await GoogleSheetsClient.find_spreadsheet_by_name(
                db=db_session,
                connection=full_google_connection,
                name="Sample data",
            )

        err_msg = str(exc_info.value)
        assert "Found 2 spreadsheets named 'Sample data'" in err_msg
        assert "doc_id_11111111111111111111" in err_msg
        assert "doc_id_22222222222222222222" in err_msg


@pytest.mark.asyncio
async def test_missing_spreadsheet_not_found(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
) -> None:
    """4. Missing spreadsheet raises SpreadsheetNotFoundError."""
    mock_drive_response = {"files": []}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_drive_response)

        with pytest.raises(SpreadsheetNotFoundError, match="No Google Sheets spreadsheet found"):
            await GoogleSheetsClient.find_spreadsheet_by_name(
                db=db_session,
                connection=full_google_connection,
                name="Nonexistent Data",
            )


@pytest.mark.asyncio
async def test_multiple_worksheets_read_all_sheets(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
) -> None:
    """5. Multiple worksheets retrieval with range='all_sheets'."""
    sheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

    meta_response = {
        "spreadsheetId": sheet_id,
        "properties": {"title": "Sample data"},
        "sheets": [
            {"properties": {"sheetId": 0, "title": "Quarterly Sales"}},
            {"properties": {"sheetId": 1, "title": "Empty Sheet"}},
        ],
    }
    sales_data = {
        "range": "'Quarterly Sales'!A1:B3",
        "majorDimension": "ROWS",
        "values": [
            ["Quarter", "Revenue"],
            ["Q1", "$100,000"],
            ["Q2", "$120,000"],
        ],
    }
    empty_data = {
        "range": "'Empty Sheet'!A1:Z",
        "majorDimension": "ROWS",
        "values": [],
    }

    async def mock_get(url, *args, **kwargs):
        if url.endswith(f"/spreadsheets/{sheet_id}"):
            return httpx.Response(200, json=meta_response)
        if "Quarterly%20Sales" in url or "Quarterly Sales" in url:
            return httpx.Response(200, json=sales_data)
        if "Empty%20Sheet" in url or "Empty Sheet" in url:
            return httpx.Response(200, json=empty_data)
        return httpx.Response(404)

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        res = await GoogleSheetsClient.read_range(
            db=db_session,
            connection=full_google_connection,
            spreadsheet_id=sheet_id,
            range_name="all_sheets",
        )

        assert res["range"] == "all_sheets"
        assert res["total_worksheets"] == 2
        worksheets = res["worksheets"]
        assert worksheets[0]["sheet_title"] == "Quarterly Sales"
        assert worksheets[0]["is_empty"] is False
        assert worksheets[0]["row_count"] == 3
        assert worksheets[1]["sheet_title"] == "Empty Sheet"
        assert worksheets[1]["is_empty"] is True
        assert worksheets[1]["row_count"] == 0


@pytest.mark.asyncio
async def test_missing_required_parameters_rejection(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
) -> None:
    """6. Rejection when neither spreadsheet_id nor spreadsheet_name is supplied."""
    with pytest.raises(ValueError, match="spreadsheet_id.*spreadsheet_name.*required"):
        await execute_sheets_read_range(
            db=db_session,
            user_id=full_google_connection.user_id,
            parameters={"range": "all_sheets"},
        )


@pytest.mark.asyncio
async def test_google_authorization_scope_failures(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """7. Authorization failures when required scopes are missing."""
    # Connection lacking Drive metadata scope
    sheets_only_conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="sheets",
        encrypted_access_token=encrypt_oauth_token("mock_token"),
        granted_scopes=["https://www.googleapis.com/auth/spreadsheets"],
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(sheets_only_conn)
    await db_session.commit()

    with pytest.raises(OAuthScopeError, match="drive.metadata.readonly"):
        await GoogleSheetsClient.find_spreadsheet_by_name(
            db=db_session,
            connection=sheets_only_conn,
            name="Sample data",
        )


def test_placeholder_resolution_and_data_propagation() -> None:
    """8. Correct propagation of retrieved spreadsheet data between LangGraph steps."""
    step_results = [
        {
            "step_id": "step_1",
            "operation": "sheets_read_range",
            "status": "success",
            "result": {
                "spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
                "worksheets": [
                    {
                        "sheet_title": "Customers",
                        "row_count": 2,
                        "rows": [["ID", "Name", "Plan"], ["1", "Acme Corp", "Enterprise"]],
                    }
                ],
            },
        },
        {
            "step_id": "step_2",
            "operation": "task_summary_generation",
            "status": "success",
            "result": {
                "summary": (
                    "Sample data contains 1 customer record for Acme Corp on Enterprise plan."
                ),
                "key_highlights": ["Acme Corp is an Enterprise client."],
            },
        },
    ]

    # Test formatting step 1 output into tabular text
    sheet_text = format_step_output_as_text(step_results[0]["result"])
    assert "Worksheet: 'Customers'" in sheet_text
    assert "Acme Corp" in sheet_text

    # Test resolving step 3 Gmail parameters referencing step 2
    raw_params = {
        "recipient": None,
        "subject": "",
        "body": "output_from_step_2",
    }
    resolved = resolve_step_placeholders(
        parameters=raw_params,
        step_results=step_results,
        user_email="operator@flowpilot.ai",
        operation="gmail_send_email",
    )

    assert resolved["recipient"] == "operator@flowpilot.ai"
    assert "Acme Corp" in resolved["body"]
    assert "Executive Summary:" in resolved["body"]


@pytest.mark.asyncio
async def test_workflow_blocks_gmail_after_upstream_failure(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
    registered_user: User,
) -> None:
    """9. Upstream failure blocks execution; approval gate is never called."""
    checkpointer = MemorySaver()

    # Mock planner to propose sheets_read_range -> task_summary -> gmail_send_email
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "sheets_workflow",
                "action": "sheets_read_range",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {"spreadsheet_name": "Sample data"},
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
                        "operation": "sheets_read_range",
                        "parameters": {
                            "spreadsheet_name": "Sample data",
                            "range": "all_sheets",
                        },
                        "required_capability": "sheets_read_range",
                        "approval_required": False,
                        "expected_outcome": "Read spreadsheet contents",
                    },
                    {
                        "step_id": "step_2",
                        "operation": "task_summary_generation",
                        "parameters": {"text": "output_from_step_1"},
                        "required_capability": "task_summary_generation",
                        "approval_required": False,
                        "expected_outcome": "Summary of spreadsheet contents",
                    },
                    {
                        "step_id": "step_3",
                        "operation": "gmail_send_email",
                        "parameters": {
                            "body": "output_from_step_2",
                            "subject": "Sample data Analysis",
                        },
                        "required_capability": "gmail_send_email",
                        "approval_required": True,
                        "expected_outcome": "Send email with summary",
                    },
                ],
                "unsupported_capability": False,
                "unsupported_reason": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    async def mock_llm_gen(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        if "Planning" in sys_msg:
            return plan_resp
        return GatewayGenerationResult(
            content="{}", provider="gemini", model="gemini-2.5-flash", latency_ms=50
        )

    # Simulate Drive API returning 0 spreadsheets (NotFoundError)
    mock_drive_empty = {"files": []}

    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_llm_gen),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_http_get,
        patch(
            "flowpilot.integrations.google.gmail.GmailClient.send_email", new_callable=AsyncMock
        ) as mock_send_email,
    ):
        mock_http_get.return_value = httpx.Response(200, json=mock_drive_empty)

        req = (
            "Find my connected Google Sheets spreadsheet named Sample data, "
            "analyze its contents, and email the results."
        )
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=registered_user.id,
            request=req,
            checkpointer=checkpointer,
        )

        # Run must have failed at Step 1
        assert run.status == AgentRunStatus.FAILED
        assert run.error_message is not None
        assert "No Google Sheets spreadsheet found with name 'Sample data'" in run.error_message
        # Email MUST NOT have been sent
        assert not mock_send_email.called


@pytest.mark.asyncio
async def test_workflow_reaches_approval_gate_with_grounded_email(
    db_session: AsyncSession,
    full_google_connection: IntegrationConnection,
    registered_user: User,
) -> None:
    """10 & 11. Workflow pauses at Gmail approval gate with grounded body, then completes."""
    checkpointer = MemorySaver()

    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "sheets_workflow",
                "action": "sheets_read_range",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {"spreadsheet_name": "Sample data"},
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
                        "operation": "sheets_read_range",
                        "parameters": {
                            "spreadsheet_name": "Sample data",
                            "range": "all_sheets",
                        },
                        "required_capability": "sheets_read_range",
                        "approval_required": False,
                        "expected_outcome": "Read spreadsheet contents",
                    },
                    {
                        "step_id": "step_2",
                        "operation": "task_summary_generation",
                        "parameters": {"text": "output_from_step_1"},
                        "required_capability": "task_summary_generation",
                        "approval_required": False,
                        "expected_outcome": "Executive summary of spreadsheet",
                    },
                    {
                        "step_id": "step_3",
                        "operation": "gmail_send_email",
                        "parameters": {
                            "body": "output_from_step_2",
                            "subject": "Professional Analysis of Sample data",
                        },
                        "required_capability": "gmail_send_email",
                        "approval_required": True,
                        "expected_outcome": "Send professional email",
                    },
                ],
                "unsupported_capability": False,
                "unsupported_reason": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    summary_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "summary": "Sample data reveals Q1 revenue of $100k and Q2 revenue of $120k.",
                "key_highlights": ["20% quarter-over-quarter revenue growth"],
                "next_steps": ["Maintain current sales trajectory"],
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "Workflow executed successfully and summary email dispatched.",
                "missing_outputs": [],
                "needs_correction": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    async def mock_llm_gen(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        if "Planning" in sys_msg:
            return plan_resp
        if "senior workflow analyst" in sys_msg or "Executive" in sys_msg or "Summary" in sys_msg:
            return summary_resp
        if "Verification" in sys_msg:
            return verifier_resp
        return summary_resp

    # HTTP mocks for Google Drive & Sheets API
    sheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    drive_search_data = {"files": [{"id": sheet_id, "name": "Sample data"}]}
    sheets_meta_data = {
        "spreadsheetId": sheet_id,
        "properties": {"title": "Sample data"},
        "sheets": [{"properties": {"sheetId": 0, "title": "Revenue"}}],
    }
    sheets_values_data = {
        "range": "Revenue!A1:B3",
        "majorDimension": "ROWS",
        "values": [["Quarter", "Revenue"], ["Q1", "$100,000"], ["Q2", "$120,000"]],
    }

    async def mock_http_get(url, *args, **kwargs):
        if "drive/v3/files" in url:
            return httpx.Response(200, json=drive_search_data)
        if url.endswith(f"/spreadsheets/{sheet_id}"):
            return httpx.Response(200, json=sheets_meta_data)
        return httpx.Response(200, json=sheets_values_data)

    gmail_mock_response = {
        "id": "18a1b2c3d4e5f678",
        "threadId": "18a1b2c3d4e5f678",
        "recipient": registered_user.email,
        "subject": "Professional Analysis of Sample data",
        "status": "sent",
    }

    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_llm_gen),
        patch("httpx.AsyncClient.get", side_effect=mock_http_get),
        patch(
            "flowpilot.integrations.google.gmail.GmailClient.send_email", new_callable=AsyncMock
        ) as mock_send,
    ):
        mock_send.return_value = gmail_mock_response

        req = (
            "Find my connected Google Sheets spreadsheet named Sample data, "
            "analyze its contents, and email the results."
        )
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=registered_user.id,
            request=req,
            checkpointer=checkpointer,
        )

        # Verification 1: Must be paused at AWAITING_APPROVAL
        assert run.status == AgentRunStatus.AWAITING_APPROVAL
        # Verification 2: Non-sensitive steps (1 and 2) MUST have succeeded before pausing!
        assert run.execution_plan is not None
        # Email MUST NOT have been sent before human approval!
        assert not mock_send.called

        # Phase 2: Resume with approval
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=registered_user.id,
            decision="approve",
            comment="Approved by user review.",
            checkpointer=checkpointer,
        )

        # Verification 3: Workflow successfully completed after approval!
        assert resumed_run.status == AgentRunStatus.COMPLETED
        # Verification 4: Gmail send email executed with authorized parameters
        assert mock_send.called
        send_kwargs = mock_send.call_args[1]
        assert send_kwargs["recipient"] == registered_user.email
        assert (
            "Q1 revenue" in send_kwargs["body_text"] or "revenue growth" in send_kwargs["body_text"]
        )


def test_deterministic_numerical_analysis_sample_data() -> None:
    """12. Deterministic arithmetic calculation on Sample data records."""
    from flowpilot.agents.analysis import analyze_tabular_dataset

    sample_rows = [
        ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
        ["1001", "2026-01-05", "North", "Sarah", "Laptop", "12", "650"],
        ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
    ]

    analysis = analyze_tabular_dataset(sample_rows, sheet_title="Sheet1")

    assert analysis.data_row_count == 2
    assert analysis.total_units == 22
    assert analysis.cost_column_sum == 830
    assert analysis.per_unit_combined_total == 9600
    assert analysis.currency_detected is None
    assert "NOT established" in analysis.currency_note
    assert analysis.date_range_note is not None
    assert "2026-01-05 to 2026-01-06" in analysis.date_range_note
    assert len(analysis.computed_order_totals) == 2
    assert analysis.computed_order_totals[0]["calculated_total"] == 7800
    assert analysis.computed_order_totals[1]["calculated_total"] == 1800


def test_numerical_regression_prevention_8300() -> None:
    """13. Regression defense against previously reported 8,300 calculation error."""
    from flowpilot.agents.analysis import (
        analyze_tabular_dataset,
        rectify_text_numbers,
        validate_summary_accuracy,
    )

    sample_rows = [
        ["Order ID", "Date", "Region", "Rep", "Item", "Units", "Cost"],
        ["1001", "2026-01-05", "North", "Sarah", "Laptop", "12", "650"],
        ["1002", "2026-01-06", "East", "Chinnu", "Monitor", "10", "180"],
    ]
    analysis = analyze_tabular_dataset(sample_rows)

    bad_summary = (
        "The dataset contains two recent orders from January 2026, totaling 22 units "
        "with a combined cost of $8,300."
    )

    errors = validate_summary_accuracy(bad_summary, analysis)
    assert len(errors) >= 2
    assert any("8,300" in e for e in errors)
    assert any("unauthorized currency symbol" in e.lower() for e in errors)

    rectified = rectify_text_numbers(bad_summary, analysis)
    assert "8,300" not in rectified
    assert "9,600" in rectified
    assert "$8,300" not in rectified
    assert "recent orders from January 2026" not in rectified


def test_missing_values_and_zero_distinction() -> None:
    """14. Robust handling of missing vs zero values in tabular analysis."""
    from flowpilot.agents.analysis import analyze_tabular_dataset

    rows = [
        ["Product", "Units", "Cost"],
        ["Widget A", "5", "100"],
        ["Widget B", "", "50"],  # Missing units
        ["Widget C", "0", "20"],  # Explicit zero units
        ["Widget D", "N/A", "0"],  # Non-numeric text & zero cost
    ]

    analysis = analyze_tabular_dataset(rows, sheet_title="Inventory")
    units_col = analysis.columns["Units"]
    assert units_col.missing_count == 1
    assert units_col.zero_count == 1
    assert units_col.sum_val == 5  # 5 + 0 = 5

    cost_col = analysis.columns["Cost"]
    assert cost_col.zero_count == 1
    assert cost_col.sum_val == 170  # 100 + 50 + 20 + 0 = 170


def test_explicit_recipient_preservation() -> None:
    """15. Explicit email recipient is never clobbered by authenticated user default."""
    from flowpilot.agents.resolution import resolve_step_placeholders

    step_results = [
        {"step_id": "step_1", "operation": "sheets_read_range", "result": {"rows": []}},
        {
            "step_id": "step_2",
            "operation": "task_summary_generation",
            "result": {"summary": "Done"},
        },
    ]

    # Case A: to specified explicitly
    params_a = {
        "recipient": "authenticated_user",
        "to": "target@example.com",
        "body": "output_from_step_2",
    }
    resolved_a = resolve_step_placeholders(
        parameters=params_a,
        step_results=step_results,
        user_email="operator@flowpilot.ai",
        operation="gmail_send_email",
    )
    assert resolved_a["recipient"] == "target@example.com"

    # Case B: recipient specified explicitly
    params_b = {
        "recipient": "target@example.com",
        "body": "output_from_step_2",
    }
    resolved_b = resolve_step_placeholders(
        parameters=params_b,
        step_results=step_results,
        user_email="operator@flowpilot.ai",
        operation="gmail_send_email",
    )
    assert resolved_b["recipient"] == "target@example.com"

    # Case C: No explicit recipient -> falls back to user_email
    params_c = {
        "recipient": "authenticated_user",
        "body": "output_from_step_2",
    }
    resolved_c = resolve_step_placeholders(
        parameters=params_c,
        step_results=step_results,
        user_email="operator@flowpilot.ai",
        operation="gmail_send_email",
    )
    assert resolved_c["recipient"] == "operator@flowpilot.ai"


def test_google_oauth_reauthorization_url_generation() -> None:
    """16. Google OAuth URL includes Drive metadata and Sheets scopes."""
    from flowpilot.integrations.google.oauth import GoogleOAuth

    scopes = GoogleOAuth.get_service_scopes("sheets")
    assert "https://www.googleapis.com/auth/spreadsheets" in scopes
    assert "https://www.googleapis.com/auth/drive.metadata.readonly" in scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in scopes

    url, state, verifier = GoogleOAuth.get_authorization_url(
        user_id=uuid.uuid4(),
        service="sheets",
        client_id="mock_client_id.apps.googleusercontent.com",
        redirect_uri="http://localhost:8000/api/v1/integrations/google/callback",
    )
    assert "drive.metadata.readonly" in url
    assert "spreadsheets" in url
    assert "prompt=consent" in url
    assert "access_type=offline" in url
    assert state
    assert verifier
