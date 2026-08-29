# FABINZI Production Deployment

This document describes the repository-defined production topology. It does **not** assert that the currently running public service is on the latest repository revision, that optional integrations are configured, or that account-owner operational checks have been completed.

## Production Blueprint

`render.yaml` defines:

1. `fabinzi-web` — Django/Gunicorn Docker web service.
2. `fabinzi-db` — paid Render PostgreSQL 17 (`basic-256mb`).
3. `fabinzi-redis` — Render Key Value/Redis-compatible Celery transport.
4. `fabinzi-worker` — Celery worker.
5. `fabinzi-beat` — Celery Beat scheduler.

The production Blueprint tracks `main`. This checkpoint does not merge or deploy `main`.

## Required production configuration

The Blueprint sets non-secret production policy including:

- `DJANGO_DEBUG=0`
- `ENVIRONMENT=production`
- `PRIVATE_MEDIA_STORAGE_MODE=s3`
- HTTPS redirect enabled
- demo seeding disabled
- the Render public origin and host/CSRF policy

Render generates `DJANGO_SECRET_KEY` and `INTEGRATION_ENCRYPTION_KEY` for the environment group. These values must remain stable for the deployed environment, especially the integration encryption key after provider credentials have been encrypted.

`DATABASE_URL` and `REDIS_URL` are wired from the dedicated Render resources.

## Web startup order

`render-start.sh` performs:

```text
python manage.py reconcile_migration_state
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application ...
```

No demo seed or provider test is part of startup.

## Health and readiness

- `/healthz/` — liveness plus non-secret Render source identity (`branch`, `commit`, `service`) when supplied by Render.
- `/readyz/` — database readiness only.
- `/api/v1/health/` — API liveness.

These endpoints do not claim provider health, Celery health, backup status, email/SMS delivery, or payment success.

## Private media

Production is configured fail-closed for S3 private media. Before a real go-live, the account owner must configure and test an isolated production Amazon S3 `IntegrationConfig`. Private uploads must not fall back to Render local disk.

## Optional integrations

Paymob, Stripe, Mailgun, Twilio, Cloudflare Images and Sentry may remain disabled until intentionally configured. COD is the internal payment option and requires no external credential. A production launch report must classify every optional provider from actual configuration rather than adapter existence.

## Deployment sequence

1. Confirm the intended release SHA and CI are GREEN.
2. Confirm production environment values and the public origin in Render.
3. Confirm a recoverable PostgreSQL point per `BACKUP_AND_RECOVERY.md`.
4. Confirm production S3 configuration before accepting private-media writes.
5. Deploy the web/worker/Beat revision through the approved Render/main release process.
6. Wait for `/readyz/` to be healthy.
7. Verify `/healthz/` reports the exact intended deployed source commit.
8. Run non-destructive public/account/Commerce/portal smoke checks.
9. Verify actual worker/Beat logs if async delivery is required for the release.
10. Verify only the external integrations intended for that release.

## Rollback

Application-only regressions should roll back to a known source revision that is schema-compatible with the current database. If a migration or data change is not safely reversible, use the database recovery runbook rather than pretending a source rollback alone restores data. Validate the restored environment before cutover.

## QA separation

Production must not be used for demo seeding or live E2E test mutation. The repository contains a separate `render-qa.yaml` architecture for the future isolated QA return. The unresolved external QA/live gates are preserved in `DEFERRED_LIVE_E2E.md` and must be resumed after Flutter.

## Production launch limitations to resolve operationally

Repository readiness cannot prove:

- the exact live production deployment SHA until a release is actually deployed,
- actual production S3/provider credentials,
- worker/Beat runtime health,
- provider connectivity,
- backup restore execution,
- public legal approval,
- public support contact coordinates.

Those facts must be verified by the account owner during the later go-live checkpoint, not invented here.
