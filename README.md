# FABINZI

FABINZI is a digital fashion manufacturing marketplace that connects Designers, Manufacturers, Customers, and FABINZI Platform Administration in one controlled workflow.

**Designer creates. Manufacturer produces. Customer buys. FABINZI orchestrates.**

The web platform manages garment design, artwork, ready-designed products, optional customer customization, manufacturer sourcing, checkout, production, quality control, fulfillment, finance, and platform operations through a Django/REST backend and responsive web applications.

## Product model

FABINZI keeps the main business concepts separate:

- **Garment Designs** define the manufacturable base garment, versions, size information, technical specifications, assets, and decoration zones.
- **Artwork** is independently created, reviewed, rights-declared, and published.
- **Ready Designed Products** combine an approved garment version with approved artwork and production placement.
- **Customer Customization** is optional and is created in Studio against supported decoration zones.
- **Manufacturer Capabilities** describe what a Manufacturer can actually produce, including cut-and-sew, printing, embroidery, finishing, and packaging.
- **Manufacturing Offers** are represented by RFQs, invitations, Manufacturer quotes, and Manufacturer selection.
- **Orders and Routing** connect confirmed customer orders with the selected production path.
- **Manufacturing and QC** track production milestones and quality inspection decisions.
- **Fulfillment** tracks packing, shipping, carrier information, tracking numbers, and delivery.
- **Payments and Finance** support COD by default, optional online payment providers, ledger entries, earnings, settlement requests, and payout readiness.
- **Communications** include in-app notifications with optional Mailgun/Twilio delivery, announcements, and maintenance messaging.

Printing and embroidery are Manufacturer capabilities, not separate marketplace actors. Shipping is a fulfillment service. Customer customization is never mandatory.

## Main web applications

| Surface | Purpose |
| --- | --- |
| `/` | Public FABINZI website |
| `/app/` | Customer application home and account/store journey |
| `/store/` | Public storefront marketplace |
| `/studio/` | Customer Customization Studio |
| `/artwork/` | Artwork Marketplace |
| `/designer/` | Designer Portal |
| `/manufacturer/` | Manufacturer Portal |
| `/orders/` | Customer orders and tracking |
| `/notifications/` | User notification center |
| `/Maneg/` | OTP-protected FABINZI Control Center |
| `/api/v1/` | Versioned REST API |
| `/healthz/` | Liveness check |
| `/readyz/` | Database readiness check |

## Technology stack

- Python 3.12
- Django 5.2
- Django REST Framework
- PostgreSQL
- Redis-compatible broker (Render Key Value/Valkey is supported)
- Celery worker and Celery Beat
- Gunicorn
- WhiteNoise for static files
- django-two-factor-auth / django-otp for privileged administration
- Optional Amazon S3 and Cloudflare Images media integrations
- Optional Paymob and Stripe payments
- Optional Mailgun and Twilio communications
- Optional Sentry monitoring

Flutter is planned as the customer mobile client for Android and iOS after the accepted web deployment/QA baseline. It is not part of the current web repository runtime.

## Features

- Designer and Manufacturer onboarding, verification, membership, and tenant-aware RBAC
- Versioned garment design and technical review
- Artwork publishing, IP declarations, moderation, and designed-product composition
- Manufacturer marketplace, capabilities, RFQs, quotes, and selection
- Storefront catalog, variants, Studio projects, and optional customer customization
- Checkout with immutable commercial snapshots and COD default
- Optional Paymob/Stripe payment initiation and signed webhook handling
- Manufacturer assignment, production milestones, QC, fulfillment, shipping, and tracking
- Finance ledger, Designer/Manufacturer earnings, settlement requests, payout profiles, and adjustments
- In-app notifications plus optional email/SMS delivery
- Announcements, maintenance mode, audit events, health/readiness endpoints, throttling, and security headers
- Arabic and English with RTL/LTR support
- Light/Dark/System theme preference persisted on the user account

## Local installation

### Requirements

- Python 3.12
- PostgreSQL
- Redis 7+ or a compatible Redis protocol server

### Setup

```bash
git clone https://github.com/waelbeso/FABINZI.git
cd FABINZI
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Create the PostgreSQL database referenced by `DATABASE_URL`, start Redis, then run:

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py check
python manage.py collectstatic --noinput
python manage.py runserver
```

For background communications, start these in separate terminals:

```bash
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
```

Create a normal Django superuser only when you need a new administrator:

```bash
python manage.py createsuperuser
```

The FABINZI Control Center uses OTP-required administration. Complete the normal two-factor setup flow for privileged access.

## Environment configuration

Copy `.env.example` and provide environment-specific values. Never commit `.env`.

### Required in production

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=false`
- `ENVIRONMENT=production`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SECURE_SSL_REDIRECT=true`
- `FABINZI_PUBLIC_BASE_URL`
- `DATABASE_URL`
- `REDIS_URL`
- `INTEGRATION_ENCRYPTION_KEY`

`FABINZI_PUBLIC_BASE_URL` is the authoritative public origin used whenever the backend must generate an absolute public URL. Same-origin browser API calls should continue to use relative paths. Changing the public domain therefore does not require application-code rewrites.

### Optional runtime configuration

- `DEFAULT_LANGUAGE`
- `TIME_ZONE`
- `API_ANON_RATE`
- `API_USER_RATE`
- `SENTRY_ENABLED`
- `SENTRY_DSN`

Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images, and the database-backed Sentry integration configuration remain disabled until explicitly configured and tested according to the Control Center workflow.

### Demo-only configuration

- `FABINZI_DEMO_SEED_ENABLED`
- `DEMO_ADMIN_EMAIL`
- `DEMO_ADMIN_PASSWORD`
- `DEMO_DESIGNER_EMAIL`
- `DEMO_DESIGNER_PASSWORD`
- `DEMO_MANUFACTURER_EMAIL`
- `DEMO_MANUFACTURER_PASSWORD`
- `DEMO_CUSTOMER_EMAIL`
- `DEMO_CUSTOMER_PASSWORD`

Do not reuse demo credentials in a real production launch.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for details.

## Running tests

The CI quality gates use PostgreSQL and Redis and run:

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py check
python manage.py collectstatic --noinput
pytest -q
```

CI also runs a production-settings Django deployment check.

## Demo data

FABINZI includes an optional, manually executed QA seed:

```bash
python manage.py seed_demo
```

The command **refuses to run** unless `FABINZI_DEMO_SEED_ENABLED=true`. It also requires demo passwords from environment variables. It is idempotent where practical and never runs from migrations, application startup, deployment startup, worker startup, or normal request processing.

For real production, keep:

```text
FABINZI_DEMO_SEED_ENABLED=false
```

See [docs/DEMO_QA.md](docs/DEMO_QA.md).

## Render deployment

The repository includes `render.yaml` for the current deployment topology:

- Django/Gunicorn web service
- persistent Render PostgreSQL
- Render Key Value for Celery transport
- Celery background worker
- dedicated Celery Beat service

The web service runs migrations and `collectstatic` before starting Gunicorn. `/readyz/` is the deployment health check. Demo seeding is not part of any automatic deployment command.

The current public origin is configured as:

```text
FABINZI_PUBLIC_BASE_URL=https://fabinzi-web.onrender.com
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for deployment and operational notes.

## External integrations

External integrations are intentionally optional. Disabled providers must not prevent core QA or COD operation. Configuration and secrets are stored through the existing FABINZI integration configuration architecture and should be managed through `/Maneg/` where implemented. No provider credential belongs in Git history.

## Localization

FABINZI supports:

- English (`en`) with LTR layout
- Arabic (`ar`) with RTL layout

User language preference is persisted on the account and reflected in the session.

## Themes

Users can persist `Light`, `Dark`, or `System` theme preference on their account.

## Security

The platform includes tenant-aware authorization, privileged OTP administration, CSRF/session protection, secure production cookies, HTTPS redirect/HSTS, clickjacking protection, security headers, API throttling, encrypted integration secrets, signed payment webhooks, immutable/audited workflow records where required, and append-only audit/financial patterns.

Do not weaken these controls for local testing or deployment convenience.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Render deployment](docs/DEPLOYMENT.md)
- [Demo and QA](docs/DEMO_QA.md)
- [Backup and recovery](docs/BACKUP_AND_RECOVERY.md)

## License

No open-source license has been granted for this repository. All rights are reserved by the project owner unless a separate license is explicitly published.
