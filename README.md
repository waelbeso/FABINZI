# FABINZI

FABINZI is a digital fashion platform that connects **Customers, Designers, Manufacturing Partners, and FABINZI Platform Administration** in one controlled design-to-production workflow.

**Designer creates. Manufacturer produces. Customer buys. FABINZI orchestrates.**

The current Web product covers public discovery, Designer Artwork, ready-designed products, optional Customer Studio customization, manufacturer sourcing, Commerce, production, QC, fulfillment/tracking, finance, notifications and the OTP-protected `/Maneg/` Control Center.

## WEB v1.0 release identity

The authoritative semantic application version is **1.0.0** in `config/release.py`. `release-manifest.json` and `RELEASE_MANIFEST.md` freeze the WEB v1.0 release metadata. The exact Release Candidate identity is the Git commit containing those files and is recorded by CI/PR acceptance metadata rather than embedded inside the commit itself.

Release runtime: **Python 3.12.14**. `requirements.txt` remains the supported dependency envelope; `constraints-release.txt` freezes the exact dependency resolution used to reproduce WEB v1.0.

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
| `/healthz/`, `/readyz/` | Safe liveness/version/source identity and database readiness |

Public trust information is available at `/about/`, `/terms/`, `/privacy/`, `/returns/`, `/shipping/`, and `/support/`. These repository pages are conservative baseline launch copy and are **not represented as lawyer-reviewed**. Jurisdiction-specific legal approval and public support coordinates remain operator responsibilities before a public production launch.

## Technology

- Python **3.12.14** for the WEB v1.0 release contract
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

Release reproduction requires Python 3.12.14, PostgreSQL, and Redis 7+ or a compatible Redis-protocol service.

```bash
git clone https://github.com/waelbeso/FABINZI.git
cd FABINZI
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -c constraints-release.txt
python -m pip check
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

Production startup rejects the development secret fallback, non-HTTPS public origin and local private-media mode. See [WEB v1.0 Configuration Contract](docs/WEB_V1_CONFIGURATION_CONTRACT.md).

## Security

The Web product includes tenant-aware authorization, `/Maneg/` OTP/MFA, CSRF/session protection, secure production cookies, SSL redirect/HSTS, frame denial, content-type/referrer/cross-origin security headers, private-surface `noindex`, encrypted integration secrets, private-media authorization, payment callback/webhook validation, API throttling, payout masking and audit/finance controls implemented by the accepted domain architecture.

`/healthz/` exposes only semantic application version and optional non-secret Render branch/commit/service source identity. It does not expose credentials, DSNs, provider secrets or environment dumps. `/readyz/` remains database readiness only.

## Localization, theme and responsive Web

- English + LTR
- Arabic + RTL
- Light / Dark / System themes
- responsive desktop/tablet/mobile Web surfaces

Language and authenticated theme preferences are persisted by the existing account model; anonymous theme selection uses browser persistence.

## Account lifecycle limitation

Login/logout and privileged two-factor authentication are implemented. **The current repository does not implement a customer-facing automated password-reset flow or email-verification/activation-token flow.** These capabilities are not advertised or fabricated. The product owner must decide the intended account-provisioning/recovery policy before broad public account rollout.

## Integrations

Supported adapters/configuration include COD, Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images and Sentry. Adapter presence does **not** mean a provider is configured or production-ready. Secrets belong in protected configuration and database-backed encrypted `IntegrationConfig`, never source control.

COD is internal and requires no external provider credential. Production private uploaded media requires the configured S3 path.

## QA/demo safety

Deterministic QA data is created only by `python manage.py seed_demo` when `FABINZI_DEMO_SEED_ENABLED=true` with protected QA credentials. Controlled QA Admin TOTP provisioning uses `python manage.py provision_demo_admin_otp` with a protected base32 secret. Neither operation is part of production startup.

## Deferred live validation

The Global Live E2E checkpoint remains explicitly **UNRESOLVED** for its deferred external items. Its durable register is [docs/DEFERRED_LIVE_E2E.md](docs/DEFERRED_LIVE_E2E.md). Those items return after Flutter; WEB v1.0 release preparation does not convert them to PASS.

## Testing

CI checks out the exact PR head SHA, uses Python 3.12.14 plus `constraints-release.txt`, then runs dependency validation, migration/static freeze checks, migration drift/reconciliation/fresh migrate, Django checks, `collectstatic`, production `check --deploy`, the full pytest/browser regressions and release-contract tests. Successful runs also upload a `web-v1-release-contract` evidence artifact.

## Render deployment

`render.yaml` defines the repository-side production topology: Django/Gunicorn web, paid PostgreSQL, Redis-compatible Key Value, Celery worker and Celery Beat. The production Blueprint tracks `main`; branch/PR checkpoints must not be treated as deployed production until an explicit release process occurs.

See [Deployment](docs/DEPLOYMENT.md), [WEB v1.0 Deployment & Rollback](docs/WEB_V1_DEPLOYMENT_ROLLBACK.md) and [Backup & Recovery](docs/BACKUP_AND_RECOVERY.md).

## Release documentation

- [Release Manifest](RELEASE_MANIFEST.md)
- [Machine-readable Release Manifest](release-manifest.json)
- [Changelog](CHANGELOG.md)
- [Release Preparation](docs/WEB_V1_RELEASE_PREPARATION.md)
- [Accepted Limitations](docs/WEB_V1_LIMITATIONS.md)
- [Canonical Route Inventory](docs/WEB_V1_ROUTE_INVENTORY.md)
- [Capability Inventory](docs/WEB_V1_CAPABILITY_INVENTORY.md)
- [Migration Baseline](docs/WEB_V1_MIGRATION_BASELINE.md)
- [Production Configuration Contract](docs/WEB_V1_CONFIGURATION_CONTRACT.md)
- [Deployment & Rollback Contract](docs/WEB_V1_DEPLOYMENT_ROLLBACK.md)
- [Build Reproducibility](docs/WEB_V1_BUILD_REPRODUCIBILITY.md)
- [Preliminary API v1 Inventory](docs/WEB_V1_API_V1_INVENTORY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Backup & Recovery](docs/BACKUP_AND_RECOVERY.md)
- [Demo & QA](docs/DEMO_QA.md)
- [Deferred Global Live E2E](docs/DEFERRED_LIVE_E2E.md)

## License

No open-source license has been granted for this repository. All rights are reserved by the project owner unless a separate license is explicitly published.
