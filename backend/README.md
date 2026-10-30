# FlowPilot AI — Backend

Backend service for **FlowPilot AI**, a multi-agent workflow orchestration and business automation platform.

Built with FastAPI, Python 3.12, LangGraph, PostgreSQL, Redis, and Celery, the backend manages AI-powered workflow execution, background scheduling, human-in-the-loop approvals, secure third-party integrations, and real-time execution monitoring.

## Core Capabilities

- Multi-agent orchestration using LangGraph.
- Unified LLM gateway supporting Google Gemini, OpenAI, and Groq.
- Bring Your Own Key (BYOK) model configuration.
- Persistent workflow checkpointing using PostgreSQL.
- Asynchronous workflow execution using Celery.
- One-time and recurring workflow scheduling.
- Human approval gates for sensitive external actions.
- Gmail, Google Sheets, Slack, and WhatsApp Business integrations.
- Secure, user-managed credentials through App Connections.
- Multi-user resource and credential isolation.
- Transactional outbox and background recovery.
- Real-time execution telemetry using Server-Sent Events (SSE).
- Persistent notifications, scheduled-workflow reminders, and approval alerts.
- JWT authentication, refresh-token rotation, and password recovery.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API Framework | FastAPI |
| Data Validation | Pydantic v2 |
| ORM | SQLAlchemy Async |
| Database | PostgreSQL 16 |
| Database Migrations | Alembic |
| Agent Orchestration | LangGraph |
| Persistent Checkpoints | PostgreSQL / AsyncPostgresSaver |
| Background Processing | Celery |
| Message Broker | Redis 7 |
| LLM Providers | Gemini, OpenAI, Groq |
| Credential Encryption | MultiFernet |
| Authentication | JWT and secure password hashing |
| Testing | Pytest |
| Linting and Formatting | Ruff |
| Dependency Management | uv |

---

## Architecture Overview

```text
                  Next.js Frontend
                         |
                         v
                   FastAPI Backend
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     Authentication   LLM Gateway   App Connections
          |              |              |
          +--------------+--------------+
                         |
                         v
                Workflow Orchestration
                     LangGraph
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     PostgreSQL       Redis         Celery Worker
     Persistence      Broker             |
          |                              v
          |                       External Actions
          |                              |
          |                  Gmail / Sheets / Slack /
          |                         WhatsApp
          |
          +------ Checkpoints & Audit Records

                  Celery Beat Scheduler
                         |
                         v
                  Scheduled Workflows
                         |
                         v
                Notifications & Approvals
```

FastAPI handles application requests and authenticated access. Celery executes workflows asynchronously, while LangGraph coordinates the agent execution lifecycle.

PostgreSQL stores application records, workflow checkpoints, encrypted credential records, approval information, and execution history.

Redis supports background task processing and related runtime coordination.

---

## Local Development

### Quick Start (Recommended Everyday Method)

For everyday local development, the recommended way to start the complete FlowPilot AI stack is via the root one-command startup script:

```cmd
cd /d D:\PROJECTS\FLOWPILOT-AI
start-dev.cmd
```

This automatically orchestrates PostgreSQL, Redis, FastAPI, Celery Worker, Celery Beat, and the Next.js frontend, opening the application at `http://localhost:3000`. Refer to the [Root README](../README.md#running-flowpilot-ai-locally-windows) for complete startup options, log directories (`.run/logs/`), optional ngrok configuration, and graceful shutdown commands (`stop-dev.cmd`).

---

### Manual Setup & Individual Services (Development Reference)

The step-by-step instructions below are preserved for developers who need to install dependencies, run migrations, or execute and debug individual backend services independently.

#### Prerequisites

Install:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop
- Docker Compose

The frontend requires Node.js and npm. See [Frontend README](../frontend/README.md) for frontend-specific instructions.

#### 1. Open the Backend Directory

Run the following commands from Windows Command Prompt:

```cmd
cd /d D:\PROJECTS\FLOWPILOT-AI\backend
```

For a fresh installation, install the locked dependencies:

```cmd
uv sync --python 3.12
```

#### 2. Configure Environment Variables

Create the local environment configuration from the repository's existing environment template.

The backend requires infrastructure-level configuration for services such as:

- PostgreSQL.
- Redis.
- JWT authentication.
- Credential encryption.
- Trusted application origins.
- Application environment.
- Public callback/base URLs where applicable.

Individual users configure their LLM API keys and supported external-application credentials through the frontend's **Multi-LLM (BYOK)** and **App Connections** modules.

Do not commit `.env` files, OAuth credentials, encryption keys, or API tokens.

#### 3. Start PostgreSQL and Redis

From the backend directory:

```cmd
docker compose -f ..\infrastructure\compose.yaml up -d
```

Check container health:

```cmd
docker compose -f ..\infrastructure\compose.yaml ps
```

The current local development configuration exposes PostgreSQL on port `5433` and Redis on port `6379`.

Use the actual Docker Compose configuration as the source of truth if these mappings change.

#### 4. Apply Database Migrations

```cmd
uv run alembic upgrade head
```

Verify migration consistency:

```cmd
uv run alembic check
```

Never reset an existing database merely to apply a new migration.

#### 5. Start FastAPI (Manual Mode)

```cmd
uv run uvicorn flowpilot.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify the health endpoint:

```text
http://127.0.0.1:8000/api/v1/health
```

Interactive API documentation is available in development at:

```text
http://127.0.0.1:8000/docs
```

#### 6. Start Celery Worker (Manual Mode)

If running or debugging the worker independently in an isolated terminal:

```cmd
cd /d D:\PROJECTS\FLOWPILOT-AI\backend

uv run celery -A flowpilot.workers.celery_app worker --loglevel=info -P solo
```

The `solo` pool is used for local Windows development.

#### 7. Start Celery Beat (Manual Mode)

If running or debugging the scheduler independently in an isolated terminal:

```cmd
cd /d D:\PROJECTS\FLOWPILOT-AI\backend

uv run celery -A flowpilot.workers.celery_app beat --loglevel=info
```

Celery Beat handles periodic scheduling, due-workflow processing, and configured recovery tasks.

Avoid running duplicate Beat instances against the same scheduling environment.

> [!NOTE]
> FastAPI, Celery Worker, and Celery Beat are separate processes. Starting FastAPI alone does not start background workflow execution or scheduling. (When using `start-dev.cmd` from the root, all three backend services and infrastructure containers are automatically orchestrated together.)

---

## API Overview

All major application endpoints are organized under `/api/v1`.

The following sections summarize the backend's capabilities. Consult the running OpenAPI documentation for the complete, current route definitions and request/response schemas.

### Authentication

| Endpoint | Description |
|---|---|
| `POST /api/v1/auth/register` | Register an account |
| `POST /api/v1/auth/login` | Authenticate a user |
| `POST /api/v1/auth/refresh` | Refresh authentication |
| `POST /api/v1/auth/logout` | Revoke the active session |

The authentication system also supports password recovery and authenticated account management.

### Health

| Endpoint | Description |
|---|---|
| `GET /api/v1/health` | Application health status |

### Multi-LLM Gateway

Supports:

- Gemini.
- OpenAI.
- Groq.
- Encrypted user-managed API keys.
- Dynamic model discovery.
- Default provider/model preferences.
- Unified generation.
- Token and cost tracking.
- Generation audit history.

Main API namespace:

```text
/api/v1/llm
```

### Workflow Execution

The workflow API supports:

- Creating asynchronous execution runs.
- Retrieving execution details.
- Monitoring execution status.
- Streaming telemetry.
- Cancelling supported executions.
- Persistent agent-state recovery.

Workflow creation returns HTTP `202 Accepted` when the execution is accepted for asynchronous processing.

### Human Approval

Sensitive external actions require explicit authorization before dispatch.

Approval records preserve the intended operation, parameters, authorization state, and relevant integrity information.

Approval and rejection are handled through authenticated backend endpoints.

### Scheduling

The scheduling service supports:

- One-time workflows.
- Recurring workflows.
- Schedule pause/resume.
- Timezone-aware execution.
- Durable scheduled-run creation.
- Schedule History.
- Recovery and duplicate-trigger protection.

### Notifications

Persistent notifications support:

- Upcoming scheduled workflows.
- Workflow-start events.
- Human approval requirements.
- Notification read/dismiss lifecycle.
- Direct navigation to related application resources.

The frontend displays a live 15-second pre-execution countdown using the configured scheduled timestamp.

### App Connections

The App Connections APIs enable authenticated users to configure and manage supported external providers without modifying backend environment files.

Supported providers:

- Gmail.
- Google Sheets.
- Slack.
- WhatsApp Business.

Available functionality includes credential configuration, OAuth authorization where applicable, connection testing, setup guides, and connection management.

### External Integrations

Integration adapters execute authorized operations through the connected user's provider credentials.

Execution results are recorded through the existing external-action audit system.

WhatsApp additionally supports delivery-status webhook processing, distinguishing API acceptance from subsequent delivery outcomes.

---

## LangGraph Execution Lifecycle

FlowPilot uses specialized agents to process workflow instructions.

A typical execution follows:

```text
Workflow Submitted
        |
        v
   Intent Analysis
        |
        v
      Planning
        |
        v
 Human Approval Gate
   (when required)
        |
        v
  External Execution
        |
        v
    Verification
        |
        v
 Completed / Failed
```

Not every workflow requires external execution or human approval.

Sensitive external actions must pause until the appropriate user explicitly authorizes them.

Persistent PostgreSQL checkpoints support interruption and subsequent execution resumption.

---

## Scheduling and Background Processing

Celery separates long-running workflow execution from HTTP request handling.

The backend uses:

- Celery Worker for asynchronous execution.
- Celery Beat for periodic scheduling.
- Redis as the message broker.
- PostgreSQL for durable application and execution state.
- Transactional outbox processing for reliable task dispatch.
- Recovery mechanisms for abandoned or interrupted runs.

One-time schedules move to Schedule History after their scheduled execution has been durably created.

Recurring schedules remain available for subsequent occurrences.

A scheduled workflow requiring approval must not bypass the normal human authorization gate.

---

## Integration Credential Security

FlowPilot separates deployment-level configuration from user-managed credentials.

### Deployment-Level Configuration

The backend environment retains infrastructure and security configuration, including database access, Redis connectivity, authentication secrets, and encryption keys.

### User-Managed Configuration

Users configure supported providers through:

- Multi-LLM (BYOK).
- App Connections.

Sensitive credentials are encrypted at rest using MultiFernet.

Normal API responses expose safe configuration metadata rather than decrypted stored secrets.

Integration records are scoped to their authenticated owners.

Background workflow execution must resolve the appropriate owner's connection instead of silently sharing another user's credentials.

Production mode must not silently fall back to developer-owned external provider credentials.

---

## Encryption and Key Rotation

FlowPilot uses `cryptography`'s MultiFernet implementation for authenticated encryption of sensitive credentials.

Generate a Fernet key:

```cmd
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The project uses separately configured encryption-key settings for supported credential domains, including:

```dotenv
LLM_ENCRYPTION_KEYS=primary_key,previous_key
INTEGRATION_ENCRYPTION_KEYS=primary_key,previous_key
```

Use actual generated keys, not these example values.

Key ordering matters:

- The first key is used for new encryption operations.
- Previously configured keys remain available for decrypting older records during rotation.
- Do not remove an old key until every record depending on it has been safely migrated or re-encrypted.

Store encryption keys securely outside the source repository.

Losing every valid decryption key can make existing encrypted credentials unrecoverable.

---

## Security Architecture

The backend includes the following security mechanisms:

- Authenticated user sessions.
- Password hashing.
- JWT refresh-token rotation.
- User-scoped resource authorization.
- MultiFernet credential encryption.
- OAuth state validation.
- Human-in-the-loop authorization.
- Parameter-integrity verification for sensitive actions.
- Provider webhook verification.
- External-action audit records.
- Secret-safe API responses.
- Environment-aware production security configuration.

Security controls must also apply to Celery workers, scheduled workflows, OAuth callbacks, and other asynchronous execution paths.

---

## Automated Testing

Run the complete backend validation suite from the backend directory:

```cmd
uv run ruff check .

uv run ruff format --check .

uv run alembic check

uv run pytest -q
```

### Latest Reported Audit Results

The October 28, 2026 production-readiness audit reported:

| Validation | Result |
|---|---|
| Backend tests | 260 passed, 1 skipped |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Alembic check | Passed |
| Production-readiness classification | Ready with documented limitations |

These are results from the recorded engineering audit, not a guarantee that every external provider is currently available or unrestricted.

Automated tests should mock provider operations where possible and must not unintentionally send actual external messages.

---

## Deployment Considerations

Before deploying the backend:

1. Configure production environment variables and strong encryption keys.
2. Use HTTPS and appropriate trusted application origins.
3. Configure persistent PostgreSQL and Redis services.
4. Apply Alembic migrations.
5. Start FastAPI, Celery Worker, and Celery Beat.
6. Register the correct OAuth callback URLs.
7. Configure the canonical WhatsApp webhook endpoint where applicable.
8. Validate multi-user credential isolation.
9. Verify the application's health and background services.
10. Perform controlled post-deployment smoke testing.

Third-party integrations may require provider-specific application verification, authorization, business-account configuration, or additional permissions.

The backend must not assume that successfully saving credentials guarantees a working external connection.

Refer to the root README and the documentation directory for full deployment and integration instructions.

---

## Related Documentation

- [Main Project README](../README.md)
- [Documentation Directory](../docs/)
- [Integration Setup Guide](../docs/integrations-setup.md)
- [WhatsApp Setup Guide](../docs/whatsapp-setup.md)
- [Operations and Recovery](../docs/operations-and-runbooks.md)
- [Production Readiness Audit](../docs/production_readiness_audit_report.md)

---

## Project Status

**Production readiness assessment:** Ready with documented limitations.

The backend has passed its latest reported automated engineering audit. Public deployment still requires appropriate production configuration, live-provider verification, operational monitoring, and review of the documented remaining limitations.