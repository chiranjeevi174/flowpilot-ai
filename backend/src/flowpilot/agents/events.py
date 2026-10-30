"""Helper utilities for agent JSON extraction and audit event persistence."""

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.models.agent_event import AgentEvent

logger = get_logger("agents.events")


def extract_json_payload(content: str) -> dict[str, Any]:
    """Robustly extract and parse a JSON dictionary from an LLM response string."""
    text = content.strip()
    # Strip markdown code blocks if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Fallback: search for outermost curly brackets
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = text[start_idx : end_idx + 1]
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data

    raise ValueError(f"Could not extract a valid JSON dictionary from LLM output: {content[:200]}")


def publish_redis_event(run_id: str, event_data: dict[str, Any]) -> None:
    """Publish real-time notification to Redis Pub/Sub channel for SSE stream consumers."""
    try:
        import redis

        from flowpilot.core.config import get_settings

        settings = get_settings()
        r = redis.Redis.from_url(settings.REDIS_URL)
        channel = f"run:{run_id}:events"
        r.publish(channel, json.dumps(event_data, default=str))
    except Exception as exc:
        logger.debug("Redis event publish skipped/failed: %s", exc)


async def record_event(
    db: AsyncSession,
    run_id: str | uuid.UUID,
    agent_name: str,
    event_type: str,
    event_payload: dict[str, Any],
) -> AgentEvent:
    """Persist a telemetry/audit event for an agent run into PostgreSQL.

    Ensures that no sensitive secrets (API keys, raw tokens) are ever stored,
    and notifies real-time SSE stream listeners via Redis Pub/Sub.
    """
    clean_payload = dict(event_payload)
    # Defense-in-depth: strip any accidental keys containing sensitive credentials
    for key in list(clean_payload.keys()):
        if any(
            secret_term in key.lower() for secret_term in ("api_key", "password", "token", "secret")
        ):
            clean_payload[key] = "[REDACTED]"

    parsed_run_id = uuid.UUID(str(run_id))
    event = AgentEvent(
        id=uuid.uuid4(),
        run_id=parsed_run_id,
        agent_name=agent_name,
        event_type=event_type,
        event_payload=clean_payload,
    )
    db.add(event)
    try:
        await db.commit()
        # Publish event to Redis Pub/Sub for active SSE subscribers
        publish_redis_event(
            str(parsed_run_id),
            {
                "id": str(event.id),
                "run_id": str(parsed_run_id),
                "agent_name": agent_name,
                "event_type": event_type,
                "event_payload": clean_payload,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            },
        )
    except Exception as exc:
        logger.warning("Failed to commit event %s for run %s: %s", event_type, run_id, exc)
        await db.rollback()
    return event
