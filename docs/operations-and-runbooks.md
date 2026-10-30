# FlowPilot AI — Operations, Backup & Disaster Recovery Runbook

This document details production operational standards, backup protocols, key rotation procedures, and incident recovery runbooks for the FlowPilot AI multi-agent workflow platform.

---

## 1. Persistent Storage & Backup Protocols

### 1.1 PostgreSQL Backup (Automated & On-Demand)
FlowPilot uses PostgreSQL 16 to persist users, multi-agent execution runs, checkpoints, outbox messages, scheduled workflows, and encrypted credentials.

#### Creating a Full Consistent Backup
To create a binary compressed backup (`.dump`) using `pg_dump`:
```bash
# Containerized production deployment
docker exec -t flowpilot-postgres-prod pg_dump \
  -U flowpilot_admin \
  -d flowpilot_production \
  -Fc > "flowpilot_backup_$(date +%Y%m%d_%H%M%S).dump"

# Verify dump integrity
pg_restore -l "flowpilot_backup_<timestamp>.dump" | head -n 20
```

#### Restoring a PostgreSQL Backup
To restore into a fresh recovery database:
```bash
# 1. Ensure target database exists
docker exec -i flowpilot-postgres-prod psql -U flowpilot_admin -d postgres -c "CREATE DATABASE flowpilot_restore;"

# 2. Restore schema and data
docker exec -i flowpilot-postgres-prod pg_restore \
  -U flowpilot_admin \
  -d flowpilot_restore \
  --clean \
  --if-exists \
  --no-owner \
  < "flowpilot_backup_<timestamp>.dump"
```

### 1.2 Redis Persistent Storage
FlowPilot runs Redis with `appendonly yes` and `allkeys-lru` eviction policy.
- AOF persistence files are mapped to the volume `redis_prod_data` at `/data/appendonlydir`.
- For cold backups, snapshot the `/data` directory or trigger `BGSAVE`:
```bash
docker exec -t flowpilot-redis-prod redis-cli bgsave
```

---

## 2. Encryption Keys & Secret Rotation

### 2.1 MultiFernet Architecture
FlowPilot encrypts all user LLM keys (Gemini, OpenAI, Groq) and OAuth 2.0 refresh tokens at rest using Fernet symmetric encryption. Multiple keys are supported simultaneously via cryptography's `MultiFernet`:
- **Primary key** (first entry in list): Used for all **new** encryptions.
- **Secondary keys** (subsequent entries): Used to **decrypt** existing ciphertexts.

### 2.2 Zero-Downtime Secret Rotation Procedure
1. **Generate a new 32-byte URL-safe base64 Fernet key**:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. **Update environment configuration**:
   Set `LLM_ENCRYPTION_KEYS` in `.env.prod`:
   ```bash
   LLM_ENCRYPTION_KEYS=["<NEW_PRIMARY_KEY>","<OLD_SECONDARY_KEY>"]
   ```
3. **Restart application containers**:
   ```bash
   docker compose -f infrastructure/compose.prod.yaml restart backend worker
   ```
   *At this stage, new credentials encrypt with `<NEW_PRIMARY_KEY>`, and existing credentials decrypt cleanly with `<OLD_SECONDARY_KEY>`.*
4. **Run batch re-encryption script** (optional batch migration to re-encrypt all ciphertexts under the new primary key).
5. **Retire the old key** once all records have been rotated.

---

## 3. Incident Recovery & Failure Modes

### 3.1 Redis Interruption & Outbox Resilience
- **Failure Mode**: Redis crashes or becomes temporarily unreachable.
- **System Behavior**:
  - API requests continue accepting workflows without data loss.
  - New workflow dispatches are committed to PostgreSQL within the `workflow_outbox` table (`status="pending"`).
  - Webhook receipts are safely stored in `integration_events`.
- **Recovery Procedure**:
  1. Restart Redis container:
     ```bash
     docker compose -f infrastructure/compose.prod.yaml up -d redis
     ```
  2. The Celery Beat process will automatically trigger `flowpilot.workers.tasks.sweep_outbox` on the next interval.
  3. All pending outbox messages are dispatched to workers in original chronological order.

### 3.2 Celery Worker Failure & Heartbeat Reaping
- **Failure Mode**: A worker container runs out of memory or terminates ungracefully while executing a multi-agent run.
- **System Behavior**:
  - LangGraph step checkpoints remain safely stored in PostgreSQL (`langgraph_checkpoints`).
  - Active runs maintain a `heartbeat_at` timestamp in the database.
- **Recovery Procedure**:
  1. Restart the worker service:
     ```bash
     docker compose -f infrastructure/compose.prod.yaml restart worker
     ```
  2. The periodic task `flowpilot.workers.tasks.reap_stale_heartbeats` scans for runs whose heartbeat has exceeded `WORKFLOW_HEARTBEAT_TIMEOUT_SECONDS` (default: 300s).
  3. Stale runs are either resumed from their last saved LangGraph checkpoint or cleanly transitioned to `failed` status with audit logs recorded.

### 3.3 Failed Scheduled Workflow Handling
- If an automated schedule fails during execution:
  - The failure is logged in `agent_runs` with `error_message`.
  - The schedule recurrence state in `scheduled_workflows` remains intact; the next recurrence will trigger as scheduled.
  - To inspect scheduling status:
    ```bash
    curl -H "Authorization: Bearer <ADMIN_TOKEN>" http://localhost/api/v1/monitoring/health
    ```

---

## 4. Observability & Health Endpoints

| Endpoint | Authentication | Purpose |
|---|---|---|
| `GET /api/v1/health` | Public | Liveness probe: returns `{"status": "healthy", "service": "flowpilot-api", "version": "1.0.0"}` |
| `GET /api/v1/monitoring/health` | Authenticated | Readiness & diagnostics: DB status, Redis status, Celery queue depth, outbox counters, LLM provider failure rates |

---

## 5. Security & Hardening Checklist

- [x] All database and Redis ports bound strictly to internal Docker bridge network (`flowpilot_prod_network`).
- [x] Reverse proxy terminates public traffic and strips internal headers.
- [x] Sensitive data filter active across all application loggers to scrub API keys and OAuth tokens.
- [x] Refresh token rotation deduplicated at Next.js BFF layer to prevent concurrent request race conditions.
- [x] Production settings reject default passwords and wildcard CORS origins.

---

## 6. HTTPS & Public Production Deployment Architecture

This section provides operational guidelines for transitioning FlowPilot AI from a local or private Docker environment to an Internet-facing production deployment.

### 6.1 Domain Configuration & DNS Setup
1. Allocate two subdomains or a root domain with a dedicated API/web scheme:
   - Web application & API: `app.yourdomain.com` (or `yourdomain.com`)
2. Configure DNS records:
   - `A` or `AAAA` record pointing to the public static IPv4/IPv6 address of your production host or reverse proxy load balancer.
   - Set TTL to 300 seconds during initial migration to allow rapid rollback if needed.

### 6.2 SSL/TLS Certificate Provisioning (Let's Encrypt / Certbot)
Obtain certificates using Certbot standalone or webroot mode:
```bash
sudo certbot certonly --standalone -d app.yourdomain.com --agree-tos -m admin@yourdomain.com
```
Certificates will be generated at `/etc/letsencrypt/live/app.yourdomain.com/fullchain.pem` and `privkey.pem`.
Mount these certificates into the NGINX container via `compose.prod.yaml` volume mounts:
```yaml
volumes:
  - /etc/letsencrypt/live/app.yourdomain.com:/etc/nginx/ssl/live/app.yourdomain.com:ro
  - ./nginx/nginx.https.conf.example:/etc/nginx/nginx.conf:ro
```

### 6.3 Reverse Proxy Headers & SSE Streaming
FlowPilot streams real-time execution events over Server-Sent Events (`/api/v1/agents/runs/{id}/stream`).
The reverse proxy must preserve streaming by ensuring:
- `proxy_buffering off;`
- `proxy_cache off;`
- `proxy_read_timeout 86400s;`
- `proxy_set_header X-Forwarded-Proto https;` (informs FastAPI and Next.js BFF that the original connection is encrypted)

### 6.4 Secure Cookies & CSRF Protection
In production (`ENVIRONMENT=production`), the Next.js BFF automatically sets:
- `Secure=true` on auth cookies (`flowpilot_access_token`, `flowpilot_refresh_token`).
- `HttpOnly=true` (inaccessible to JavaScript).
- `SameSite=Lax` (protects against cross-site request forgery while permitting top-level navigation).

### 6.5 Public OAuth Callback URLs
When registering third-party OAuth apps for Google Workspace and Slack, the authorized redirect URIs must match your public HTTPS origin:
- Google Redirect URI: `https://app.yourdomain.com/api/v1/integrations/google/callback`
- Slack Redirect URI: `https://app.yourdomain.com/api/v1/integrations/slack/callback`

### 6.6 Production CORS & Environment Settings
In `infrastructure/.env.prod`, configure:
```bash
ENVIRONMENT=production
DEBUG=false
APP_URL=https://app.yourdomain.com
CORS_ORIGINS=["https://app.yourdomain.com"]
```
Never use wildcard CORS (`["*"]`) in production when cookies or credentials are exchanged.

### 6.7 Firewall & Port Exposure Rules
- **Allow Public Inbound**:
  - Port `80/tcp` (HTTP -> HTTPS redirect)
  - Port `443/tcp` (HTTPS traffic)
  - Port `22/tcp` (SSH, restricted to bastion/VPN IP addresses)
- **Deny / Block External Inbound**:
  - Port `5432` (PostgreSQL) — strictly internal Docker bridge network.
  - Port `6379` (Redis) — strictly internal Docker bridge network.
  - Port `8000` (FastAPI backend) — strictly routed through NGINX.
  - Port `3000` (Next.js frontend) — strictly routed through NGINX.

