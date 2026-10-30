# FlowPilot AI — External Integrations & OAuth 2.0 Setup Guide

This document guides deployment administrators through configuring OAuth 2.0 applications and webhook endpoints for Google (Gmail & Google Sheets) and Slack.

---

## 1. Security Architecture & Credential Model

FlowPilot AI maintains strict separation across three distinct credential tiers:

| Credential Tier | Ownership | Storage | Purpose |
|---|---|---|---|
| **LLM Provider API Keys (BYOK)** | Individual User | PostgreSQL (MultiFernet Encrypted) | Direct LLM inference (Google Gemini, OpenAI, Groq). |
| **OAuth Application Credentials** | Deployment Administrator | Environment Variables (`.env`) | Client IDs, client secrets, and signing secrets owned by the FlowPilot deployment. |
| **User OAuth Access/Refresh Tokens** | Individual User | PostgreSQL (MultiFernet Encrypted) | Authorized user grants to external mailboxes, spreadsheets, and Slack workspaces. Scoped strictly per user. |

Provider client secrets **never** leave the server. All external integration access is strictly scoped to the authenticated user owning the connection. Multi-user cross-account token access is prohibited and cryptographically isolated.

---

## 2. Google Cloud Setup (Gmail & Google Sheets)

### Step 2.1 — Project Creation & API Enablement
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new Google Cloud project: `FlowPilot AI Automation`.
3. In **APIs & Services > Library**, search for and enable:
   - **Gmail API** (`gmail.googleapis.com`)
   - **Google Sheets API** (`sheets.googleapis.com`)
   - **Google People API / User Profile** (for user email & identity verification)

### Step 2.2 — OAuth Consent Screen
1. Go to **APIs & Services > OAuth consent screen**.
2. Select **User Type**:
   - **Internal**: If using Google Workspace for internal team members only (no public verification needed).
   - **External**: If allowing arbitrary Google accounts to connect (starts in "Testing" mode).
3. Fill in required App Information:
   - App Name: `FlowPilot AI`
   - User Support Email: Administrator email
   - Developer Contact Information: Administrator email
4. Click **Save and Continue**.

### Step 2.3 — Authorized Scopes
Add the following minimal scopes. Do not request broad Drive permissions:
- `https://www.googleapis.com/auth/userinfo.email` (Read user's email address)
- `https://www.googleapis.com/auth/userinfo.profile` (Read display name)
- `https://www.googleapis.com/auth/gmail.readonly` (Read and search emails)
- `https://www.googleapis.com/auth/gmail.compose` (Create email drafts)
- `https://www.googleapis.com/auth/gmail.send` (Send emails — guarded by Human Approval)
- `https://www.googleapis.com/auth/spreadsheets` (Read and append spreadsheet rows — writes guarded by Human Approval)

### Step 2.4 — OAuth 2.0 Client ID Creation
1. Go to **APIs & Services > Credentials**.
2. Click **Create Credentials > OAuth client ID**.
3. Application Type: **Web application**.
4. Name: `FlowPilot Backend Client`.
5. Authorized JavaScript Origins:
   - `http://localhost:3000` (Frontend development)
   - `http://localhost:8000` (Backend development)
6. Authorized Redirect URIs:
   - `http://localhost:8000/api/v1/integrations/google/callback`
   - *(Production URL):* `https://api.yourdomain.com/api/v1/integrations/google/callback`
7. Save and copy the **Client ID** and **Client Secret**.

### Step 2.5 — Test Users & Public Verification
- In "Testing" mode, Google limits access to designated test accounts. Add developer test accounts under **Test Users**.
- Moving to production with sensitive scopes (`gmail.send`, `gmail.readonly`) requires **Google Cloud Security Assessment / OAuth App Verification** (including privacy policy, YouTube video demo, and annual CASA tier 2 security validation for external distribution).

### Step 2.6 — Backend Environment Configuration
Add to `backend/.env`:
```bash
GOOGLE_CLIENT_ID="<your-google-client-id>.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="<your-google-client-secret>"
GOOGLE_REDIRECT_URI="http://localhost:8000/api/v1/integrations/google/callback"
```

---

## 3. Slack Workspace Integration & Events Setup

### Step 3.1 — Create Slack App
1. Go to [Slack API: Your Apps](https://api.slack.com/apps).
2. Click **Create New App > From scratch**.
3. App Name: `FlowPilot AI`.
4. Pick your development workspace and click **Create App**.

### Step 3.2 — OAuth & Permissions Configuration
1. In the sidebar, navigate to **OAuth & Permissions**.
2. Under **Redirect URLs**, click **Add New Redirect URL**:
   - `http://localhost:8000/api/v1/integrations/slack/callback`
   - *(Production URL):* `https://api.yourdomain.com/api/v1/integrations/slack/callback`
   - Click **Save URLs**.
3. Under **Bot Token Scopes**, add the minimum necessary scopes:
   - `channels:read` (View public channels in workspace)
   - `groups:read` (View private channels bot is invited to)
   - `chat:write` (Send messages as FlowPilot AI — guarded by Human Approval)
   - `chat:write.public` (Send messages to any public channel without joining)
   - `team:read` (View workspace team name and metadata)
4. Do **not** request workspace administration or user impersonation permissions.

### Step 3.3 — Retrieve Signing Secret & Credentials
1. Navigate to **Basic Information**.
2. Under **App Credentials**, copy:
   - **Client ID**
   - **Client Secret**
   - **Signing Secret** (Used to verify HMAC-SHA256 signatures on inbound webhooks)

### Step 3.4 — Event Subscriptions (Webhooks)
1. In the sidebar, select **Event Subscriptions** and toggle **Enable Events** to **On**.
2. Request URL:
   - In local development, use an HTTPS tunnel (e.g. `ngrok http 8000` or Cloudflare Tunnel):
     `https://<tunnel-id>.ngrok-free.app/api/v1/webhooks/slack`
   - FlowPilot automatically answers Slack's `url_verification` challenge.
3. Under **Subscribe to bot events**, add desired triggers:
   - `app_mention` (Triggered when bot is mentioned in a channel)
   - `message.channels` (Optional: listen to messages in channels bot belongs to)
4. Click **Save Changes**.

### Step 3.5 — Backend Environment Configuration
Add to `backend/.env`:
```bash
SLACK_CLIENT_ID="<your-slack-client-id>"
SLACK_CLIENT_SECRET="<your-slack-client-secret>"
SLACK_SIGNING_SECRET="<your-slack-signing-secret>"
SLACK_REDIRECT_URI="http://localhost:8000/api/v1/integrations/slack/callback"
```

---

## 4. Key Management & Rotation Procedures

### MultiFernet Secret Key Rotation
1. FlowPilot uses `MultiFernet` to encrypt all OAuth access tokens and refresh tokens.
2. To rotate keys without invalidating existing connections:
   - Generate a new 32-byte urlsafe base64 key using `flowpilot.core.encryption.generate_fernet_key()`.
   - Prepend the new key to `INTEGRATION_ENCRYPTION_KEYS` in `.env`:
     ```bash
     INTEGRATION_ENCRYPTION_KEYS='["<NEW_PRIMARY_KEY>", "<OLD_SECONDARY_KEY>"]'
     ```
   - All newly saved or refreshed tokens are automatically encrypted with the primary key.
   - Existing tokens encrypted with `<OLD_SECONDARY_KEY>` continue to decrypt seamlessly.

---

## 5. Idempotency & Human Approval Policies

All external real-world operations respect backend-enforced policies:
1. **Mandatory Approval Operations**:
   - `gmail_send_email`: Requires human decision + parameter digest check.
   - `slack_send_message`: Requires human decision + parameter digest check.
   - `sheets_append_rows`: Requires human decision + cell formula sanitization + parameter digest check.
2. **Idempotency Protection**:
   - Every external action generates a unique `idempotency_key` binding the `run_id`, `step_id`, `operation`, and SHA-256 parameter digest.
   - If a Celery task is re-delivered or a LangGraph checkpoint is replayed, the existing `ExternalAction` record returns the previous response without re-executing external side effects.
