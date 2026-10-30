"""Centralized Celery application configuration and beat schedules for FlowPilot AI."""

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from celery import Celery

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger

logger = get_logger("workers.celery")
settings = get_settings()

celery_app = Celery("flowpilot")

celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER or settings.is_testing,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    imports=[
        "flowpilot.workers.tasks",
    ],
    beat_schedule={
        "process-scheduled-workflows-every-10s": {
            "task": "flowpilot.workers.tasks.process_scheduled_workflows_task",
            "schedule": 10.0,
        },
        "recover-stuck-outbox-every-10s": {
            "task": "flowpilot.workers.tasks.recover_outbox_task",
            "schedule": 10.0,
        },
        "recover-abandoned-runs-every-60s": {
            "task": "flowpilot.workers.tasks.recover_abandoned_runs_task",
            "schedule": 60.0,
        },
    },
)
