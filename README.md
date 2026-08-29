# FABINZI

FABINZI is a greenfield fashion platform connecting Designers, Manufacturers and Customers through controlled design, sourcing, storefront, customization, checkout, manufacturing, fulfillment and finance workflows.

## Current implementation
Stages 0–8 are implemented and CI-gated:
- Stage 0 — Engineering Foundation
- Stage 1 — Business Identity & Onboarding
- Stage 2 — Garment Design
- Stage 3 — Artwork & Designed Products + IP Governance
- Stage 4 — Manufacturer Marketplace
- Stage 5 — Store & Studio
- Stage 6 — Checkout & Payments
- Stage 7 — Manufacturing & Fulfillment
- Stage 8 — Finance

Stage 8 adds delivery-triggered financial recognition, platform commission policy, immutable organization/platform ledgers, available/pending/reserved balances, verified payout profiles, settlement requests and controlled external-settlement recording.

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
- `/finance/` organization finance dashboard
- `/designer/fulfillment/` Designer fulfillment operations
- `/designer/finance/` Designer finance
- `/manufacturer/production/` Manufacturer production operations
- `/manufacturer/finance/` Manufacturer finance
- `/artwork/` Artwork marketplace
- `/manufacturers/` Manufacturer marketplace
- `/designer/` Designer portal
- `/manufacturer/` Manufacturer portal
- `/Maneg/` privileged OTP-protected administration

## Integrations
COD is the default practical payment method. Paymob and Stripe remain disabled until explicitly configured and successfully tested in `/Maneg/`. Mailgun, Twilio, Amazon S3, Cloudflare Images and Sentry are also optional and disabled until configured, except the original seeded COD configuration.

Finance payout profiles intentionally store only masked/non-sensitive destination hints. Stage 8 records externally completed settlements but does not store banking credentials or execute bank transfers.

No production secrets belong in source control.