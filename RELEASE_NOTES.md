# Release Notes — FlowPilot AI v1.0.0

**Release Version:** `v1.0.0`  
**Date:** October 30, 2026  
**Repository:** `flowpilot-ai`  
**Architectural Scope:** Production-Ready Multi-Agent Workflow Orchestration & Business Automation Platform  

---

## Overview

FlowPilot AI v1.0.0 is the foundational production release of a self-hostable, multi-agent business process automation platform. Designed for privacy-conscious organizations and demanding automation workflows, FlowPilot AI enables teams to orchestrate specialized AI agents with LangGraph, enforce human-in-the-loop authorization gates, schedule recurring cron-based automations, and connect enterprise tools (Gmail, Google Sheets, Slack, Meta WhatsApp Business) while bringing their own LLM API keys (BYOK).

---

## Key Capabilities & Highlights

### 1. Multi-LLM BYOK Gateway (Gemini, OpenAI, Groq)
- **Zero Vendor Lock-In**: Operators supply their own API keys via encrypted settings.
- **Dynamic Model Discovery**: Real-time querying of available models directly from provider endpoints (`gemini-2.0-flash`, `gpt-4o`, `llama-3.3-70b-versatile`, etc.).
- **MultiFernet Encryption**: User API keys are encrypted at rest with authenticated AES-128-CBC + HMAC-SHA256 with zero-downtime key rotation support.
- **Token Telemetry & Cost Accounting**: Granular prompt and completion token tracking with model pricing tables.
- **Collapsible UI Experience**: Dedicated collapsible sections for Available Models and Generation Audit History with persistent preferences.

### 2. LangGraph Multi-Agent Orchestrator
- **State Checkpointing in PostgreSQL**: Graph state is persisted at every execution step (`langgraph_checkpoints`), enabling pause/resume capabilities and fault tolerance across worker restarts.
- **Specialized Multi-Agent Fleet**:
  - `intent`: Detects and classifies natural-language requests into structured automation intents.
  - `planner`: Formulates multi-step execution plans with dependency resolution.
  - `executor`: Dispatches tool invocations and coordinates LLM generations.
  - `verifier`: Inspects outputs, verifies policy compliance, and guards external action boundaries.
- **Human-in-the-Loop (HITL) Approval Engine**: Sensitive actions (sending outbound emails, posting to public Slack channels, appending spreadsheet records, WhatsApp messaging) pause execution in `AWAITING_APPROVAL` status until an authorized operator approves or rejects the action with cryptographic parameter digest verification.

### 3. Enterprise External Integrations (OAuth 2.0 & Webhooks)
- **Google Workspace (Gmail & Sheets)**:
  - Read email threads, compose drafts, and send emails (send guarded by HITL approval).
  - Append rows to spreadsheets with built-in CWE-1236 spreadsheet formula injection sanitization.
- **Slack Workspace**:
  - Send messages and block kits to public/private channels.
  - Ingest webhook events with HMAC-SHA256 signature verification and 5-minute replay window protection.
- **Meta WhatsApp Business Platform (Cloud API)**:
  - Official Meta Cloud API adapter supporting direct customer-service messages (24-hour messaging window) and pre-approved Meta message templates.
  - Cryptographic inbound webhook signature verification using `X-Hub-Signature-256` (HMAC-SHA256) with delivery receipt lifecycle tracking (`sent`, `delivered`, `read`, `failed`).
  - Mandatory human-in-the-loop approval gate (`whatsapp_send_message`, `whatsapp_send_template`) with cryptographic SHA-256 parameter digest validation preventing runtime modification.
  - Canonical webhook endpoint: `/api/v1/webhooks/whatsapp`.

### 4. Dashboard Consistency & Multi-User Resource Isolation
- **Tenant-Scoped Operational Metrics**: Resolved metric aggregation defect in `GET /api/v1/monitoring/health` by binding all counters to the authenticated user's ID (`user_id`).
- **Shared Actionable Approvals Filter**: Unified `actionable_approvals_filter` ensures dashboard pending approval counts match actionable cards on the Approvals page.
- **Schedule Lifecycle Consistency**: Distinct separation between Active Schedules (upcoming one-time, active/paused recurring) and Schedule History (completed one-time schedules).
- **Reactive Cache Invalidation**: TanStack Query mutations automatically invalidate both domain queries and `["monitoring", "health"]` for instant UI updates.

### 5. Production Reliability & Asynchronous Task Architecture
- **Transactional Outbox Pattern**: Decouples API transactions from Celery task delivery, guaranteeing zero lost workflow runs during Redis broker disruptions.
- **Heartbeat & Zombie Reaper**: Background recovery process scans for orphaned runs if a worker node unexpectedly crashes, cleanly resuming from saved LangGraph checkpoints.
- **Concurrency-Safe Refresh Token Rotation**: Implemented row-level database locking (`SELECT ... FOR UPDATE`) in `rotate_refresh_token` to eliminate token reuse race conditions across multi-instance frontend SSR invocations.
- **Next.js Backend-For-Frontend (BFF)**: Authentication tokens are stored in `HttpOnly`, `SameSite=Lax`, `Secure` cookies; browser client code never accesses raw JWTs.

### 6. Streamlined Windows Development Lifecycle
- **One-Command Startup (`start-dev.cmd`)**: Automatically validates dependencies, starts Docker infrastructure (PostgreSQL on port `5433`, Redis on port `6379`), launches FastAPI (`http://127.0.0.1:8000`), Celery Worker (`-P solo`), Celery Beat, and Next.js frontend (`http://localhost:3000`), opening the browser upon readiness.
- **Clean Background Mode**: All processes run in the background by default with dedicated logging under `.run/logs/`.
- **Debugging Terminal Mode**: Pass `--show-windows` (or `/w`) to launch visible terminal windows for each process.
- **One-Command Shutdown (`stop-dev.cmd`)**: Safely halts development processes and Docker containers non-destructively, preserving all database volumes and credentials.
- **Explicitly Optional ngrok**: Dedicated instructions for `ngrok http 8000` solely for local Meta WhatsApp webhook receipt testing.

---

## Automated Validation & Quality Assurance Summary

| Validation Layer | Command / Tool | Status | Verified Metrics |
|---|---|---|---|
| **Backend Linting** | `uv run ruff check .` | **PASSED** | 0 errors across 142 files |
| **Backend Formatting** | `uv run ruff format --check .` | **PASSED** | 142 files formatted cleanly |
| **Database Migrations** | `uv run alembic check` | **PASSED** | Clean schema, 0 pending upgrade operations |
| **Backend Test Suite** | `uv run pytest -q` | **PASSED** | **273 passed, 1 skipped** (157.7s) |
| **TypeScript Compilation**| `npx tsc --noEmit` | **PASSED** | 0 type errors |
| **Frontend Linting** | `npm run lint` | **PASSED** | 0 warnings, 0 errors |
| **Frontend Unit Tests** | `npm run test` (Vitest) | **PASSED** | **59 passed** across 12 test files (34.4s) |
| **Frontend Production Build** | `npm run build` | **PASSED** | **27/27 static/dynamic routes** compiled |
| **Browser E2E Tests** | `npm run test:e2e` (Playwright) | **PASSED** | **5 passed** across 3 test suites (22.4s) |

---

## Security Audit & Hygiene Status

- [x] **Zero Hardcoded Secrets**: All development credentials removed from public-facing documentation; environment variable templates use explicit placeholders.
- [x] **Production Guard on Seeding**: `seed_dev.py` explicitly rejects execution in `ENVIRONMENT=production`.
- [x] **Git Tracking Cleanliness**: Verified via `git status --ignored`. Zero `.env`, `.pem`, `.key`, or `.dump` files are tracked.
- [x] **Container Security**: Backend and Frontend containers run as unprivileged users (`appuser` UID 10001, `nextjs` UID 1001). Internal PostgreSQL and Redis ports are bound strictly to private Docker bridge networks in production.
- [x] **Secret Log Redaction**: Live logging pipeline redacts API tokens matching `gsk_`, `sk-`, `AIzaSy`, `xox*`, and `Bearer`.
- [x] **Per-User Resource Isolation**: Multi-tenant database querying guarantees users cannot view or manipulate other users' workflows, credentials, approvals, or schedules.

---

## Deployment Architecture

FlowPilot AI provides two deployment options:
1. **Containerized Production Stack (`compose.prod.yaml`)**:
   - Single-command orchestration for NGINX, Next.js, FastAPI, PostgreSQL, Redis, Celery Worker, and Celery Beat.
   - Ready for HTTPS termination via Let's Encrypt / Certbot (`infrastructure/nginx/nginx.https.conf.example`).
   - Automated database migration runner (`flowpilot-migrator`) runs `alembic upgrade head` before backend traffic starts.
2. **Local Development Stack (`compose.yaml` + `start-dev.cmd`)**:
   - Lightweight PostgreSQL and Redis containers with hot-reloading FastAPI and Next.js dev servers.

---

## Known Limitations & Pre-Release Checklist

1. **Distribution License**: Adopted the official MIT License (`LICENSE`) with copyright attributed to chiranjeevi174 (2026).
2. **Third-Party Provider Verification**: Live external integration testing (Google Workspace OAuth consent, Slack App installation, Meta WhatsApp Business Cloud API verification) requires operator-supplied credentials and provider approval.
3. **Domain & HTTPS Termination**: Production deployment requires configuring DNS, a valid domain name, and Let's Encrypt / SSL certificates in `infrastructure/nginx/`.
