# FABINZI Configuration

## Core runtime variables

| Variable | Purpose | Production requirement |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Django cryptographic signing secret | Required |
| `DJANGO_DEBUG` | Django debug mode | Must be `false` |
| `ENVIRONMENT` | Environment label used by monitoring | Set to `production` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts | Required |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated trusted HTTPS origins | Required for deployed browser forms/API session auth |
| `DJANGO_SECURE_SSL_REDIRECT` | HTTPS enforcement | `true` in production |
| `FABINZI_PUBLIC_BASE_URL` | Single authoritative public origin for generated absolute URLs | Required |
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `REDIS_URL` | Redis/Valkey connection string for Celery | Required when worker/Beat are deployed |
| `INTEGRATION_ENCRYPTION_KEY` | Encryption secret for database-backed provider credentials | Required outside DEBUG |
| `DEFAULT_LANGUAGE` | Default UI language | Optional, default `en` |
| `TIME_ZONE` | Application time zone | Optional, default `Africa/Cairo` |
| `API_ANON_RATE` | DRF anonymous throttle rate | Optional |
| `API_USER_RATE` | DRF authenticated throttle rate | Optional |

## Public URL configuration

Set exactly one canonical origin:

```text
FABINZI_PUBLIC_BASE_URL=https://fabinzi-web.onrender.com
```

Do not scatter the deployment domain through application code. Server-generated absolute URLs should use `apps.platform_ops.public_urls.absolute_public_url()`. Same-origin browser calls should use relative `/api/v1/...` paths.

When the public domain changes later, update the environment variable and corresponding host/CSRF configuration rather than editing code.

## Sentry

Bootstrap variables:

- `SENTRY_ENABLED`
- `SENTRY_DSN`

The platform also contains database-backed integration configuration for Sentry. Keep monitoring disabled until a valid DSN and intended policy are configured.

## Payment, communications, and media integrations

Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images, and integration-level Sentry settings are stored in the existing `IntegrationConfig` model and managed through `/Maneg/` where supported.

Provider secrets must never be committed to `.env.example`, `render.yaml`, source code, or public documentation.

COD is the default QA-safe payment method and does not require a third-party credential.

## Demo-only variables

The QA seed is protected by:

```text
FABINZI_DEMO_SEED_ENABLED=false
```

The command additionally reads:

- `DEMO_ADMIN_EMAIL`
- `DEMO_ADMIN_PASSWORD`
- `DEMO_DESIGNER_EMAIL`
- `DEMO_DESIGNER_PASSWORD`
- `DEMO_MANUFACTURER_EMAIL`
- `DEMO_MANUFACTURER_PASSWORD`
- `DEMO_CUSTOMER_EMAIL`
- `DEMO_CUSTOMER_PASSWORD`

Passwords have no source-controlled defaults. The command refuses to run when any required password value is empty.

For a real production launch, keep the safety flag false and remove demo credentials from the runtime environment.

## Reverse proxy / HTTPS

Production settings trust `X-Forwarded-Proto=https` from the hosting proxy and use secure session/CSRF cookies, HTTPS redirection, HSTS, same-origin referrer policy, frame denial, content-type nosniff, and cross-origin opener/resource policy protections.

## `.env` handling

`.env.example` contains variable names and safe placeholders only. Copy it locally as `.env` and provide local values. `.env` itself must remain ignored by Git.
