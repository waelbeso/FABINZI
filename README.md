# FABINZI

FABINZI is a digital fashion platform that connects **Customers, Designers, Manufacturing Partners, and FABINZI Platform Administration** in one controlled design-to-production workflow.

**Designer creates. Manufacturer produces. Customer buys. FABINZI orchestrates.**

The current Web product covers public discovery, Designer Artwork, ready-designed products, optional Customer Studio customization, manufacturer sourcing, Commerce, production, QC, fulfillment/tracking, finance, notifications and the OTP-protected `/Maneg/` Control Center.

## Business model

- **Customer** — discovers published products/artwork, optionally customizes eligible products, checks out and follows persisted purchase/fulfillment state.
- **Designer** — manages garment design, Artwork, Designed Products, storefront/catalog, manufacturing RFQs and business visibility.
- **Manufacturer** — production partner that publishes manufacturing capabilities, responds to RFQs/quotes, completes assigned production/QC/packing and records shipment/tracking through the canonical fulfillment flow.
- **FABINZI Platform Administration** — manages and audits platform operations through `/Maneg/` with MFA.

A Manufacturer is **not** a catalog seller. Printing/embroidery are Manufacturer capabilities. Shipping is fulfillment. Customer customization is optional.

## Locked Commerce / production model

```text
Cart
→ Checkout
→ one Parent CustomerPurchase

Each CartItem
→ one CustomerOrder
→ one OrderItem
→ one ProductionJob
→ one FulfillmentRecord
```

Manufacturer execution remains:

```text
RFQ
→ Quote
→ Selection
→ ProductionJob
→ QC
→ Packing
→ Ready to Ship
→ canonical FulfillmentRecord
→ Shipment / Tracking
```

## Main Web surfaces

| Surface | Purpose |
| --- | --- |
| `/` | Public FABINZI site |
| `/store/` | Public storefront/product marketplace |
| `/artwork/` | Artwork Marketplace |
| `/manufacturers/` | Public Manufacturer capability directory |
| `/studio/` | Customer Customization Studio |
| `/app/` | Customer account home |
| `/orders/`, `/purchases/` | Customer order/purchase visibility |
| `/designer/` | Designer Portal |
| `/manufacturer/` | Manufacturer Portal |
| `/Maneg/` | MFA-protected Control Center |
| `/api/v1/` | Versioned REST API |
| `/healthz/`, `/readyz/` | Safe liveness/readiness endpoints |

Public trust information is available at `/about/`, `/terms/`, `/privacy/`, `/returns/`, `/shipping/`, and `/support/`. These repository pages are conservative baseline launch copy and are **not represented as lawyer-reviewed**. Jurisdiction-specific legal approval and public support coordinates remain operator responsibilities before a public production launch.

## Technology

- Python 3.12
- Django 5.2 + Django REST Framework
- PostgreSQL
- Redis-compatible transport
- Celery worker + Celery Beat
- Gunicorn
- WhiteNoise compressed manifest static delivery
- django-two-factor-auth / django-otp
- optional Amazon S3 / Cloudflare Images
- optional Paymob / Stripe
- optional Mailgun / Twilio
- optional Sentry

## Local setup

Requirements: Python 3.12, PostgreSQL, and Redis 7+ or a compatible Redis-protocol service.

```bash
git clone https://github.com/waelbeso/FABINZI.git
cd FABINZI
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure the local PostgreSQL/Redis values in `.env`, then:

```bash
python manage.py reconcile_migration_state
python manage.py migrate --noinput
python manage.py check
python manage.py collectstatic --noinput
python manage.py runserver
```

For background delivery work:

```bash
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
```

## Production configuration

Production requires explicit secure configuration including:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=false`
- `ENVIRONMENT=production`
- `PRIVATE_MEDIA_STORAGE_MODE=s3`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SECURE_SSL_REDIRECT=true`
- `FABINZI_PUBLIC_BASE_URL=https://...`
- `DATABASE_URL`
- `REDIS_URL`
- `INTEGRATION_ENCRYPTION_KEY`

Production startup rejects the development secret fallback, non-HTTPS public origin and local private-media mode. See [Configuration](docs/CONFIGURATION.md).

## Security

The Web product includes tenant-aware authorization, `/Maneg/` OTP/MFA, CSRF/session protection, secure production cookies, SSL redirect/HSTS, frame denial, content-type/referrer/cross-origin security headers, private-surface `noindex`, encrypted integration secrets, private-media authorization, payment callback/webhook validation, API throttling, payout masking and audit/finance controls implemented by the accepted domain architecture.

Health/readiness responses intentionally do not expose credentials or provider URLs. Render source identity may be exposed as non-secret branch/commit/service metadata for exact-deployment verification.

## Localization, theme and responsive Web

- English + LTR
- Arabic + RTL
- Light / Dark / System themes
- responsive desktop/tablet/mobile Web surfaces

Language and authenticated theme preferences are persisted by the existing account model; anonymous theme selection uses browser persistence.

## Account lifecycle limitation

Login/logout and privileged two-factor authentication are implemented. **The current repository does not implement a customer-facing automated password-reset flow or email-verification/activation-token flow.** These capabilities are not advertised or fabricated by the Production Launch Gate. The product owner must decide the intended account-provisioning/recovery policy before broad public account rollout.

## Integrations

Supported adapters/configuration include COD, Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images and Sentry. Adapter presence does **not** mean a provider is configured or production-ready. Secrets belong in protected configuration and database-backed encrypted `IntegrationConfig`, never source control.

COD is internal and requires no external provider credential. Production private uploaded media requires the configured S3 path.

## QA/demo safety

Deterministic QA data is created only by:

```bash
python manage.py seed_demo
```

and only when `FABINZI_DEMO_SEED_ENABLED=true` with protected QA credentials. Controlled QA Admin TOTP provisioning uses `python manage.py provision_demo_admin_otp` with a protected base32 secret. Neither operation is part of production startup.

## Deferred live validation

The Global Live E2E checkpoint was intentionally passed forward **source-side complete but not live-accepted** because the isolated QA environment and protected configuration were unavailable. Its complete unresolved register is [docs/DEFERRED_LIVE_E2E.md](docs/DEFERRED_LIVE_E2E.md). Those items must be resumed after Flutter; they are not converted to PASS by repository launch-readiness work.

## Testing

CI uses PostgreSQL + Redis and runs:

```bash
python manage.py makemigrations --check --dry-run
python manage.py reconcile_migration_state
python manage.py migrate --noinput
python manage.py check
python manage.py collectstatic --noinput
python manage.py check --deploy   # production settings
pytest -q
```

It preserves the existing Web, Artwork/Studio, Designer, Manufacturer and `/Maneg/` browser evidence and adds focused Production Launch Gate browser evidence.

## Render deployment

`render.yaml` defines the repository-side production topology: Django/Gunicorn web, paid PostgreSQL, Redis-compatible Key Value, Celery worker and Celery Beat. The production Blueprint tracks `main`; branch/PR checkpoints must not be treated as deployed production until the explicit release process occurs.

See [Deployment](docs/DEPLOYMENT.md) and [Backup & Recovery](docs/BACKUP_AND_RECOVERY.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Backup & Recovery](docs/BACKUP_AND_RECOVERY.md)
- [Demo & QA](docs/DEMO_QA.md)
- [Deferred Global Live E2E](docs/DEFERRED_LIVE_E2E.md)

## License

No open-source license has been granted for this repository. All rights are reserved by the project owner unless a separate license is explicitly published.
