# Security model and review notes

The October 28, 2026 local audit reported 8 passing multi-user isolation scenarios and a release decision of **Ready with documented limitations**. Treat this as reported local verification, not an independent penetration test or certification.

## Principal controls

- Authenticated ownership checks for workflows, schedules, approvals, notifications, BYOK and App Connections; unrelated resource identifiers should not reveal another user's records.
- User-managed secrets encrypted at rest with server-managed MultiFernet keys. Existing sensitive values are masked in the UI and not returned through ordinary GET endpoints.
- Provider OAuth includes user/connection state binding, expiry and one-time consumption; production callbacks must match trusted registered URLs.
- Sensitive external actions require explicit approval, with parameter-digest verification before dispatch.
- WhatsApp webhook signatures and account/message correlation govern receipt updates. API acceptance is distinct from recipient delivery.
- Development-only `.env` credential fallbacks must not give production users access to developer-owned accounts.

## Operational responsibilities

Secure origins/cookies, key storage and rotation, least-privilege provider scopes, backup/restore procedures, dependency checks, secret scanning, log redaction, and live-provider account verification remain deployment responsibilities. Provider-specific restrictions can prevent a real send even when internal tests pass.

## Disclosure

Before publishing, add a security contact/reporting procedure appropriate to the eventual repository and maintainer setup. Avoid claiming compliance certification or absolute prevention of attacks solely from automated tests.
