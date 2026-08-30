# FABINZI Customer API v1 — Endpoint Inventory

**Base path:** `/api/v1/customer/`

**Backend baseline:** FABINZI WEB v1.0 (`APP_VERSION = 1.0.0`)

This inventory is the Customer-mobile boundary only. Existing legacy `/api/v1/` Designer, Manufacturer, finance, operations, onboarding, moderation, and payment-webhook routes remain outside the Flutter Customer contract.

## Authentication legend

- **Public** — no bearer token required; anonymous throttle applies.
- **JWT** — `Authorization: Bearer <access-token>` using the Customer mobile JWT contract.
- The existing browser/SSR application continues to use `SessionAuthentication` and CSRF and is not changed by this inventory.

## Frozen operations

| # | Method | Path | Auth | Contract purpose |
|---:|---|---|---|---|
| 1 | GET | `/bootstrap/` | Public | API/version/capability bootstrap |
| 2 | POST | `/auth/login/` | Public | Existing-account login |
| 3 | POST | `/auth/refresh/` | Public | Refresh-token rotation |
| 4 | POST | `/auth/logout/` | JWT | Revoke presented device refresh token |
| 5 | GET | `/me/` | JWT | Current Customer identity |
| 6 | PATCH | `/me/` | JWT | Language/theme preferences only |
| 7 | GET | `/stores/` | Public | Paginated published Storefront discovery |
| 8 | GET | `/stores/<store_slug>/` | Public | Published Storefront detail |
| 9 | GET | `/products/` | Public | Paginated Customer catalog |
| 10 | GET | `/stores/<store_slug>/products/<product_slug>/` | Public | Published product/variant/Studio eligibility detail |
| 11 | GET | `/artworks/` | Public | Paginated approved Artwork discovery |
| 12 | GET | `/artworks/<artwork_id>/` | Public | Approved Artwork detail |
| 13 | GET | `/studio-projects/` | JWT | Paginated Customer Studio projects |
| 14 | POST | `/studio-projects/` | JWT | Create Studio draft |
| 15 | GET | `/studio-projects/<project_id>/` | JWT | Reload persisted Studio state |
| 16 | PATCH | `/studio-projects/<project_id>/` | JWT | Edit Studio draft fields |
| 17 | POST | `/studio-projects/<project_id>/customization/` | JWT | Enable customization |
| 18 | POST | `/studio-projects/<project_id>/uploads/` | JWT | Private multipart image upload |
| 19 | POST | `/studio-projects/<project_id>/elements/` | JWT | Add text/image/Artwork element |
| 20 | PATCH | `/studio-projects/<project_id>/elements/<element_id>/` | JWT | Edit Studio element |
| 21 | DELETE | `/studio-projects/<project_id>/elements/<element_id>/` | JWT | Delete Studio element |
| 22 | GET | `/studio-projects/<project_id>/validation/` | JWT | Server-authoritative Studio validation |
| 23 | POST | `/studio-projects/<project_id>/ready/` | JWT | Mark valid Studio draft Ready |
| 24 | POST | `/studio-projects/<project_id>/checkout/` | JWT | Create/refresh Studio checkout |
| 25 | GET | `/media/<asset_id>/` | JWT | Customer-owned protected Studio media |
| 26 | GET | `/cart/` | JWT | Active Cart and authoritative totals |
| 27 | POST | `/cart/items/` | JWT | Add plain/Ready Designed/Ready Studio item |
| 28 | PATCH | `/cart/items/<item_id>/` | JWT | Update Cart quantity |
| 29 | DELETE | `/cart/items/<item_id>/` | JWT | Remove Cart item |
| 30 | POST | `/cart/checkout/` | JWT | Create/refresh Cart checkout |
| 31 | GET | `/checkouts/<checkout_id>/` | JWT | Review authoritative checkout |
| 32 | PATCH | `/checkouts/<checkout_id>/` | JWT | Update shipping fields |
| 33 | POST | `/checkouts/<checkout_id>/place/` | JWT | Place canonical parent Purchase; `Idempotency-Key` required |
| 34 | GET | `/payment-options/` | JWT | Only currently available/configuration-tested payment options |
| 35 | GET | `/purchases/` | JWT | Paginated canonical parent Purchases |
| 36 | GET | `/purchases/<purchase_reference>/` | JWT | Parent Purchase detail + Customer-safe item/fulfillment data |
| 37 | GET | `/notifications/` | JWT | Paginated Customer notifications |
| 38 | GET | `/notifications/preferences/` | JWT | Notification preferences |
| 39 | PATCH | `/notifications/preferences/` | JWT | Update notification preferences |
| 40 | POST | `/notifications/read-all/` | JWT | Mark all read |
| 41 | POST | `/notifications/<notification_id>/read/` | JWT | Mark one read |

Total frozen operations: **41**.

## Public discovery filters

- Stores: `q`
- Products: `q`, `store`, `customizable=true|false`
- Artwork: `q`, `method=print|embroidery`
- Paginated lists: `page`, `page_size` (default 20; maximum 50)

## Customer journey coverage

The inventory supports the existing WEB product capabilities required by the future native Customer app: authentication, account preferences, Storefront/catalog discovery, Variant selection, approved Artwork discovery, Ready Designed products, Visual Studio persistence, private Customer uploads, Cart, checkout, payment-option discovery, canonical parent Purchase creation, Customer-safe fulfillment/tracking, and notifications.

## Explicitly excluded from the frozen Customer contract

The following existing surfaces remain operational but are intentionally outside this contract:

- `/api/v1/payment-webhooks/<provider>/` — server-to-server payment callback only.
- Designer onboarding/workspace, Garment Design, private Artwork authoring/review, Designed Product publishing, Store management, RFQ sourcing and quote selection.
- Manufacturer listing/capabilities/portfolio management, RFQ invitations/quotes, production execution, QC, packing/shipping operations.
- Platform finance/payout/settlement APIs.
- Internal production/operations actions and assignment endpoints.
- IP moderation/internal review endpoints.
- `/Maneg/` Control Center and Django Admin internals.
- `/api/v1/manufacturers/public/` legacy public Manufacturer discovery; not required by the frozen Customer mobile journey.
- `/api/v1/health/` legacy API health endpoint; runtime health is not a Customer product contract and Customer bootstrap is the mobile capability source.

No excluded family may be inferred as Flutter-supported merely because it exists elsewhere under `/api/v1/`.
