# FlowPilot AI — Production Readiness & Security Audit Report

**Multi-Agent Workflow Orchestration & Business Automation Platform**

| Audit Information | Details |
|---|---|
| Audit date | October 28, 2026 |
| Target repository | `D:\PROJECTS\FLOWPILOT-AI` |
| Audit scope | Backend, frontend, security, database, orchestration, integrations, and automated testing |
| Assessment roles | Principal Software Architect, Senior Security Engineer, Full-Stack Lead, SRE |
| Release assessment | **READY WITH DOCUMENTED LIMITATIONS** |

> This document records the findings and verification results reported during the October 28, 2026 engineering audit. It is a project-level readiness assessment, not an independent security certification or a guarantee of unrestricted production operation.

---

## 1. Executive Summary

FlowPilot AI completed a comprehensive engineering audit covering its principal application layers:

- FastAPI backend and authenticated REST APIs.
- LangGraph multi-agent workflow orchestration.
- Celery asynchronous execution and scheduling.
- PostgreSQL persistence and Alembic migrations.
- Redis-backed task coordination and security mechanisms.
- MultiFernet credential encryption.
- OAuth and external integration handling.
- Multi-user resource isolation.
- Next.js Modern Enterprise frontend.
- Automated unit, integration, and end-to-end testing.

The audit identified and addressed several security, integration, and development-tooling issues.

Particular attention was given to preventing cross-user resource access, ensuring production environments do not silently use developer-owned provider credentials, and correcting WhatsApp webhook callback inconsistencies.

### Overall Results

| Validation Area | Reported Result |
|---|---|
| Backend tests | 260 passed, 1 skipped, 0 failed |
| Multi-user isolation scenarios | 8 passed |
| Ruff lint | Passed |
| Ruff formatting | 141 files checked successfully |
| Database migration consistency | Passed |
| Frontend unit/component tests | 59 passed |
| TypeScript | 0 errors |
| ESLint | 0 errors |
| Next.js production build | 28 routes compiled |
| Playwright browser tests | 3 passed |
| IDE/language-server diagnostics | Reported resolved |

The eight multi-user isolation scenarios form part of the backend validation evidence and should not be added to the 260 passing tests as a separate test total.

**Final assessment: READY WITH DOCUMENTED LIMITATIONS.**

---

## 2. Audited Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16.4.3, React 19, TypeScript 5 |
| Frontend data management | TanStack Query |
| Backend | Python 3.12, FastAPI |
| Agent orchestration | LangGraph |
| Database | PostgreSQL, AsyncPG, SQLAlchemy |
| Schema migrations | Alembic |
| Message broker | Redis 7 |
| Background processing | Celery Worker and Celery Beat |
| Encryption | MultiFernet |
| LLM gateway | Google Gemini, OpenAI, Groq |
| External integrations | Gmail, Google Sheets, Slack, WhatsApp Business |
| Backend testing | Pytest |
| Frontend testing | Vitest, React Testing Library |
| End-to-end testing | Playwright |
| Code quality | Ruff, TypeScript, ESLint |

---

## 3. Architecture Overview

```text
                     NEXT.JS FRONTEND
                   Modern Enterprise UI
                            |
                            v
                      FASTAPI BACKEND
                            |
          +-----------------+-----------------+
          |                 |                 |
          v                 v                 v
     Authentication     LLM Gateway     App Connections
          |                 |                 |
          |          Gemini/OpenAI/Groq       |
          |                                   |
          +-----------------+-----------------+
                            |
                            v
                     LangGraph Engine
                            |
                 Human Approval Gates
                            |
                            v
                    External Execution
                            |
          +-----------------+-----------------+
          |                 |                 |
          v                 v                 v
        Gmail         Sheets / Slack       WhatsApp

                    PERSISTENCE LAYER

       PostgreSQL                  Redis
       - User records              - Task broker
       - Agent runs                - OAuth nonces
       - Checkpoints               - Coordination
       - Encrypted credentials
       - Approvals
       - Notifications
       - Transactional outbox

                    BACKGROUND SERVICES

                Celery Worker / Celery Beat
                - Workflow execution
                - Smart Scheduling
                - Outbox processing
                - Recovery tasks
```

The frontend communicates with the authenticated backend, while Celery handles asynchronous operations independently of the HTTP request lifecycle.

PostgreSQL provides durable execution and application state. Redis supports background processing and security-sensitive coordination.

---

## 4. Confirmed Findings and Remediations

The audit documented five principal remediation items.

| ID | Area | Severity | Finding | Resolution |
|---|---|---|---|---|
| SEC-01 | App Connections | High | WhatsApp execution could fall back to global environment credentials when a user had no configured connection | Restricted fallback to explicitly configured non-production environments |
| SEC-02 | Multi-user isolation | Critical | Potential insecure direct object reference (IDOR) exposure across user-owned resources | Added dedicated isolation tests covering eight scenarios |
| BUG-01 | WhatsApp webhooks | Medium | Setup instructions and registered callback paths were inconsistent | Standardized the canonical path and introduced backward-compatible aliases |
| TYP-01 | OAuth typing | Low | Optional encrypted access tokens were passed into a function expecting a string | Added explicit token-presence checks and safe expiration handling |
| CFG-01 | Development tooling | Low | Incorrect system Python interpreter caused false missing-module diagnostics | Configured the Python 3.12 virtual environment and relevant import paths |

### SEC-01 — Production Credential Fallback

**Finding**

The WhatsApp execution path could use server-level environment credentials when the current user had not configured an appropriate connection.

This introduced a risk of unintended credential sharing.

**Remediation**

The reported fix restricts the relevant fallback condition to:

```python
not settings.is_production and settings.is_whatsapp_configured
```

Production execution without an appropriate user connection raises `IntegrationExecutionError`.

**Verification**

The audit reports source inspection in `registry.py` and unit tests confirming that an unconfigured production user cannot dispatch an operation using server-provided fallback credentials.

### SEC-02 — Multi-User Isolation

**Finding**

User-owned resources required consistent ownership filtering to prevent cross-user inspection or modification.

**Remediation**

A dedicated `test_multi_user_isolation.py` suite was introduced with isolated test users.

**Verification**

Eight reported isolation scenarios passed. Unauthorized resource lookups returned HTTP 404 where applicable, without exposing the target records.

These tests provide evidence for the tested access-control paths; they do not establish that every possible authorization vulnerability has been eliminated.

### BUG-01 — WhatsApp Webhook Callback Consistency

**Finding**

Two callback paths were referenced inconsistently:

```text
/api/v1/integrations/whatsapp/webhook
/api/v1/webhooks/whatsapp
```

**Remediation**

The canonical callback path was standardized as:

```text
/api/v1/webhooks/whatsapp
```

Backward-compatible aliases were added through the integration routing layer.

**Verification**

The audit reports that the setup interface displays the canonical path and the compatibility route handles the verification challenge.

### TYP-01 — Optional OAuth Token Handling

**Finding**

`decrypt_oauth_token()` could receive `connection.encrypted_access_token`, whose declared type permitted `None`.

**Remediation**

An explicit token-presence guard was added, and `is_token_expired()` was updated to safely handle an absent token.

**Verification**

The reported Pyright validation completed with zero errors.

### CFG-01 — Python Interpreter Configuration

**Finding**

Development tooling selected the system Python 3.14 interpreter instead of the intended Python 3.12 project environment.

This generated missing-module diagnostics for installed dependencies.

**Remediation**

Project-level Pyright and VS Code configuration was updated to resolve the appropriate virtual environment and source import paths.

**Verification**

The final audit reported no remaining language-server diagnostics.

---

## 5. Multi-User Isolation Audit

Multi-user isolation was tested using separate disposable user fixtures:

- `registered_user`
- `second_user`

The following eight domains were included.

| Domain | Verified Isolation Behavior |
|---|---|
| Agent runs | Another user's runs cannot be retrieved or enumerated |
| Telemetry and audit events | Another user's execution events are inaccessible |
| Human approvals | Approval/rejection cannot be performed on another user's run |
| Scheduled workflows | Cross-user viewing and schedule mutations are denied |
| Notifications | Cross-user reading and dismissal are denied |
| BYOK credentials and usage | Credentials and consumption records remain owner-scoped |
| App Connections | Connection details and management operations remain owner-scoped |
| External action audits | Audit records are filtered to the authenticated owner |

### Important Authorization Behaviors

For the tested scenarios:

- Direct access to another user's execution returned HTTP 404.
- Unauthorized approval or rejection did not alter the target workflow state.
- Schedule management operations enforced ownership checks.
- Credential-management endpoints did not expose another user's configuration.
- Connection overview responses did not disclose another user's sensitive metadata.
- External-action audit queries returned only the requesting user's records.

**Reported result: 8/8 isolation scenarios passed.**

---

## 6. OAuth and Provider Callback Security

The audit evaluated OAuth state generation, replay prevention, PKCE, and encrypted token storage.

### Signed OAuth State

State tokens use HMAC-SHA256 and include the relevant authorization context, including:

- User identity.
- Provider and service.
- Redirect URI.
- PKCE verifier.
- Nonce.
- Issued-at timestamp.
- Expiration timestamp.

### Replay Protection

OAuth state nonces are consumed atomically through Redis.

The reported implementation uses:

```text
SET key 1 EX ttl NX
```

A reused nonce produces an OAuth state validation error.

The production implementation is configured to fail safely when Redis is unavailable rather than silently bypassing replay protection.

### PKCE

The implementation uses a URL-safe verifier and SHA-256 code challenge, following the PKCE mechanism described by RFC 7636.

### Token Storage

OAuth tokens are encrypted at rest through MultiFernet.

Plaintext tokens must not be stored in normal persistent records or exposed in application logs.

---

## 7. App Connections Credential Security

The App Connections module was assessed for encrypted storage, secure editing, and user ownership.

### Encrypted Credential Storage

Sensitive provider credentials are protected using MultiFernet authenticated encryption.

### Masked Configuration Responses

Saved credentials are represented through masked indicators or non-reversible metadata rather than plaintext secret values.

Previously saved secrets are not decrypted and returned to the browser.

### Partial Updates

Updating non-sensitive connection fields preserves existing stored secrets when those secret fields are omitted.

Users can explicitly replace credentials when necessary.

### Owner-Scoped Access

Connection retrieval uses authenticated ownership constraints, including filtering by the relevant `user_id`.

The tested connection-management operations did not permit cross-user access.

---

## 8. Agent Execution and Approval Security

FlowPilot AI uses LangGraph to coordinate workflow interpretation, planning, execution, and verification.

Sensitive external actions are protected by explicit human approval.

### Parameter Integrity

Before a sensitive action is approved, its parameters are represented through canonical JSON and hashed using SHA-256.

The resulting digest is used to detect relevant changes between approval and dispatch.

Examples of protected parameters include:

- Recipients.
- Channels.
- Message payloads.
- External operation arguments.

A mismatch blocks the affected operation.

### Approval Lifecycle

An applicable workflow transitions to:

```text
awaiting_approval
```

It remains paused until an authorized user approves or rejects the action.

Approval allows the execution lifecycle to continue. Rejection terminates the proposed external action safely.

### Persistent Checkpointing

LangGraph execution state is persisted in PostgreSQL, supporting interruption and controlled resumption after worker restarts.

---

## 9. Scheduling, Notifications, and Background Reliability

### Smart Scheduling

Celery Beat periodically checks active schedules and initiates due workflows.

Triggered schedules produce linked `AgentRun` records.

### Notification Deduplication

Persistent notifications use deduplication keys to reduce duplicate notifications for the same triggering event.

### Scheduled-Execution Countdown

The frontend implements a 15-second countdown before a scheduled execution.

Navigation into the execution view depends on confirmed backend state rather than assuming that reaching zero guarantees execution creation.

### Transactional Outbox

Workflow dispatch operations are coordinated through persisted `WorkflowOutbox` records.

The reported implementation includes retry counters and exponential backoff for transient failures.

This separates durable application state changes from subsequent task delivery.

---

## 10. Database and Migration Consistency

The audit reviewed the Alembic migration history through the App Connections, scheduling, and notification additions.

The recorded validation command was:

```cmd
uv run alembic check
```

Reported output:

```text
No new upgrade operations detected.
```

The audit also reviewed foreign-key relationships for major user-owned entities, including:

- `AgentRun`
- `AgentEvent`
- `ScheduledWorkflow`
- `Notification`
- `IntegrationConnection`
- `LLMCredential`

Deletion behavior was reported as using appropriate `ON DELETE CASCADE` or `ON DELETE SET NULL` relationships.

Migration consistency should be revalidated after subsequent model or schema changes.

---

## 11. Frontend Quality and Design Integrity

The audited frontend uses the Modern Enterprise design system.

### Design Tokens

| Interface Element | Color |
|---|---|
| Navigation sidebar | `#172229` |
| Application header | `#24433F` |
| Primary accent | `#087F72` |
| Workspace background | `#F7F8F6` |

### Validation Results

| Check | Result |
|---|---|
| TypeScript | 0 errors |
| ESLint | 0 errors |
| Next.js production build | Passed |
| Compiled application routes | 28 |
| Playwright browser specifications | 3 passed |

The Playwright checks were reported as running against the local application runtime.

The audit also confirmed that previously reported development-environment diagnostics were resolved.

---

## 12. Complete Automated Validation Summary

The following figures are preserved from the original audit report.

| Validation | Reported Result |
|---|---|
| Backend unit and integration tests | 260 passed, 1 skipped |
| Multi-user isolation scenarios | 8 passed |
| Ruff formatting | 141 files checked |
| Ruff lint | Passed |
| Alembic schema consistency | Passed |
| Frontend TypeScript | Passed |
| Frontend ESLint | Passed |
| Frontend Vitest | 12 test files, 59 tests passed |
| Next.js production build | 28 routes compiled |
| Playwright Chromium | 3 tests passed |

### Reproduction Commands

From `backend/`:

```cmd
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run pytest -q
```

From `frontend/`:

```cmd
npx tsc --noEmit
npm run lint
npm run test
npm run build
```

Execute Playwright through the E2E script configured in the current `frontend/package.json`.

The results above represent the October 28, 2026 audit and should not be presented as the outcome of a newer run unless the tests have been executed again.

---

## 13. Documented Limitations and Deployment Prerequisites

Passing automated validation does not remove deployment-level dependencies on infrastructure, provider configuration, or external service availability.

The following items remain important before public deployment.

### 13.1 Production Encryption Keys

Configure secure Fernet keys for:

```dotenv
LLM_ENCRYPTION_KEYS=...
INTEGRATION_ENCRYPTION_KEYS=...
```

Keys must be generated securely and stored outside version control.

Existing decryption keys must be preserved during rotation until the associated credentials have been safely migrated.

### 13.2 Authentication Secret

Configure a strong production `JWT_SECRET_KEY`.

The audit records a minimum requirement of 32 cryptographically random characters enforced through production security validation.

### 13.3 Google Integration

Live OAuth operation requires the appropriate:

- Google Cloud project.
- Enabled APIs.
- OAuth consent-screen configuration.
- Authorized redirect URIs.
- Requested API scopes.
- Application verification where required.

### 13.4 Slack Integration

Live integration requires:

- A configured Slack application.
- Appropriate permissions.
- An authorized installation.
- Correct OAuth redirect URIs.

### 13.5 WhatsApp Business

Production messaging requires appropriate Meta configuration, including:

- WhatsApp Business Account.
- Registered phone number.
- Valid access token.
- Correct webhook subscription.
- Applicable messaging permissions and business verification.

An API-accepted WhatsApp message does not establish successful recipient delivery.

Provider restrictions or account-level locks remain external operational limitations.

### 13.6 Redis Availability

Redis supports Celery queueing and atomic OAuth nonce handling.

Production deployment must account for Redis availability, persistence requirements, backup strategy, and recovery procedures.

More advanced multi-instance configurations require additional infrastructure planning.

### 13.7 Live Provider Verification

Offline tests and mocked integrations do not replace authorized, post-deployment provider testing.

Live smoke tests may require valid credentials, approved recipient accounts, available provider quotas, and explicit permission to perform external operations.

---

## 14. Release Assessment

### READY WITH DOCUMENTED LIMITATIONS

The October 28, 2026 audit reported that:

- All identified issues listed in this report were remediated.
- The tested multi-user isolation scenarios passed.
- The complete backend test run finished without failures.
- Frontend unit, static-analysis, production-build, and browser tests passed.
- Database migrations were consistent with the audited models.
- WhatsApp callback paths were reconciled.
- Production credential fallback was restricted.
- Development tooling diagnostics were resolved.

These findings support progression to deployment preparation and controlled production smoke testing.

They do not eliminate the need for:

1. Correct production secrets and infrastructure configuration.
2. Provider-specific OAuth and webhook setup.
3. Live integration validation.
4. Monitoring, database backups, and recovery planning.
5. Final documentation and release review.

**Final audit decision: READY WITH DOCUMENTED LIMITATIONS.**

---

## 15. Audit Maintenance

This document describes a point-in-time assessment dated **October 28, 2026**.

Update or supplement the report when:

- A new production-readiness audit is performed.
- Significant authentication or authorization code changes.
- New external providers are introduced.
- Database or orchestration architecture changes.
- New security findings are discovered.
- Deployment verification produces additional evidence.

Historical test results should remain identifiable by their original audit date rather than being silently replaced with newer figures.

---

## 16. Engineering Addendum: Dashboard Isolation & Schedule Lifecycle Remediation (October 29–30, 2026)

### 16.1 Defect Overview: Cross-User Dashboard Metrics & Lifecycle Inconsistency
On October 29, 2026, an internal regression audit discovered a metric-scoping defect on the Overview Dashboard:
1. **Cross-User Metric Aggregation:** The endpoint `GET /api/v1/monitoring/health` was aggregating operational counts (pending approvals, active schedules, run counts, and average durations) globally across all tenants rather than filtering strictly by the authenticated user's ID (`user_id`). This allowed User A's dashboard cards to reflect the presence of User B's pending human approvals and active schedules.
2. **Approval Eligibility Mismatch:** The dashboard counter counted all runs where `status == "awaiting_approval"`, including stale runs with invalid/empty execution plans or cancelled workflows, whereas the Approvals destination page filtered for genuine actionable approval cards.
3. **Schedule Lifecycle Inconsistency:** The "Active Schedules" dashboard counter included completed one-time schedules and paused recurring schedules, creating discrepancies against the active schedules view.
4. **Stale Cache Invalidation:** Frontend mutations for approving/rejecting runs and pausing/resuming schedules did not explicitly invalidate the TanStack Query cache key `["monitoring", "health"]`, causing the dashboard count to lag behind destination-page state changes.

### 16.2 Confirmed Root Cause
- `MonitoringService.get_system_health`: Executed global `SELECT status, count(*) FROM agent_runs GROUP BY status` and `SELECT count(*) FROM scheduled_workflows WHERE is_active=True` without appending a `.where(user_id == current_user.id)` constraint.
- Absence of a centralized, shared domain filter for actionable approvals and active schedules across `AgentService`, `SchedulingService`, and `MonitoringService`.
- Scheduling state machine lacked automated `is_active = False` state transitions for consumed one-time schedules upon execution trigger.

### 16.3 Technical Remediation
1. **User-Scoped Backend Querying:**
   - Updated `GET /api/v1/monitoring/health` router to extract `current_user.id` from the authenticated session and pass it into `MonitoringService.get_system_health(db, user_id=current_user.id)`.
   - Scoped run status counts, active schedules, and average duration calculations strictly to `user_id`.
2. **Shared Actionable Approvals Filter (`actionable_approvals_filter`):**
   - Implemented `AgentService.actionable_approvals_filter(user_id)`:
     ```python
     and_(
         AgentRun.status == AgentRunStatus.AWAITING_APPROVAL,
         AgentRun.completed_at.is_(None),
         AgentRun.cancellation_requested.is_(False),
         AgentRun.execution_plan.is_not(None),
         func.jsonb_typeof(AgentRun.execution_plan) == "array",
         AgentRun.user_id == user_id,  # when user_id is provided
     )
     ```
   - Bound both `AgentService.count_pending_approvals` (used by monitoring health) and `AgentService.list_runs` (used by the Approvals view) to this identical filter expression, guaranteeing 100% count consistency.
3. **Shared Schedule Lifecycle Filter (`active_schedules_filter`):**
   - Implemented `SchedulingService.active_schedules_filter(user_id)`:
     ```python
     and_(
         ScheduledWorkflow.is_active.is_(True),
         or_(
             ScheduledWorkflow.schedule_type != ScheduleType.ONE_TIME,
             ScheduledWorkflow.last_run_at.is_(None),
         ),
         ScheduledWorkflow.user_id == user_id,  # when user_id is provided
     )
     ```
   - Bound both `SchedulingService.count_active_schedules` and frontend active schedule counts to this shared lifecycle rule. Completed one-time schedules automatically transition out of active counts and remain preserved in Schedule History.
4. **Existing-Data Reconciliation:**
   - Created and executed a standalone database reconciliation script (`backend/scripts/reconcile_db.py`) to reconcile historical schedules and approvals into consistent lifecycle states without data loss.
5. **Frontend Query Invalidation:**
   - Updated React Query mutation handlers in `approvals/page.tsx` and `schedules/page.tsx` to invalidate `["monitoring", "health"]` alongside domain keys (`["approvals"]`, `["schedules"]`, `["workflows"]`) upon approval, rejection, creation, pause, resume, and trigger operations.
6. **Regression Test Suite:**
   - Authored comprehensive backend regression suite: `backend/tests/test_dashboard_metrics_consistency.py` (13 isolated test scenarios covering approvals, schedules, multi-user isolation, and duplicate prevention).
   - Authored Playwright E2E regression suite: `frontend/tests/e2e/dashboard-metrics-consistency.spec.ts` (Scenarios A, B, C, D).

### 16.4 Verified Regression & Release Results (October 30, 2026)

All automated validation commands were freshly re-executed on October 30, 2026, confirming 100% passing status across the entire codebase:

| Validation Layer | Command / Tool | Status | Exact Metric |
|---|---|---|---|
| **Backend Test Suite** | `uv run pytest -q` | **PASSED** | **273 passed, 1 skipped** (157.7s) |
| **Backend Linting** | `uv run ruff check .` | **PASSED** | 0 errors across 142 files |
| **Backend Formatting** | `uv run ruff format --check .` | **PASSED** | 142 files properly formatted |
| **Database Migrations** | `uv run alembic check` | **PASSED** | Schema consistent, 0 pending upgrade operations |
| **TypeScript Compilation** | `npx tsc --noEmit` | **PASSED** | 0 type errors |
| **Frontend Linting** | `npm run lint` | **PASSED** | 0 warnings, 0 errors |
| **Frontend Unit Tests** | `npm run test` (Vitest) | **PASSED** | **59 passed** across 12 test files (34.4s) |
| **Frontend Production Build** | `npm run build` | **PASSED** | **27/27 static/dynamic routes** compiled |
| **Browser E2E Specifications** | `npm run test:e2e` (Playwright) | **PASSED** | **5 passed** across 3 spec files (22.4s) |

---

*End of production-readiness audit report and release addendum.*