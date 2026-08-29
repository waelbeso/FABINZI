# FABINZI

FABINZI is a greenfield fashion platform connecting Designers, Manufacturers and Customers through controlled design, sourcing, storefront, customization, checkout, manufacturing, fulfillment and finance workflows.

## Current implementation
Stages 0–9 are implemented and CI-gated:
- Stage 0 — Engineering Foundation
- Stage 1 — Business Identity & Onboarding
- Stage 2 — Garment Design
- Stage 3 — Artwork & Designed Products + IP Governance
- Stage 4 — Manufacturer Marketplace
- Stage 5 — Store & Studio
- Stage 6 — Checkout & Payments
- Stage 7 — Manufacturing & Fulfillment
- Stage 8 — Finance
- Stage 9 — Communications & Hardening

Stage 9 adds the notification center, opt-in Mailgun/Twilio delivery queue, communication preferences, API throttling, security headers and readiness checks. The primary responsive web platform is now complete; Flutter is the next major phase.

## Stack
Python / Django / Django REST Framework / PostgreSQL / Celery / Redis.

## Development
Copy `.env.example` to `.env`, configure PostgreSQL and Redis, install `requirements.txt`, then run migrations and the Django server.

```bash
python manage.py migrate
python manage.py runserver
```

## Primary surfaces
- `/` public home
- `/store/` public Store marketplace
- `/studio/` customer Studio
- `/orders/` customer orders
- `/notifications/` user notification center
- `/designer/fulfillment/` Designer fulfillment operations
- `/manufacturer/production/` Manufacturer production operations
- `/designer/finance/` Designer finance
- `/manufacturer/finance/` Manufacturer finance
- `/artwork/` Artwork marketplace
- `/manufacturers/` Manufacturer marketplace
- `/designer/` Designer portal
- `/manufacturer/` Manufacturer portal
- `/healthz/` liveness
- `/readyz/` database readiness
- `/Maneg/` privileged OTP-protected administration

## Integrations
COD is the default practical payment method. Paymob and Stripe remain disabled until explicitly configured and successfully tested in `/Maneg/`. Mailgun and Twilio are opt-in communication providers and also remain disabled until configured and successfully tested. Amazon S3, Cloudflare Images and Sentry remain optional.

No production secrets belong in source control. `INTEGRATION_ENCRYPTION_KEY` is mandatory outside DEBUG mode.
