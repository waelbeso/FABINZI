# FABINZI Render Deployment

## Target

Current public URL:

```text
https://fabinzi-web.onrender.com
```

The repository contains a Render Blueprint in `render.yaml`.

## Required services

The current application architecture uses:

1. `fabinzi-web` — Django/Gunicorn web service.
2. `fabinzi-db` — persistent PostgreSQL database.
3. `fabinzi-redis` — Render Key Value (Redis-compatible/Valkey) used by Celery.
4. `fabinzi-worker` — Celery worker for asynchronous delivery work.
5. `fabinzi-beat` — Celery Beat scheduler for periodic notification dispatch.

The worker and Beat services are part of the implemented communications subsystem. External Mailgun/Twilio providers may remain disabled; the processes should still be healthy.

## Deployment flow

The Docker image installs Python dependencies and copies the application. The Render web `dockerCommand` performs:

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application ...
```

No demo seed command is present in Docker build/start, migrations, application initialization, worker startup, or Beat startup.

## Health checks

Render should use:

```text
/readyz/
```

for deployment health checks because it verifies database connectivity.

Use `/healthz/` for basic liveness and `/api/v1/health/` for API liveness.

## Data persistence

PostgreSQL is the durable system of record. The Blueprint uses a persistent paid PostgreSQL plan rather than treating a free, expiring database as a production QA baseline.

Render Key Value is transport infrastructure for Celery and is not the source of truth for customer, order, product, or finance data.

Deployments must never recreate or reset database data.

## Environment configuration

The Blueprint links common non-secret/runtime configuration through the `fabinzi-runtime` environment group and wires `DATABASE_URL`/`REDIS_URL` from managed Render resources.

For an existing Render service, confirm these values in the Render Dashboard before deployment:

- `FABINZI_PUBLIC_BASE_URL=https://fabinzi-web.onrender.com`
- `DJANGO_ALLOWED_HOSTS` includes the Render hostname.
- `DJANGO_CSRF_TRUSTED_ORIGINS` includes the HTTPS Render origin/pattern.
- `DJANGO_DEBUG=false`
- `INTEGRATION_ENCRYPTION_KEY` is stable and shared by web, worker, and Beat.
- `DJANGO_SECRET_KEY` is stable and shared by web, worker, and Beat.

Do not rotate `INTEGRATION_ENCRYPTION_KEY` after provider secrets have been encrypted unless a controlled re-encryption procedure is performed.

## Demo credentials on Render

Demo credential variables are intentionally declared as secret/manual values. For an existing service, set them through the Render Dashboard or another approved secret-management path.

To enable a one-time seed temporarily:

```text
FABINZI_DEMO_SEED_ENABLED=true
```

Then explicitly run in a Render shell/job:

```bash
python manage.py seed_demo
```

After successful seeding, set:

```text
FABINZI_DEMO_SEED_ENABLED=false
```

The command is never an automatic deployment hook.

## External integrations

Keep Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images, and Sentry disabled until their Control Center configuration is complete and Test Connection succeeds where required.

COD remains available for QA without external payment credentials.

## Media decision for QA

The demo dataset uses original SVG files committed under `static/demo/`. The database `MediaAsset` rows point to these stable static references. This avoids relying on Render's ephemeral local filesystem while preserving the existing production media/provider abstraction.

Production user-uploaded arbitrary media should use the existing durable provider path (Amazon S3 when configured). Do not treat Render local disk as durable media storage unless the architecture is intentionally changed later.

## Live validation checklist

After deployment verify:

- `/`
- `/app/`
- `/store/`
- `/studio/`
- `/artwork/`
- `/designer/`
- `/manufacturer/`
- `/Maneg/`
- `/healthz/`
- `/readyz/`
- `/api/v1/health/`

Then verify authenticated RBAC and the QA journeys in `docs/DEMO_QA.md`.
