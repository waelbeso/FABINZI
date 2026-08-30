# FABINZI Web Architecture

WEB v1.0 semantic application version is defined only in `config/release.py`; release metadata/inventories are frozen by `release-manifest.json` and the `WEB_V1_*` release documents. This versioning layer does not alter the accepted domain architecture below.

## Runtime shape

FABINZI is a Django application with server-rendered responsive web surfaces and a versioned Django REST Framework boundary at `/api/v1/`. PostgreSQL is the transactional system of record. Redis-compatible transport supports Celery worker/Beat. Gunicorn serves Django in production and WhiteNoise serves collected static assets.

## Actors

1. **Customer** — browses public catalog/artwork, optionally customizes eligible products, checks out, and views purchase/fulfillment state.
2. **Designer organization** — manages creative/design/product/storefront work and manufacturing sourcing.
3. **Manufacturer organization** — production partner that publishes capabilities, responds to RFQs/quotes, executes assigned production/QC/packing and records shipment/tracking through canonical fulfillment.
4. **FABINZI Platform Administration** — OTP-protected `/Maneg/` operational and audit control surface.

A Manufacturer is not a catalog seller. Printing/embroidery are Manufacturer capabilities. Shipping is fulfillment. Customer Studio customization is optional.

## Domain boundaries

- `apps.accounts` — account preferences and authentication identity.
- `apps.organizations` — Designer/Manufacturer organizations, memberships, onboarding, verification and portal views.
- `apps.design` — Garment Design/version/technical definitions and decoration zones.
- `apps.artwork` — Artwork/version/IP workflow, Designed Products and placements.
- `apps.manufacturer_marketplace` — Manufacturer public listings/capabilities, RFQ, invitation, quote and selection.
- `apps.storefront` — storefront catalog, variants, imagery and Studio projects/customization.
- `apps.checkout` — Cart, checkout, parent/child Commerce, payment attempts and webhook events.
- `apps.operations` — ProductionJobs, milestones, QC and canonical FulfillmentRecord/tracking.
- `apps.finance` — finance snapshots, ledger, earnings, payout profiles, settlement requests and adjustments.
- `apps.notifications` — canonical in-app notifications plus optional external delivery queue/tasks.
- `apps.integrations` — optional provider configuration with encrypted secrets and controlled connection tests.
- `apps.media` — provider-neutral media metadata and authorized private-media delivery.
- `apps.audit` — append-oriented audit events.
- `apps.platform_ops` — public site/SEO/trust/error surfaces, health/readiness, maintenance/announcements and security middleware.

## Commerce architecture — locked

The accepted customer model is:

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

The parent purchase is the customer-facing commercial aggregate. Child orders carry operational line-level state. Checkout does not require a Manufacturer assignment.

## Manufacturer / fulfillment architecture — locked

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

There is no second shipment model or parallel fulfillment architecture.

## Tenancy and authorization

Organization-owned data is scoped to Designer/Manufacturer organizations and active memberships/roles. Customer-owned Studio, Cart, purchase/order and notification records are scoped to the authenticated customer. Private-media endpoints perform application authorization before exposing provider access. `/Maneg/` requires privileged staff identity plus OTP verification.

## Public/private web boundary

Public/indexable surfaces include the homepage, published storefront/product/artwork/manufacturer content and launch trust pages. Customer account, Cart/Checkout, Studio, Designer, Manufacturer, `/Maneg/`, API, health/readiness and private-media routes are excluded from public indexing through robots policy and application `X-Robots-Tag`/metadata.

Public metadata uses `FABINZI_PUBLIC_BASE_URL` for canonical URLs, sitemap, hreflang and social preview URLs.

## Static and private media

Collected static files use WhiteNoise compressed manifest storage in non-DEBUG deployments. Production private uploaded media is fail-closed to the S3 integration path; local private-media storage is allowed only in development/test. Media provider state is not inferred from the presence of adapters.

## Async and notifications

Celery uses `REDIS_URL` for broker and result backend. Worker settings use late acknowledgement, reject-on-worker-lost, retry-on-startup and task time limits. Beat schedules pending external notification dispatch every 60 seconds. In-app notifications remain canonical even when Mailgun/Twilio are disabled.

## Integrations

The integration model supports COD, Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images and Sentry. Secrets are encrypted using `INTEGRATION_ENCRYPTION_KEY`. Adapter existence is not evidence that a provider is configured or healthy.

## Deployment components

The production Render Blueprint defines:

- `fabinzi-web` — Docker/Gunicorn web service.
- `fabinzi-db` — paid PostgreSQL 17 database.
- `fabinzi-redis` — Redis-compatible Render Key Value transport.
- `fabinzi-worker` — Celery worker.
- `fabinzi-beat` — Celery Beat scheduler.

The isolated QA Blueprint is separate and remains part of the deferred live-validation return documented in `DEFERRED_LIVE_E2E.md`.

## API boundary

The existing `/api/v1/` API shares the same business/service layer and persistence model as the SSR Web product. WEB v1.0 release preparation records a **preliminary read-only inventory only** in `WEB_V1_API_V1_INVENTORY.md`; it does not freeze the future Customer API contract, choose Flutter authentication semantics, or start Flutter work.
