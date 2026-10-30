"""Automated tests for Google Sheets v4 adapter, range reads, appends, and formula sanitization."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.integrations.google.sheets import GoogleSheetsClient, GoogleSheetsError
from flowpilot.integrations.oauth import OAuthScopeError
from flowpilot.integrations.security import encrypt_oauth_token
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User


@pytest.fixture
async def sheets_connection(
    db_session: AsyncSession,
    registered_user: User,
) -> IntegrationConnection:
    """Create an active Google Sheets integration connection."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="sheets",
        external_account_id="sheets_tester@gmail.com",
        encrypted_access_token=encrypt_oauth_token("mock_sheets_access_token"),
        granted_scopes=["https://www.googleapis.com/auth/spreadsheets"],
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return conn


@pytest.mark.asyncio
async def test_sheets_validate_spreadsheet_id() -> None:
    """Verify spreadsheet ID format validation."""
    valid_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert GoogleSheetsClient.validate_spreadsheet_id(valid_id) == valid_id

    with pytest.raises(ValueError, match="Invalid Google Spreadsheet ID"):
        GoogleSheetsClient.validate_spreadsheet_id("too-short")

    with pytest.raises(ValueError, match="Invalid Google Spreadsheet ID"):
        GoogleSheetsClient.validate_spreadsheet_id("invalid character!!@#$")


@pytest.mark.asyncio
async def test_sheets_read_range_success(
    db_session: AsyncSession,
    sheets_connection: IntegrationConnection,
) -> None:
    """Verify reading a cell range returns values and dimensions."""
    spreadsheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    mock_resp = {
        "range": "Sheet1!A1:C2",
        "majorDimension": "ROWS",
        "values": [
            ["Item", "Quantity", "Price"],
            ["Widget A", "10", "$5.00"],
        ],
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_resp)

        res = await GoogleSheetsClient.read_range(
            db=db_session,
            connection=sheets_connection,
            spreadsheet_id=spreadsheet_id,
            range_name="Sheet1!A1:C2",
        )

        assert res["range"] == "Sheet1!A1:C2"
        assert len(res["rows"]) == 2
        assert res["rows"][0] == ["Item", "Quantity", "Price"]


@pytest.mark.asyncio
async def test_sheets_read_range_missing_scope(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify reading without spreadsheets scope raises OAuthScopeError."""
    narrow_conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="sheets",
        encrypted_access_token=encrypt_oauth_token("mock_token"),
        granted_scopes=["https://www.googleapis.com/auth/userinfo.email"],
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(narrow_conn)
    await db_session.commit()

    with pytest.raises(OAuthScopeError, match="Missing required Google Sheets scope"):
        await GoogleSheetsClient.read_range(
            db_session,
            narrow_conn,
            "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            "A1:B2",
        )


@pytest.mark.asyncio
async def test_sheets_append_rows_with_formula_sanitization(
    db_session: AsyncSession,
    sheets_connection: IntegrationConnection,
) -> None:
    """Verify appending rows sanitizes dangerous formula injection characters."""
    spreadsheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    raw_rows = [
        ["Alice", 25, "=SUM(A1:A5)"],
        ["Bob", "+100", "-50"],
    ]

    mock_append_resp = {
        "spreadsheetId": spreadsheet_id,
        "tableRange": "Sheet1!A1:C1",
        "updates": {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": "Sheet1!A2:C3",
            "updatedRows": 2,
            "updatedColumns": 3,
            "updatedCells": 6,
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, json=mock_append_resp)

        res = await GoogleSheetsClient.append_rows(
            db=db_session,
            connection=sheets_connection,
            spreadsheet_id=spreadsheet_id,
            range_name="Sheet1!A1",
            values=raw_rows,
        )

        assert res["status"] == "appended"
        assert res["updated_rows"] == 2
        assert mock_post.called

        # Inspect the json payload that was sent to httpx
        call_kwargs = mock_post.call_args[1]
        sent_payload = call_kwargs["json"]
        sent_values = sent_payload["values"]

        # Verify formula prefixes were neutralized with leading single quote
        assert sent_values[0][2] == "'=SUM(A1:A5)"
        assert sent_values[1][1] == "'+100"
        assert sent_values[1][2] == "'-50"


@pytest.mark.asyncio
async def test_sheets_get_metadata_success(
    db_session: AsyncSession,
    sheets_connection: IntegrationConnection,
) -> None:
    """Verify fetching spreadsheet metadata returns sheets list."""
    spreadsheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    mock_meta_resp = {
        "spreadsheetId": spreadsheet_id,
        "properties": {"title": "Quarterly Financials"},
        "sheets": [
            {"properties": {"sheetId": 0, "title": "Summary", "index": 0}},
            {"properties": {"sheetId": 12345, "title": "Q1 Breakdown", "index": 1}},
        ],
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_meta_resp)

        meta = await GoogleSheetsClient.get_metadata(
            db_session,
            sheets_connection,
            spreadsheet_id,
        )

        assert meta["title"] == "Quarterly Financials"
        assert len(meta["sheets"]) == 2
        assert meta["sheets"][0]["title"] == "Summary"


@pytest.mark.asyncio
async def test_sheets_provider_error_raises_googlesheetserror(
    db_session: AsyncSession,
    sheets_connection: IntegrationConnection,
) -> None:
    """Verify 404 from Google Sheets API raises GoogleSheetsError."""
    spreadsheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(404, text="Requested entity was not found.")

        with pytest.raises(GoogleSheetsError, match="not found"):
            await GoogleSheetsClient.read_range(
                db_session,
                sheets_connection,
                spreadsheet_id,
                "NonExistent!A1",
            )
