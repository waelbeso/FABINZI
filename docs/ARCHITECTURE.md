# FABINZI Architecture

## Overview

FABINZI is a Django monolith with a versioned REST API, PostgreSQL persistence, Redis-compatible Celery transport, and responsive server-rendered web surfaces. The architecture intentionally keeps business domains separated while sharing a single authenticated account, organization, audit, notification, and integration foundation.

## Core domains

- `apps.accounts` — user account, language, and theme preference.
- `apps.organizations` — Designer/Manufacturer organizations, onboarding, memberships, verification, and profiles.
- `apps.design` — Garment Designs, versions, technical information, size charts, decoration zones, assets, and technical review.
- `apps.artwork` — Artwork, versions, IP declarations, reviews, Designed Products, placements, and IP cases.
- `apps.manufacturer_marketplace` — public Manufacturer listings, capabilities, RFQs, invitations, quotes, and selection.
- `apps.storefront` — Designer storefront, products, variants, product imagery, Studio projects, and Customer Customization.
- `apps.checkout` — checkout sessions, immutable order snapshots, COD/online payment attempts, and payment webhooks.
- `apps.operations` — production assignment, milestones, QC, fulfillment records, and shipment tracking.
- `apps.finance` — order finance snapshots, ledger, payout profiles, settlement requests, and adjustments.
- `apps.notifications` — in-app notifications, preferences, delivery queue, and Celery delivery work.
- `apps.integrations` — optional external provider configuration with encrypted secrets and Control Center test actions.
- `apps.media` — provider-neutral media metadata references.
- `apps.audit` — append-only audit events.
- `apps.platform_ops` — public home, health/readiness, announcements, maintenance mode, security middleware, and public URL helpers.

## Business identity

The four operating roles are:

1. Customer
2. Designer organization
3. Manufacturer organization
4. FABINZI Platform Administration

Printing and embroidery are Manufacturer capabilities. Shipping is fulfillment. Customer customization is optional and remains distinct from Designer Artwork and Ready Designed Products.

## Request surfaces

Django `config/urls.py` exposes the web surfaces and mounts the versioned API at `/api/v1/`. The administrative Control Center is mounted at `/Maneg/` using an OTP-required AdminSite.

## Data and tenancy

PostgreSQL is the system of record. Organization-owned records reference a Designer or Manufacturer `Organization`, and service-layer access checks use active membership plus role restrictions. Customer-owned Studio, checkout, order, and notification records remain scoped to the authenticated user.

## Background processing

Celery uses `REDIS_URL` for broker and result backend. The worker executes asynchronous communication deliveries. Celery Beat schedules pending notification dispatch once per minute. Core in-app records do not depend on an external email/SMS provider being enabled.

## Static and media

Static assets are collected to `STATIC_ROOT` and served by WhiteNoise in production. Arbitrary production media is represented through `MediaAsset` and optional provider integrations. Amazon S3 is the production file-storage path when enabled; Cloudflare Images is available for image-specific integration. Demo visual assets are committed SVG static files so Render's ephemeral local filesystem is not relied upon.

## External integrations

The database-backed integration model supports COD, Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images, and Sentry. Providers remain disabled until configured. Integration secrets are encrypted using `INTEGRATION_ENCRYPTION_KEY` and are not stored in source control.

## Public URL policy

`FABINZI_PUBLIC_BASE_URL` is the authoritative public origin for server-generated absolute URLs. Same-origin browser traffic should use relative paths. This allows a future domain migration without rewriting application code and provides a clean base for future Flutter client configuration.

## Deployment topology

The Render Blueprint defines:

- `fabinzi-web` — Django/Gunicorn web process.
- `fabinzi-db` — persistent PostgreSQL.
- `fabinzi-redis` — Render Key Value transport for Celery.
- `fabinzi-worker` — Celery worker.
- `fabinzi-beat` — Celery Beat scheduler.

The Flutter mobile applications are intentionally outside the current phase and will consume the accepted Django REST API later.
