# FABINZI Configuration

Configuration is environment-specific. Secrets never belong in Git, templates, browser JavaScript, screenshots, or public documentation.

## REQUIRED — production runtime

| Variable | Requirement |
| --- | --- |
| `DJANGO_SECRET_KEY` | Explicit secret; production startup rejects the development fallback. |
| `DJANGO_DEBUG` | `false` / `0`. |
| `ENVIRONMENT` | `production`. |
| `PRIVATE_MEDIA_STORAGE_MODE` | `s3` for production private media. |
| `DJANGO_ALLOWED_HOSTS` | Actual production hostnames only. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Actual trusted HTTPS browser origins. |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` / `1`. |
| `FABINZI_PUBLIC_BASE_URL` | Canonical HTTPS public origin; non-HTTPS is rejected outside DEBUG. |
| `DATABASE_URL` | PostgreSQL connection string. |
| `REDIS_URL` | Redis-compatible broker/result backend used by Celery. |
| `INTEGRATION_ENCRYPTION_KEY` | Stable encryption key for provider secrets; required outside DEBUG. |

`FABINZI_PUBLIC_BASE_URL` is the single origin used for generated absolute URLs, canonical metadata, sitemap entries and social metadata. Same-origin browser API calls use relative URLs.

## OPTIONAL — core runtime

- `DEFAULT_LANGUAGE` — default `en`.
- `TIME_ZONE` — default `Africa/Cairo`.
- `API_ANON_RATE` — DRF anonymous throttle rate.
- `API_USER_RATE` — DRF authenticated throttle rate.
- `SENTRY_ENABLED` — enables bootstrap Sentry initialization when a DSN is also present.
- `SENTRY_DSN` — optional deployment-level Sentry DSN.

Optional does not mean “enabled by default.” Provider availability must be determined from actual deployment configuration.

## INTEGRATION-SPECIFIC

Database-backed `IntegrationConfig` supports:

- COD — internal payment option; no third-party credential.
- Paymob — optional online payment provider.
- Stripe — optional online payment provider.
- Mailgun — optional email delivery.
- Twilio — optional SMS delivery.
- Amazon S3 — production private object storage path.
- Cloudflare Images — optional image provider.
- Sentry — optional monitoring integration metadata.

Provider secrets are encrypted with `INTEGRATION_ENCRYPTION_KEY`. A provider must not be described as configured, sandbox-ready or production-ready merely because its adapter exists. `/Maneg/` Test Connection should be used only against credentials intentionally configured by the account owner.

## QA-ONLY / DEMO-ONLY

The guarded dataset uses:

- `FABINZI_DEMO_SEED_ENABLED`
- `DEMO_ADMIN_EMAIL`
- `DEMO_ADMIN_PASSWORD`
- `DEMO_ADMIN_TOTP_SECRET` — base32 secret used only by `provision_demo_admin_otp`.
- `DEMO_DESIGNER_EMAIL`
- `DEMO_DESIGNER_PASSWORD`
- `DEMO_MANUFACTURER_EMAIL`
- `DEMO_MANUFACTURER_PASSWORD`
- `DEMO_CUSTOMER_EMAIL`
- `DEMO_CUSTOMER_PASSWORD`

`FABINZI_DEMO_SEED_ENABLED` must remain false in production. The production `render.yaml` does not request demo passwords. QA/demo secrets belong only in a protected non-production environment.

## Local development

`.env.example` contains safe names/placeholders. Copy it to `.env` locally and provide local values. `PRIVATE_MEDIA_STORAGE_MODE=local` is allowed only for development/test environments; the settings module rejects it for production-like environments.

## Security-derived settings

When DEBUG is false the application enables secure session/CSRF cookies, HTTPS redirect by default, one-year HSTS, subdomain HSTS/preload, `DENY` framing, content-type nosniff, same-origin referrer policy and cross-origin opener policy. Custom middleware also applies restrictive permissions/resource headers and `X-Robots-Tag` to non-public surfaces.

The custom CSRF failure view is `apps.platform_ops.launch_views.csrf_failure`; it renders a branded recovery page without exposing the internal rejection reason.
