# Stage 9 Acceptance — Communications & Hardening

Status: **COMPLETE**

Stage 9 closes the primary web implementation with a user-owned communications center and deployment/runtime hardening.

## Communications
- In-app notifications remain the always-on core channel.
- Authenticated users have a notification center plus API list/read/read-all actions.
- External email and SMS are explicit opt-in preferences; SMS requires E.164 contact format.
- Mailgun and Twilio remain disabled unless configured, enabled and successfully connection-tested in `/Maneg/`.
- New notifications create provider-specific delivery records only for opted-in users.
- Celery Beat dispatches queued/failed external deliveries; delivery history records provider, status, attempts and failures.
- External provider secrets remain encrypted through the existing integration configuration.

## Hardening
- DRF authenticated and anonymous throttles are enabled with environment-overridable rates.
- Production no longer silently accepts the DEBUG integration encryption key; a real key is mandatory outside DEBUG.
- Security headers add Permissions-Policy, Cross-Origin-Resource-Policy and X-Permitted-Cross-Domain-Policies alongside existing HSTS/cookie/frame/referrer controls.
- `/readyz/` performs a database readiness probe while `/healthz/` remains a lightweight liveness probe.
- Maintenance mode permits liveness/readiness, administration, static and account surfaces.
- Notification ownership is enforced server-side.
- `/Maneg/` remains OTP-protected for privileged administration.
- Automated Stage 9 tests cover ownership, opt-in communications, E.164 validation, readiness and headers.

## Boundary
Flutter/mobile delivery is the next major implementation phase. Stage 9 does not add a mobile client or silently enable any optional provider.
