# FABINZI

Greenfield implementation of the FABINZI digital fashion manufacturing marketplace.

> **Designer creates. Manufacturer produces. Customer buys. FABINZI orchestrates.**

This repository intentionally does **not** preserve or depend on any previous FABINZI implementation.

## Current status

**Stage 0 — Engineering Foundation: complete.** See `docs/STAGE_0_ACCEPTANCE.md`.

The repository now contains the production-oriented Django/DRF foundation, PostgreSQL migrations, Redis/Celery wiring, branded MFA-protected `/Maneg/` Control Center, integration health framework, media abstraction, announcements/maintenance controls, audit foundation, notification foundation, CI, and backup/recovery baseline.

## Stack

- Python / Django / Django REST Framework
- PostgreSQL
- Redis + Celery
- Amazon S3 + Cloudflare Images provider abstraction
- TOTP/MFA-protected branded Django Control Center at `/Maneg/`
- Arabic/English, RTL/LTR, Light/Dark/System theme foundation
- Sentry foundation (disabled until configured)

## Local bootstrap

```bash
cp .env.example .env
docker compose up -d db redis
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open `http://127.0.0.1:8000/Maneg/`. Privileged administration is designed to use two-factor authentication.

## Integration security

Optional integrations are disabled by default. COD is seeded enabled as the initial practical payment method. Provider credentials are not hard-coded. The integration model supports encrypted write-only secret payloads and a provider-specific Test Connection action with safe diagnostics.

## Greenfield rule

The historical FABINZI database, migrations, actors, portals, CSS, APIs, workflows and old source code are explicitly out of scope. The approved FABINZI logo is the only carried-forward product asset.
