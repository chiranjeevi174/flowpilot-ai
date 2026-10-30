# FlowPilot AI — WhatsApp Business Cloud API Integration Guide

A setup, security, and troubleshooting guide for integrating the **Meta WhatsApp Business Platform (Cloud API)** with FlowPilot AI.

FlowPilot AI supports WhatsApp automation through its user-managed **App Connections** module, with human-in-the-loop approvals, encrypted credential storage, persistent execution records, and webhook-based delivery tracking.

This guide covers development testing, production configuration, approved message templates, webhook subscriptions, and common integration failures.

---

## 1. Integration Overview

The WhatsApp integration enables authorized FlowPilot users to:

- Connect a WhatsApp Business Account (WABA).
- Configure their own Meta application credentials.
- Send supported WhatsApp messages and approved templates.
- Review external actions before dispatch.
- Monitor Meta API responses.
- Track message delivery through webhooks.
- Inspect execution and external-action audit records.

### Responsibilities

| Responsibility | Owner |
|---|---|
| Meta developer account registration | User / Administrator |
| Meta application creation | User / Administrator |
| WABA and phone number configuration | User / Administrator |
| Test recipient verification | User / Administrator |
| Access token generation | User / Administrator |
| App Connections credential entry | User |
| Webhook registration | User / Administrator |
| Webhook endpoint implementation | FlowPilot AI |
| Credential encryption | FlowPilot AI |
| Human approval enforcement | FlowPilot AI |
| Message execution and auditing | FlowPilot AI |
| Delivery-status processing | FlowPilot AI |

> **Security:** Never commit access tokens, application secrets, encryption keys, or personal credentials to GitHub. Do not paste production secrets into README files, screenshots, issue reports, or AI conversations.

---

## 2. Prerequisites

Before configuring the integration, ensure you have:

1. A running FlowPilot AI installation.
2. A registered FlowPilot user account.
3. Access to Meta for Developers.
4. A Meta business portfolio or an eligible business account.
5. A WhatsApp Business Account.
6. A configured WhatsApp sender phone number or Meta-provided development test number.
7. Permission to manage the relevant Meta application and business assets.
8. A publicly reachable HTTPS endpoint for receiving live webhooks.

Useful portals:

- [Meta for Developers](https://developers.facebook.com/)
- [Meta Business Settings](https://business.facebook.com/settings/)
- [WhatsApp Manager](https://business.facebook.com/wa/manage/)
- [Meta WhatsApp Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api/)

Meta periodically changes its developer-console navigation and available configuration options. Follow the equivalent current settings if screen labels differ.

---

## 3. Create a Meta Application

### Step 3.1 — Register as a Developer

1. Open Meta for Developers.
2. Sign in using your Meta account.
3. Complete any required developer registration or verification.
4. Ensure you have access to the intended business portfolio.

### Step 3.2 — Create an Application

1. Open **My Apps**.
2. Select **Create App**.
3. Choose the relevant business messaging or WhatsApp use case offered by Meta.
4. Associate the application with the appropriate business portfolio when prompted.
5. Complete the application creation process.

Example application name:

```text
FlowPilot AI Business Automation
```

The exact creation wizard may vary by account and Meta developer-console version.

### Step 3.3 — Configure WhatsApp

Open the WhatsApp product or WhatsApp configuration area within your Meta application.

For development, Meta may provide a test WhatsApp Business Account and test sender number.

Use the associated API setup area to retrieve the identifiers required by FlowPilot.

---

## 4. Obtain WhatsApp Credentials

The integration requires several Meta identifiers and credentials.

| Credential | Purpose | Sensitive? |
|---|---|---|
| Meta App ID | Identifies the Meta application | No, but manage carefully |
| Meta App Secret | Validates provider webhook signatures | Yes |
| WhatsApp Business Account ID | Identifies the WABA | No, but manage carefully |
| Phone Number ID | Identifies the Cloud API sender | No, but manage carefully |
| Access Token | Authorizes Graph API requests | Yes |
| Webhook Verify Token | Validates webhook registration challenges | Yes |

### 4.1 Phone Number ID

In your Meta WhatsApp API setup, locate the sender's **Phone Number ID**.

This is an identifier assigned by Meta, not the sender's actual telephone number.

### 4.2 WhatsApp Business Account ID

Locate the WABA associated with your sender.

The WABA ID is required for certain account-management operations, including webhook subscription management.

### 4.3 Meta App ID and App Secret

Open the application's basic settings to locate its App ID and App Secret.

The App Secret must remain confidential.

FlowPilot uses the configured secret for cryptographic verification of incoming webhook payloads.

### 4.4 Access Token

Development environments may provide a temporary access token.

Temporary tokens expire and should not be treated as permanent production credentials.

For persistent deployment, configure an appropriately authorized system-user access token using Meta Business Settings.

The precise system-user creation and token-management options depend on the business account and permissions available to the administrator.

Where applicable:

1. Create or select an authorized system user.
2. Assign the intended Meta application.
3. Assign the appropriate WhatsApp Business Account.
4. Grant only the permissions required for the intended operations.
5. Generate an access token using the available supported expiration policy.
6. Store the token securely.

Relevant permissions can include:

```text
whatsapp_business_messaging
whatsapp_business_management
```

Do not grant unrestricted administrative permissions when a narrower supported role is sufficient.

Record the token's expiration or renewal requirements in your operational procedures.

---

## 5. Configure WhatsApp in FlowPilot AI

### Recommended Method: App Connections

FlowPilot AI supports user-managed credentials through its frontend.

1. Sign in to FlowPilot AI.
2. Open **App Connections**.
3. Select **WhatsApp Business**.
4. Open the provider setup instructions.
5. Enter the required Meta identifiers and credentials.
6. Save the configuration.
7. Run the available connection test.
8. Review the resulting connection status.

The interface supports saved configuration indicators and secure credential replacement.

Previously stored secrets are represented through masked indicators rather than being returned to the browser in plaintext.

Updating a non-sensitive setting does not require replacing every previously stored secret.

### Deployment-Level Configuration

FlowPilot separates user-managed credentials from infrastructure-level security settings.

The backend remains responsible for secure environment configuration, authentication, encryption keys, trusted origins, and any required webhook-level settings.

For example, the encryption configuration includes:

```dotenv
INTEGRATION_ENCRYPTION_KEYS=your_generated_fernet_key
```

Use an actual securely generated Fernet key.

Do not substitute this example value.

### Legacy Development Configuration

Earlier FlowPilot development builds supported WhatsApp credentials directly through `backend/.env`, using variables such as:

```dotenv
WHATSAPP_APP_ID=your_app_id
WHATSAPP_APP_SECRET=your_app_secret
WHATSAPP_BUSINESS_ACCOUNT_ID=your_waba_id
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_ACCESS_TOKEN=your_access_token
WHATSAPP_WEBHOOK_VERIFY_TOKEN=your_private_verify_token
```

These represent the older server-managed configuration approach.

**Production external-action execution must not silently fall back to a developer's global credentials when an authenticated user has not configured their own required connection.**

The October 28, 2026 security audit reported that this fallback was restricted to explicitly configured non-production environments.

Use the current backend configuration schema as the authority for which webhook-level settings remain deployment-managed.

---

## 6. Verify a Development Test Recipient

Meta development environments may restrict outbound messaging to verified test recipients.

To register an eligible recipient:

1. Open the WhatsApp API setup section in Meta for Developers.
2. Find the recipient-management controls.
3. Add the intended recipient number with its international country code.
4. Complete Meta's verification process.
5. Confirm the recipient appears in the permitted test-recipient list.

Example international format:

```text
+919XXXXXXXXX
```

This is an illustrative format, not a real recipient number.

Use only numbers that you own or have permission to contact.

**Important:** Adding a recipient to FlowPilot does not automatically verify that recipient in Meta's development environment.

---

## 7. Configure the WhatsApp Webhook

FlowPilot receives WhatsApp delivery-status events through a dedicated webhook endpoint.

### Canonical Webhook Path

The canonical callback path is:

```text
/api/v1/webhooks/whatsapp
```

The complete production URL follows this structure:

```text
https://your-domain.example/api/v1/webhooks/whatsapp
```

The October 28, 2026 audit also reported backward-compatible routing aliases for an earlier integration callback path.

Use the canonical endpoint for all new Meta configurations.

### 7.1 Local Development with HTTPS (Optional ngrok Tunnel)

> [!NOTE]
> **ngrok is unnecessary for ordinary application workflows and outbound WhatsApp API requests.**
> You do not need ngrok to use FlowPilot AI or send outbound WhatsApp messages and pre-approved templates through Meta's Cloud API.
> 
> However, because Meta requires a publicly reachable HTTPS endpoint to deliver incoming webhook notifications, a public HTTPS tunnel (such as ngrok) is required if you wish to receive and test incoming webhook callbacks (inbound delivery receipts: `sent`, `delivered`, `read`, `failed` or incoming user messages) against your local development environment.

If you are testing incoming webhook callbacks locally:

1. Ensure FlowPilot AI is running (e.g. via `start-dev.cmd` from the project root) with FastAPI responsive on port `8000`.
2. Open a separate terminal and execute:

```cmd
ngrok http 8000
```

3. Combine your active HTTPS tunnel address with the canonical callback path:

```text
https://YOUR-NGROK-DOMAIN/api/v1/webhooks/whatsapp
```

*(For example: `https://your-tunnel-id.ngrok-free.app/api/v1/webhooks/whatsapp`)*

Replace `YOUR-NGROK-DOMAIN` with the actual public HTTPS address provided by your tunnel service. Use this full URL when registering the callback in Meta.

### 7.2 Register the Callback in Meta

In the relevant Meta WhatsApp webhook configuration area:

1. Open the webhook settings.
2. Enter the public HTTPS callback URL.
3. Enter the configured webhook verify token.
4. Select the provider's verification action.
5. Confirm that the verification challenge succeeds.
6. Subscribe to the required `messages` webhook field.

The verify token entered in Meta must match the value configured for the FlowPilot webhook verification service.

### 7.3 Subscribe the Application to the WABA

**This step is essential.**

Successfully registering a webhook URL or subscribing to the `messages` field does not necessarily complete the WABA-level application subscription.

Ensure that the Meta application is subscribed to the actual WhatsApp Business Account being used.

Meta exposes the following Graph API operation:

```http
POST /{GRAPH_API_VERSION}/{WABA_ID}/subscribed_apps
```

Example URL structure:

```text
https://graph.facebook.com/{GRAPH_API_VERSION}/{WABA_ID}/subscribed_apps
```

Send the request using an authorized access token with the required permissions.

To inspect existing subscriptions, use the corresponding GET operation:

```http
GET /{GRAPH_API_VERSION}/{WABA_ID}/subscribed_apps
```

Use the Graph API version supported by the application configuration rather than relying on a permanently hardcoded version.

This WABA subscription enables configured webhook events for the associated account to reach the application's callback endpoint.

---

## 8. Webhook Security

Webhook verification and webhook event authentication are separate operations.

### Verification Challenge

Meta sends a GET request containing verification parameters.

FlowPilot validates the supplied verification token before returning the expected challenge value.

### Event Signature Verification

Incoming webhook POST requests include the header:

```text
X-Hub-Signature-256
```

The signature is based on HMAC-SHA256 over the raw request body using the Meta App Secret.

Conceptually:

```text
HMAC-SHA256(raw_request_body, META_APP_SECRET)
```

The backend validates the received signature before trusting or processing the event payload.

An invalid or missing required signature must be rejected.

Never disable signature validation to make a failing integration test pass.

### Production Recommendations

- Use HTTPS.
- Keep the Meta App Secret confidential.
- Validate webhook signatures.
- Protect against duplicate webhook processing.
- Avoid logging access tokens or complete sensitive payloads.
- Monitor verification failures.
- Preserve relevant delivery events for troubleshooting.

---

## 9. WhatsApp Messaging Rules

Meta controls which messages a business can send and under what conditions.

### 9.1 Customer Service Window

A customer service window normally opens when a WhatsApp user messages the business.

Within the supported 24-hour window, the business can respond with permitted non-template messages.

Outside that window, business-initiated messaging generally requires an approved message template.

Do not rely on an assumed open window without checking the relevant provider rules and available messaging context.

### 9.2 Approved Message Templates

Templates are used for supported business-initiated messaging.

To create a template:

1. Open WhatsApp Manager.
2. Navigate to message-template management.
3. Create a template.
4. Choose the appropriate category.
5. Set the language.
6. Define the approved content and parameters.
7. Submit the template for Meta review.
8. Confirm its approved status before use.

Illustrative template:

```text
Template: order_update

Hello {{1}}, your order {{2}} has been confirmed.
```

The name, language, parameter count, and supplied values must match the approved template configuration.

### 9.3 Pricing

Meta introduced per-message pricing for template messaging on July 1, 2025, with later pricing updates.

Charges can depend on:

- Message category.
- Recipient country or region.
- Applicable pricing tier.
- Delivery outcome.
- Current provider pricing policies.

Do not rely on historical conversation-based pricing descriptions or assume that an earlier monthly free-message allowance is still applicable.

Review the official pricing information before enabling high-volume automations:

[Meta WhatsApp Business Platform Pricing](https://developers.facebook.com/docs/whatsapp/pricing/)

---

## 10. Human-in-the-Loop Approval

FlowPilot treats WhatsApp message dispatch as a sensitive external operation.

The intended recipient and message parameters must be presented for authorization before dispatch.

### Execution Lifecycle

```text
User Workflow Request
         |
         v
Intent Analysis
         |
         v
Workflow Planning
         |
         v
WhatsApp Action Prepared
         |
         v
Persistent LangGraph Checkpoint
         |
         v
    AWAITING_APPROVAL
         |
         +-----------------------+
         |                       |
         v                       v
    User Approves           User Rejects
         |                       |
         v                       v
Parameter Integrity       Action Terminated
Verification              No Dispatch
         |
         v
Celery Worker
         |
         v
Meta Cloud API
         |
         v
API Response Recorded
         |
         v
Webhook Delivery Updates
```

### Parameter Integrity

Sensitive action parameters are represented using canonical JSON and protected using an SHA-256 parameter digest.

Relevant fields can include:

- Recipient number.
- Message body.
- Template name.
- Template language.
- Template parameters.

The implementation checks parameter integrity before performing the approved action.

If relevant parameters change after authorization, the previously approved action must not be dispatched as though it were unchanged.

### Approval Notifications

When an execution is awaiting authorization, FlowPilot can create a persistent notification linking directly to the relevant approval record.

Opening or dismissing the notification does not approve the action.

Approval and rejection remain explicit user decisions.

---

## 11. Delivery Status and Audit Tracking

A successful Graph API response does not guarantee that a message reached the recipient.

Meta may initially return a message identifier, commonly beginning with:

```text
wamid.
```

FlowPilot records the provider response and processes subsequent webhook status events.

### Supported Status Terminology

| Status | Meaning |
|---|---|
| Accepted | Meta API accepted the request for processing |
| Sent | Meta reported the message as sent |
| Delivered | Meta reported delivery to the recipient |
| Read | Meta reported a read event, where available |
| Failed | Meta reported an unsuccessful delivery or related failure |

Not every message necessarily produces every status, and downstream events may be delayed or absent.

**Do not describe `accepted` as confirmed handset delivery.**

FlowPilot's external-action audit trail and delivery-status interface should distinguish these states.

---

## 12. Troubleshooting

### Problem: Access Token Expired

**Symptoms**

- Authorization errors.
- Previously functioning API calls begin failing.
- Connection tests no longer succeed.

**Resolution**

1. Inspect the token's validity in Meta.
2. Generate or renew an authorized token.
3. Replace the stored credential in App Connections.
4. Test the connection again.
5. Where backend-level development settings were changed, restart the affected backend and worker processes.

A temporary development token is not suitable for unattended long-term production operations.

### Problem: Meta Accepts the Message, but the Recipient Does Not Receive It

An accepted API request is not proof of delivery.

Check:

1. The recipient number.
2. Test-recipient verification requirements.
3. The Meta application's current mode.
4. The sender's account status.
5. Template approval and parameters.
6. Any provider error response.
7. Subsequent delivery webhooks.

Inspect the actual provider delivery status rather than assuming the message was delivered.

### Problem: No Delivery Webhooks Arrive

Verify all of the following:

- FastAPI is running and publicly reachable.
- The HTTPS tunnel or domain is valid.
- Meta uses the canonical callback path.
- The verify token matches.
- The `messages` webhook field is subscribed.
- The application is subscribed to the correct WABA.
- The Meta App Secret used for signature verification is correct.

The WABA-level subscription is especially important.

Check the application subscription using:

```http
GET /{GRAPH_API_VERSION}/{WABA_ID}/subscribed_apps
```

### Problem: WhatsApp Business Account Locked

Meta may return provider-level restrictions, including error code:

```text
131031
```

A locked or restricted WABA must be investigated through Meta's business/account status and support processes.

Changing FlowPilot code or repeatedly retrying the same rejected request does not remove a provider-imposed account restriction.

### Problem: Message Cannot Be Sent Outside the Customer Service Window

Check whether the recipient has an open customer service window.

Where the operation is business-initiated or the window is closed, use an appropriately approved message template.

Inspect the exact Meta error response rather than assigning an assumed error code.

### Problem: Message Template Rejected

Verify:

- Template approval status.
- Exact template name.
- Language code.
- Required parameter count.
- Parameter structure.
- Sender account eligibility.

### Problem: Workflow Remains Awaiting Approval

Open FlowPilot's Approvals interface and inspect the action.

An approval notification does not automatically authorize message dispatch.

Explicitly approve or reject the proposed operation.

### Problem: Execution Is Queued but Does Not Progress

Confirm the following services are running:

- PostgreSQL.
- Redis.
- FastAPI.
- Celery Worker.
- Celery Beat, when the workflow is scheduled.

For local Windows development, all required services and containers are automatically started together when using `start-dev.cmd` from the project root. Alternatively, for isolated troubleshooting, the worker can be started manually from the backend directory with:

```cmd
uv run celery -A flowpilot.workers.celery_app worker --loglevel=info -P solo
```

---

## 13. Transitioning from Development to Production

Before enabling WhatsApp for production use:

1. Complete the applicable Meta business and application requirements.
2. Configure an eligible production WhatsApp sender.
3. Confirm the correct WABA and Phone Number ID.
4. Create and securely manage an appropriately authorized access token.
5. Configure WhatsApp through the intended user's App Connections.
6. Register the production HTTPS webhook.
7. Subscribe the `messages` webhook field.
8. Subscribe the application to the production WABA.
9. Confirm webhook signature verification.
10. Verify the production encryption configuration.
11. Ensure global developer-credential fallback is disabled.
12. Create and approve a controlled test workflow.
13. Verify the Meta API result.
14. Confirm the actual webhook delivery outcome.
15. Review FlowPilot's external-action audit record.

Use an authorized test recipient and an approved message template.

Do not interpret passing automated tests alone as proof that a production Meta account is unrestricted or ready for arbitrary outbound messaging.

---

## 14. Operational Security Checklist

Before public deployment, confirm:

- [ ] No Meta secrets are committed to Git.
- [ ] User credentials are stored through the approved encrypted connection mechanism.
- [ ] Production encryption keys are securely managed.
- [ ] The access token has appropriate permissions.
- [ ] Token expiration and renewal are documented.
- [ ] Webhooks use HTTPS.
- [ ] Webhook verification succeeds.
- [ ] POST payload signatures are validated.
- [ ] The application is subscribed to the correct WABA.
- [ ] Sensitive message operations require human approval.
- [ ] Cross-user connection isolation is enforced.
- [ ] Audit records are retained according to the deployment's policy.
- [ ] Provider API acceptance and delivery confirmation are displayed separately.
- [ ] Production provider fallback does not use another user's or a developer's credentials.

---

## 15. Related Documentation

- [Main Project README](../README.md)
- [Backend README](../backend/README.md)
- [Frontend README](../frontend/README.md)
- [External Integrations Setup](integrations-setup.md)
- [Operations and Recovery](operations-and-runbooks.md)
- [Production Readiness Audit](production_readiness_audit_report.md)

---

## Integration Status

The FlowPilot AI engineering audit dated October 28, 2026 reported implementation and automated validation of WhatsApp webhook handling, approval security, user-scoped credentials, and production fallback restrictions.

Actual message delivery remains dependent on Meta account eligibility, valid provider credentials, sender configuration, template approval, recipient eligibility, and live webhook delivery.

**The correct production success criterion is a verified end-to-end operation—not merely an HTTP-success response from Meta.**