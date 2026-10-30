"""Google Sheets API integration adapter using the official Google Sheets v4 REST API."""

import re
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.integrations.oauth import (
    OAuthAuthenticationError,
    OAuthScopeError,
    OAuthTokenManager,
)
from flowpilot.integrations.security import sanitize_sheet_rows
from flowpilot.models.integration_connection import IntegrationConnection

logger = get_logger("integrations.google.sheets")

SHEETS_BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"

# Google Spreadsheet IDs typically consist of 44 alphanumeric characters and hyphens/underscores
SPREADSHEET_ID_REGEX = re.compile(r"^[a-zA-Z0-9-_]{20,100}$")


class GoogleSheetsError(Exception):
    """Base exception for Google Sheets API errors."""


class GoogleSheetsClient:
    """Async client for interacting with the Google Sheets v4 REST API."""

    @classmethod
    def validate_spreadsheet_id(cls, spreadsheet_id: str) -> str:
        """Validate format of Google Spreadsheet ID."""
        clean = spreadsheet_id.strip()
        if not SPREADSHEET_ID_REGEX.match(clean):
            raise ValueError(f"Invalid Google Spreadsheet ID: '{spreadsheet_id}'")
        return clean

    @classmethod
    def _check_scope(cls, connection: IntegrationConnection) -> None:
        """Ensure connection has been granted Google Sheets OAuth permissions."""
        granted = set(connection.granted_scopes or [])
        required = "https://www.googleapis.com/auth/spreadsheets"
        if required not in granted:
            msg = (
                f"Missing required Google Sheets scope: '{required}'. "
                f"Connection has scopes: {sorted(granted)}"
            )
            logger.warning(msg)
            raise OAuthScopeError(msg)

    @classmethod
    async def get_metadata(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        spreadsheet_id: str,
    ) -> dict[str, Any]:
        """Retrieve spreadsheet title and sheets properties."""
        cls._check_scope(connection)
        clean_id = cls.validate_spreadsheet_id(spreadsheet_id)
        token = await OAuthTokenManager.get_valid_access_token(db, connection)

        url = f"{SHEETS_BASE_URL}/{clean_id}"
        params = {"fields": "spreadsheetId,properties.title,sheets.properties"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Sheets access token was rejected by Google API.")
            if resp.status_code == 404:
                raise GoogleSheetsError(f"Spreadsheet '{clean_id}' not found.")
            if resp.status_code != 200:
                raise GoogleSheetsError(
                    f"Failed to fetch spreadsheet metadata ({resp.status_code}): {resp.text}"
                )

            data = resp.json()
            sheets = [
                {
                    "sheet_id": s.get("properties", {}).get("sheetId"),
                    "title": s.get("properties", {}).get("title"),
                    "index": s.get("properties", {}).get("index"),
                }
                for s in data.get("sheets", [])
            ]
            return {
                "spreadsheet_id": data.get("spreadsheetId"),
                "title": data.get("properties", {}).get("title"),
                "sheets": sheets,
            }

    @classmethod
    async def read_range(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        spreadsheet_id: str,
        range_name: str,
    ) -> dict[str, Any]:
        """Read cell values from a designated A1 range in a Google Sheet."""
        cls._check_scope(connection)
        clean_id = cls.validate_spreadsheet_id(spreadsheet_id)
        clean_range = range_name.strip()
        if not clean_range:
            raise ValueError("Range name must not be empty.")

        token = await OAuthTokenManager.get_valid_access_token(db, connection)
        url = f"{SHEETS_BASE_URL}/{clean_id}/values/{clean_range}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Sheets access token was rejected by Google API.")
            if resp.status_code == 404:
                msg = f"Spreadsheet '{clean_id}' or range '{clean_range}' not found."
                raise GoogleSheetsError(msg)
            if resp.status_code != 200:
                raise GoogleSheetsError(
                    f"Google Sheets read failed ({resp.status_code}): {resp.text}"
                )

            data = resp.json()
            rows = data.get("values", [])
            return {
                "spreadsheet_id": clean_id,
                "range": data.get("range", clean_range),
                "major_dimension": data.get("majorDimension", "ROWS"),
                "rows": rows,
                "row_count": len(rows),
            }

    @classmethod
    async def append_rows(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
    ) -> dict[str, Any]:
        """Append rows to a designated range in a Google Sheet with formula injection protection.

        Mandatory Human Approval Gate: This write operation requires explicit human approval.
        Every cell value is sanitized to neutralize potential CSV / formula injection vectors.
        """
        cls._check_scope(connection)
        clean_id = cls.validate_spreadsheet_id(spreadsheet_id)
        clean_range = range_name.strip()
        if not clean_range:
            raise ValueError("Range name must not be empty.")
        if not values or not isinstance(values, list):
            raise ValueError("Values must be a non-empty list of rows.")

        # Formula injection neutralization
        sanitized_values = sanitize_sheet_rows(values)

        token = await OAuthTokenManager.get_valid_access_token(db, connection)
        url = f"{SHEETS_BASE_URL}/{clean_id}/values/{clean_range}:append"
        params = {
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
        }
        payload = {
            "range": clean_range,
            "majorDimension": "ROWS",
            "values": sanitized_values,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                params=params,
                json=payload,
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Sheets access token was rejected by Google API.")
            if resp.status_code not in (200, 201):
                raise GoogleSheetsError(
                    f"Google Sheets append failed ({resp.status_code}): {resp.text}"
                )

            data = resp.json()
            updates = data.get("updates", {})
            return {
                "spreadsheet_id": clean_id,
                "table_range": updates.get("tableRange"),
                "updated_range": updates.get("updatedRange"),
                "updated_rows": updates.get("updatedRows", len(sanitized_values)),
                "updated_columns": updates.get("updatedColumns"),
                "updated_cells": updates.get("updatedCells"),
                "status": "appended",
            }
