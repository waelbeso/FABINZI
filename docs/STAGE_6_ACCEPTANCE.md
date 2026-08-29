# Stage 6 — Checkout & Payments — COMPLETE

Stage 6 converts a READY Studio Project into a commercial order while preserving Stage 5 product/customization boundaries.

## Delivered
- Customer-owned checkout session with immutable finalization.
- Server-side price recalculation and order snapshots.
- Delivery-contact/address capture.
- Customer Order + immutable Order Item snapshot.
- COD as the default practical payment path.
- Optional Paymob and Stripe paths gated by enabled IntegrationConfig and successful Test Connection.
- Provider payment-attempt records and idempotency keys.
- Signed webhook endpoints with replay/idempotency protection.
- Payment success/failure state transitions.
- Stock-mode reservation at confirmation; no reservation before order/payment confirmation.
- In-app customer confirmation notification and audit events.
- Customer order history/detail web surfaces.
- DRF checkout, payment-option, order and webhook APIs.
- OTP-protected /Maneg/ administration.
- Automated Stage 6 tests.

## Explicit boundary
Stage 6 does not create manufacturing jobs, production milestones, shipment records, QC records or fulfillment workflow. Those belong to Stage 7.

## Acceptance gate
CI must pass migration drift check, migrate, Django system check and full pytest suite.
