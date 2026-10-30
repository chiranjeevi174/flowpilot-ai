# Deployment guide and release gates

**Status:** Preparation guide, not a claim of completed public deployment. The October 28 local audit classified FlowPilot AI as **Ready with documented limitations**.

## Before deploying

1. Inspect actual `infrastructure/` compose files and environment templates. The previous README referred to `infrastructure/compose.prod.yaml` and `infrastructure/.env.prod.example`; confirm they still exist and match the current code before executing production commands.
2. Configure a stable public HTTPS origin, domain/DNS and reverse proxy. Verify secure cookies, trusted origins and proxy/SSE behavior.
3. Provide unique database, JWT/session and encryption secrets through deployment secret management. Protect encryption-key rotation and backups.
4. Run Alembic migrations before API/worker traffic; persist PostgreSQL data and define backups/restoration tests.
5. Run exactly the intended Beat scheduler instances, worker processes and frontend/API services. Add health checks, logs and restart policies.
6. Register actual deployed OAuth redirect URIs with Google/Slack. Verify current WhatsApp webhook endpoint, signature validation and WABA subscription.
7. Keep user-owned integration credentials in App Connections and LLM credentials in BYOK. Never provision developer-owned integration fallbacks to arbitrary new users.
8. Validate a disposable multi-user smoke test without unattended real external sends.

## Validation gates

- Clean migration from a fresh disposable database and non-destructive upgrade of an existing database.
- Auth, BFF cookie session, per-user isolation, BYOK, App Connections, approvals, scheduling and notifications.
- Celery Worker/Beat and LangGraph checkpoint recovery after restart.
- Provider-specific callback and webhook verification with legitimate credentials and permission scopes.
- Documented operational limitations and any provider verification/account restrictions.
- Review tracked files and build artifacts for secrets, including `.env`, logs, local DB dumps and screenshots.

**Do not tag `v1.0.0` until the deployed smoke tests and repository URL/CI links have been verified.**
