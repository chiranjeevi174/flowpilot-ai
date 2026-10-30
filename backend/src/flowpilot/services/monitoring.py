"""Operational monitoring service gathering queue depth, run counts, and infrastructure health."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.workflow_outbox import OutboxStatus, WorkflowOutbox
from flowpilot.schemas.monitoring import MonitoringHealthResponse

logger = get_logger("services.monitoring")
settings = get_settings()


class MonitoringService:
    """Aggregates operational metrics for worker health, queue depths, and execution metrics."""

    @classmethod
    async def get_system_health(
        cls, db: AsyncSession, user_id: uuid.UUID | None = None
    ) -> MonitoringHealthResponse:
        """Query PostgreSQL and Redis to build an operational readiness report scoped to user."""
        now_utc = datetime.now(UTC)

        # 1. Check PostgreSQL readiness
        db_connected = False
        try:
            await db.execute(text("SELECT 1"))
            db_connected = True
        except Exception as exc:
            logger.warning("Database connectivity check failed: %s", exc)

        # 2. Check Redis and Celery queue depth
        redis_connected = False
        queue_depth = 0
        try:
            import redis

            r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2.0)
            redis_connected = bool(r.ping())
            # Default celery queue name in Redis list
            queue_depth = int(r.llen("celery") or 0)
        except Exception as exc:
            logger.debug("Redis connectivity check failed: %s", exc)

        # 3. Query run distribution by status (pre-populated with 0 counts)
        runs_by_status: dict[str, int] = dict.fromkeys(
            (
                AgentRunStatus.PENDING,
                AgentRunStatus.QUEUED,
                AgentRunStatus.RUNNING,
                AgentRunStatus.AWAITING_APPROVAL,
                AgentRunStatus.COMPLETED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            ),
            0,
        )
        total_runs = 0
        try:
            status_stmt = select(AgentRun.status, func.count(AgentRun.id))
            if user_id is not None:
                status_stmt = status_stmt.where(AgentRun.user_id == user_id)
            status_stmt = status_stmt.group_by(AgentRun.status)
            status_res = await db.execute(status_stmt)
            for row in status_res.all():
                status_name, count = row
                runs_by_status[status_name] = count
                total_runs += count
        except Exception as exc:
            logger.warning("Failed to aggregate agent run statuses: %s", exc)

        # Ensure awaiting_approval metric only counts genuine actionable pending approvals
        try:
            from flowpilot.services.agents import AgentService

            actionable_awaiting = await AgentService.count_pending_approvals(db, user_id=user_id)
            runs_by_status[AgentRunStatus.AWAITING_APPROVAL] = actionable_awaiting
        except Exception as exc:
            logger.warning("Failed to count actionable approvals: %s", exc)

        # 4. Count active schedules matching the shared domain lifecycle
        active_schedules = 0
        try:
            from flowpilot.services.scheduling import SchedulingService

            active_schedules = await SchedulingService.count_active_schedules(db, user_id=user_id)
        except Exception as exc:
            logger.warning("Failed to count active schedules: %s", exc)

        # 5. Average duration of completed workflows
        avg_duration: float | None = None
        try:
            dur_stmt = select(
                func.avg(
                    func.extract("epoch", AgentRun.completed_at)
                    - func.extract("epoch", AgentRun.created_at)
                )
            ).where(AgentRun.completed_at.is_not(None))
            if user_id is not None:
                dur_stmt = dur_stmt.where(AgentRun.user_id == user_id)
            raw_avg = await db.scalar(dur_stmt)
            if raw_avg is not None:
                avg_duration = round(float(raw_avg), 2)
        except Exception as exc:
            logger.warning("Failed to calculate average run duration: %s", exc)

        # 6. Outbox counts
        failed_outbox_count = 0
        pending_outbox_count = 0
        try:
            failed_stmt = (
                select(func.count())
                .select_from(WorkflowOutbox)
                .where(WorkflowOutbox.status == OutboxStatus.FAILED)
            )
            failed_outbox_count = await db.scalar(failed_stmt) or 0

            pending_stmt = (
                select(func.count())
                .select_from(WorkflowOutbox)
                .where(WorkflowOutbox.status == OutboxStatus.PENDING)
            )
            pending_outbox_count = await db.scalar(pending_stmt) or 0
        except Exception as exc:
            logger.warning("Failed to count outbox records: %s", exc)

        # 7. LLM Provider failure rates
        provider_failure_rates: dict[str, float] = {}
        try:
            from flowpilot.models.llm_usage import LLMUsage

            prov_stmt = select(
                LLMUsage.provider,
                func.count().label("total"),
                func.count().filter(LLMUsage.status != "success").label("failed"),
            ).group_by(LLMUsage.provider)
            prov_res = await db.execute(prov_stmt)
            for row in prov_res.all():
                prov, total, failed = row
                if total > 0:
                    provider_failure_rates[str(prov)] = round(float(failed) / float(total), 4)
        except Exception as exc:
            logger.debug("Failed to calculate provider failure rates: %s", exc)

        return MonitoringHealthResponse(
            database_connected=db_connected,
            redis_connected=redis_connected,
            celery_queue_depth=queue_depth,
            runs_by_status=runs_by_status,
            total_runs=total_runs,
            active_schedules=active_schedules,
            average_duration_seconds=avg_duration,
            failed_outbox_count=failed_outbox_count,
            pending_outbox_count=pending_outbox_count,
            provider_failure_rates=provider_failure_rates,
            timestamp=now_utc,
        )
