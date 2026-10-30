"""Automated integration tests for operational monitoring and system health endpoints."""

from fastapi.testclient import TestClient

from flowpilot.models.user import User


def test_monitoring_health_endpoint_authenticated(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify authenticated monitoring health check returns diagnostic status and metrics."""
    response = client.get("/api/v1/monitoring/health", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()

    # Core health checks
    assert data["database_connected"] is True
    assert "redis_connected" in data
    assert "celery_queue_depth" in data

    # Run metrics distribution
    metrics = data["runs_by_status"]
    assert "pending" in metrics
    assert "queued" in metrics
    assert "running" in metrics
    assert "awaiting_approval" in metrics
    assert "completed" in metrics
    assert "failed" in metrics
    assert "cancelled" in metrics


def test_monitoring_health_endpoint_unauthenticated_rejected(
    client: TestClient,
) -> None:
    """Verify unauthenticated requests to monitoring endpoints are rejected with 401."""
    response = client.get("/api/v1/monitoring/health")
    assert response.status_code == 401
