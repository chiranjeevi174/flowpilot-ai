"""Automated tests for application lifecycle and health endpoint."""

import pytest
from fastapi.testclient import TestClient

from flowpilot.core.config import get_settings
from flowpilot.main import app, create_app


@pytest.fixture
def client() -> TestClient:
    """Fixture providing a TestClient configured with the FastAPI app."""
    return TestClient(app)


def test_app_initialization() -> None:
    """Test that the application factory successfully creates an app with configured metadata."""
    instance = create_app()
    settings = get_settings()
    assert instance.title == settings.APP_NAME
    assert instance.version == settings.APP_VERSION
    assert instance.docs_url == "/docs"


def test_health_endpoint_returns_200(client: TestClient) -> None:
    """Test that GET /api/v1/health returns HTTP 200 status code."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_endpoint_response_json(client: TestClient) -> None:
    """Test that GET /api/v1/health returns the expected JSON payload."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data == {
        "status": "healthy",
        "service": "flowpilot-api",
        "version": "1.0.0",
    }


def test_undefined_endpoint_returns_404(client: TestClient) -> None:
    """Test that requesting an undefined endpoint returns HTTP 404 status code."""
    response = client.get("/api/v1/nonexistent-endpoint")
    assert response.status_code == 404
