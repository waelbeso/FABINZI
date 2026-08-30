# FABINZI Customer API v1 — Contract Freeze

**Status:** IN PROGRESS — NOT FROZEN

This document is the working human contract for the `FABINZI Customer API v1` checkpoint. It is intentionally incomplete until the actual repository implementation has been audited, implemented where required, tested, and formally accepted.

## Baseline

- Backend/Web baseline: `FABINZI WEB v1.0`
- `APP_VERSION`: `1.0.0`
- Integration SHA at checkpoint entry: `461c9079b5e53e51e5af4f6d564b891fe7e20b47`
- Predecessor RC3: `ce856773a58b47826b23d60f011255beda78db13`
- Predecessor CI: `#353` / Run `33290231430` — 249 passed / 0 failed / 1 existing non-blocking warning

## Scope boundary

Only the public Customer discovery API and Customer-authenticated mobile API may become the frozen Flutter Customer contract in this checkpoint.

Designer-only, Manufacturer-only, `/Maneg/`, internal/operations, admin, and server-to-server endpoint families are excluded unless a shared read-only Customer discovery resource is explicitly verified as required.

## Architecture locks

The checkpoint must preserve the accepted Commerce architecture:

`Cart → Checkout → one Parent CustomerPurchase`

Each CartItem maps to one CustomerOrder, one OrderItem, one ProductionJob, and one canonical FulfillmentRecord. Manufacturer remains a production partner, not a catalog seller. No second shipment or fulfillment architecture may be introduced.

## Current status

No mobile authentication, pagination, error, idempotency, OpenAPI, serializer, or endpoint contract is declared frozen by this initial file. All such sections will be filled only from verified repository behavior and accepted additive implementation.

`docs/DEFERRED_LIVE_E2E.md` remains explicitly UNRESOLVED and is not part of this checkpoint's live validation.
