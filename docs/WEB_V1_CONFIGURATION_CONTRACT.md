# FABINZI WEB v1.0 — Production Configuration & Security Contract

This document freezes source expectations; it does not claim account-level configuration is currently live.

## Required production runtime

- `DJANGO_SECRET_KEY` — explicit secret; development fallback is rejected outside DEBUG.
- `DJANGO_DEBUG=false`.
- `ENVIRONMENT=production`.
- `PRIVATE_MEDIA_STORAGE_MODE=s3`.
- `DJANGO_ALLOWED_HOSTS` — actual production hosts only.
- `DJANGO_CSRF_TRUSTED_ORIGINS` — actual HTTPS origins only.
- `DJANGO_SECURE_SSL_REDIRECT=true`.
- `FABINZI_PUBLIC_BASE_URL=https://...` — non-HTTPS is rejected outside DEBUG.
- `DATABASE_URL` — PostgreSQL.
- `REDIS_URL` — Celery broker/result transport.
- `INTEGRATION_ENCRYPTION_KEY` — stable key required outside DEBUG.

## Optional runtime

`DEFAULT_LANGUAGE`, `TIME_ZONE`, `API_ANON_RATE`, `API_USER_RATE`, `SENTRY_ENABLED`, `SENTRY_DSN`.

Database-backed optional adapters include COD, Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images and Sentry. Adapter existence is not provider-health evidence.

## QA-only values

`FABINZI_DEMO_SEED_ENABLED` plus DEMO identities/passwords/TOTP are QA-only and must not be production Blueprint credentials. Production keeps demo seeding disabled.

## Security freeze

WEB v1.0 preserves secure/HttpOnly session and CSRF cookies, SameSite=Lax, HTTPS redirect, HSTS, frame denial, content-type nosniff, same-origin referrer/opener policy, CSRF protection, API throttling, MFA for `/Maneg/`, tenant/RBAC checks, authorized private-media delivery, encrypted integration secrets, payment webhook verification/idempotency controls and private-route noindex behavior.

`/healthz/` may expose only semantic application version and non-secret hosting source identity (`branch`, `commit`, `service`). It must not expose secrets, DSNs, Redis credentials, provider credentials, encryption keys or an environment dump. `/readyz/` remains database readiness only.
