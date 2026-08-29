# FABINZI

FABINZI is a greenfield fashion platform connecting Designers, Manufacturers and Customers through controlled design, sourcing, storefront, customization, checkout and production workflows.

## Current implementation
Stages 0–6 are implemented and CI-gated:
- Stage 0 — Engineering Foundation
- Stage 1 — Business Identity & Onboarding
- Stage 2 — Garment Design
- Stage 3 — Artwork & Designed Products + IP Governance
- Stage 4 — Manufacturer Marketplace
- Stage 5 — Store & Studio
- Stage 6 — Checkout & Payments

Stage 6 adds customer checkout, order snapshots, COD, optional Paymob/Stripe integrations, signed payment webhooks and stock reservation at confirmation. Manufacturing/fulfillment remains Stage 7.

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
- `/artwork/` Artwork marketplace
- `/manufacturers/` Manufacturer marketplace
- `/designer/` Designer portal
- `/manufacturer/` Manufacturer portal
- `/Maneg/` privileged OTP-protected administration

## Integrations
COD is the default practical payment method. Paymob and Stripe remain disabled until explicitly configured and successfully tested in `/Maneg/`. Mailgun, Twilio, Amazon S3, Cloudflare Images and Sentry are also optional and disabled until configured, except the original seeded COD configuration.

No production secrets belong in source control.
