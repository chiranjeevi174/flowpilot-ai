# Architecture

FlowPilot AI is a Next.js BFF and FastAPI application backed by PostgreSQL and Redis. Celery Worker executes LangGraph workflows; Celery Beat claims due schedules and performs recovery jobs. LangGraph checkpoints live in PostgreSQL, enabling approval pauses and resumption.

## Main flow

1. Authenticated user submits a workflow or configures a schedule.
2. API validates ownership and records the work; transactional outbox dispatches it asynchronously.
3. Worker resolves the workflow owner's selected LLM and App Connection, then runs intent analysis, planning, execution and verification.
4. Sensitive external actions suspend for explicit human approval. Approval binds to the intended action and parameters.
5. Provider response and external-action audit data are persisted. When supplied, signed provider webhook events update downstream statuses.
6. Execution details and notifications are surfaced to the user through the API/frontend.

## Boundaries to preserve

- No browser access to decrypted saved secrets or server-side encryption keys.
- No cross-user credential fallback for production external-action dispatch.
- Distinguish workflow completion, provider API acceptance and actual recipient delivery.
- Use durable schedule-occurrence identity and execution references to prevent accidental duplicate creation.
- One-time schedules belong in Schedule History after a run is durably created; execution may still await approval.

This document summarizes the supplied engineering reports; verify exact file paths and runtime wiring against the repository prior to public release.
