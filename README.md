# FABINZI

FABINZI is a greenfield fashion design, manufacturing, marketplace, Store and Studio platform built with Django/DRF.

## Current delivery status
- Stage 0 — Engineering Foundation: COMPLETE
- Stage 1 — Business Identity & Onboarding: COMPLETE
- Stage 2 — Garment Design Domain: COMPLETE
- Stage 3 — Artwork & Designed Products + IP Governance: COMPLETE
- Stage 4 — Manufacturer Marketplace: COMPLETE
- Stage 5 — Store & Studio: COMPLETE

The domain boundaries remain explicit: Garment Design, Artwork, Designed Product and Customer Customization are separate concepts. Manufacturer is the manufacturing marketplace actor; printing and embroidery are capabilities, not actors.

## Major web surfaces
- `/` public home
- `/app/` signed-in application home
- `/store/` public Designer stores and products
- `/studio/` authenticated customer Studio projects
- `/artwork/` approved Artwork marketplace
- `/manufacturers/` public Manufacturer marketplace
- `/designer/` Designer business portal
- `/designer/store/` Designer Store management
- `/manufacturer/` Manufacturer business portal
- `/manufacturer/marketplace/` Manufacturer marketplace workspace
- `/Maneg/` privileged FABINZI Control Center protected by OTP

## Infrastructure
Python/Django/DRF/PostgreSQL/Celery/Redis. Optional external integrations remain disabled until configured and tested. COD, Paymob/Stripe checkout and all actual order/payment execution are intentionally deferred to Stage 6. Manufacturing fulfillment is Stage 7 and finance/settlement is Stage 8.

See `docs/STAGE_5_ACCEPTANCE.md` for the current acceptance boundary.
