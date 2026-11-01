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
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

# Google Spreadsheet IDs typically consist of 44 alphanumeric characters and hyphens/underscores
SPREADSHEET_ID_REGEX = re.compile(r"^[a-zA-Z0-9-_]{20,100}$")
SPREADSHEET_URL_REGEX = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]{20,100})")


class GoogleSheetsError(Exception):
    """Base exception for Google Sheets API errors."""


class SpreadsheetNotFoundError(GoogleSheetsError):
    """Raised when a spreadsheet cannot be resolved by name or ID."""


class DuplicateSpreadsheetError(GoogleSheetsError):
    """Raised when multiple spreadsheets match a given name."""


class GoogleSheetsClient:
    """Async client for interacting with the Google Sheets v4 and Drive REST APIs."""

    @classmethod
    def extract_spreadsheet_id(cls, value: str | None) -> str | None:
        """Extract Google Spreadsheet ID from either a direct ID or a full Google Sheets URL."""
        if not value:
            return None
        clean = value.strip()
        url_match = SPREADSHEET_URL_REGEX.search(clean)
        if url_match:
            return url_match.group(1)
        if SPREADSHEET_ID_REGEX.match(clean):
            return clean
        return None

    @classmethod
    def validate_spreadsheet_id(cls, spreadsheet_id: str) -> str:
        """Validate format of Google Spreadsheet ID or URL, returning the clean ID."""
        extracted = cls.extract_spreadsheet_id(spreadsheet_id)
        if not extracted:
            raise ValueError(f"Invalid Google Spreadsheet ID or URL: '{spreadsheet_id}'")
        return extracted

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
    async def find_spreadsheet_by_name(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        name: str,
    ) -> str:
        """Find a Google Spreadsheet by its exact name using Google Drive API metadata search.

        Requires minimum necessary scope: 'https://www.googleapis.com/auth/drive.metadata.readonly'
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Spreadsheet name must not be empty.")

        # 1. Check known spreadsheets cache in connection metadata
        known = (connection.metadata_json or {}).get("known_spreadsheets", {})
        for k_name, k_id in known.items():
            if k_name.strip().lower() == clean_name.lower():
                logger.info(
                    "Resolved spreadsheet name '%s' from connection metadata cache to ID '%s'",
                    clean_name,
                    k_id,
                )
                return k_id

        # 2. Check for Drive metadata permissions
        granted = set(connection.granted_scopes or [])
        drive_scopes = {
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive",
        }
        if not granted.intersection(drive_scopes):
            raise OAuthScopeError(
                f"Cannot search for spreadsheet '{clean_name}' by name because Google Drive "
                "metadata scope ('https://www.googleapis.com/auth/drive.metadata.readonly') "
                "is not granted. Please provide the direct Google Spreadsheet URL or ID "
                "(e.g., https://docs.google.com/spreadsheets/d/<ID>/edit), "
                "or re-authorize with Drive access."
            )

        token = await OAuthTokenManager.get_valid_access_token(db, connection)
        escaped_name = clean_name.replace("'", "\\'")
        query = (
            f"name = '{escaped_name}' and "
            "mimeType = 'application/vnd.google-apps.spreadsheet' and "
            "trashed = false"
        )
        params = {
            "q": query,
            "fields": "files(id, name, modifiedTime, webViewLink)",
            "pageSize": 10,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                DRIVE_FILES_URL,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Google access token was rejected by Drive API.")
            if resp.status_code == 403:
                raise OAuthScopeError(
                    f"Google Drive search permission denied ({resp.status_code}): {resp.text}. "
                    f"Please provide the direct spreadsheet URL or ID."
                )
            if resp.status_code != 200:
                raise GoogleSheetsError(
                    f"Google Drive spreadsheet search failed ({resp.status_code}): {resp.text}"
                )

            data = resp.json()
            files = data.get("files", [])

            if len(files) == 0:
                raise SpreadsheetNotFoundError(
                    f"No Google Sheets spreadsheet found with name '{clean_name}'. "
                    "Please check the name or provide the direct spreadsheet URL or ID."
                )
            if len(files) > 1:
                matching_details = [f"'{f.get('name')}' (ID: {f.get('id')})" for f in files]
                msg = (
                    f"Found {len(files)} spreadsheets named '{clean_name}': "
                    f"{', '.join(matching_details)}. To prevent reading the wrong document, "
                    "please specify the exact spreadsheet URL or ID."
                )
                raise DuplicateSpreadsheetError(msg)

            matched_id = files[0].get("id")
            logger.info("Resolved spreadsheet name '%s' to ID '%s'", clean_name, matched_id)

            try:
                meta = dict(connection.metadata_json or {})
                known_map = dict(meta.get("known_spreadsheets", {}))
                known_map[clean_name] = matched_id
                meta["known_spreadsheets"] = known_map
                connection.metadata_json = meta
                await db.commit()
            except Exception as cache_err:
                logger.debug("Could not cache known spreadsheet in metadata: %s", cache_err)

            return matched_id

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
        range_name: str | None = None,
    ) -> dict[str, Any]:
        """Read cell values from a designated A1 range or all worksheets in a Google Sheet."""
        cls._check_scope(connection)
        clean_id = cls.validate_spreadsheet_id(spreadsheet_id)

        # Handle 'all_sheets' or unspecified range: retrieve metadata and read all worksheets
        clean_range = (range_name or "").strip()
        if not clean_range or clean_range.lower() in ("all_sheets", "all", "*"):
            meta = await cls.get_metadata(db, connection, clean_id)
            sheets = meta.get("sheets", [])
            worksheets = []
            all_rows = []

            token = await OAuthTokenManager.get_valid_access_token(db, connection)
            async with httpx.AsyncClient(timeout=20.0) as client:
                for s in sheets:
                    title = s.get("title", "")
                    # Quote sheet name if it contains spaces or special characters
                    quoted_title = f"'{title}'" if (" " in title or "'" in title) else title
                    url = f"{SHEETS_BASE_URL}/{clean_id}/values/{quoted_title}"
                    try:
                        resp = await client.get(
                            url,
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            rows = data.get("values", [])
                            # Limit rows per sheet to 1000 to manage payload size
                            limited_rows = rows[:1000]
                            sheet_result = {
                                "sheet_title": title,
                                "range": data.get("range", quoted_title),
                                "major_dimension": data.get("majorDimension", "ROWS"),
                                "rows": limited_rows,
                                "row_count": len(limited_rows),
                                "is_empty": len(limited_rows) == 0,
                                "total_rows_available": len(rows),
                            }
                            worksheets.append(sheet_result)
                            all_rows.extend(limited_rows)
                        elif resp.status_code == 404:
                            worksheets.append(
                                {
                                    "sheet_title": title,
                                    "rows": [],
                                    "row_count": 0,
                                    "is_empty": True,
                                }
                            )
                        else:
                            logger.warning(
                                "Failed reading worksheet '%s' (%s): %s",
                                title,
                                resp.status_code,
                                resp.text,
                            )
                    except Exception as err:
                        logger.warning("Error fetching worksheet '%s': %s", title, err)

            return {
                "spreadsheet_id": clean_id,
                "title": meta.get("title"),
                "range": "all_sheets",
                "worksheets": worksheets,
                "total_worksheets": len(worksheets),
                "rows": all_rows,
                "row_count": len(all_rows),
            }

        # Single specific range read
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
