# FABINZI WEB v1.0 — Preliminary API v1 Inventory

**Status: read-only inventory for the NEXT checkpoint. This is not the Customer API contract freeze.**

The API is mounted at `/api/v1/`, uses DRF `NamespaceVersioning`, defaults to `SessionAuthentication` + `IsAuthenticated`, and applies anonymous/user throttles. There is no repository-wide default pagination class. These facts are current implementation, not future Flutter decisions.

## Public read endpoints currently present

- `GET /api/v1/health/`
- `GET /api/v1/artworks/public/`
- `GET /api/v1/artworks/public/<pk>/`
- `GET /api/v1/manufacturers/public/`
- `GET /api/v1/manufacturers/public/<pk>/`
- `GET /api/v1/stores/public/`
- `GET /api/v1/stores/<slug>/`
- `GET /api/v1/stores/<store_slug>/products/<product_slug>/`

Artwork public list currently accepts `q` and `method` filtering. No pagination guarantee is frozen here.

## Customer-authenticated API surface currently relevant to a future mobile contract

### Notifications

- `GET /notifications/`
- `GET|PATCH /notifications/preferences/`
- `POST /notifications/read-all/`
- `POST /notifications/<notification_id>/read/`

Current list behavior returns up to 100 in-app notifications directly; this is an implementation fact to review during contract freeze, not a frozen pagination contract.

### Studio

- `GET|POST /studio-projects/`
- `GET|PATCH /studio-projects/<project_id>/`
- `POST /studio-projects/<project_id>/customization/`
- `POST /studio-projects/<project_id>/uploads/` — multipart/form-data private image upload
- `POST /studio-projects/<project_id>/elements/`
- `PATCH|DELETE /studio-projects/<project_id>/elements/<element_id>/`
- `GET /studio-projects/<project_id>/validation/`
- `POST /studio-projects/<project_id>/ready/`
- `POST /studio-projects/<project_id>/checkout/`

### Cart / checkout / Commerce

- `GET /cart/`
- `POST /cart/items/`
- `PATCH|DELETE /cart/items/<item_id>/`
- `POST /cart/checkout/`
- `GET|PATCH /checkouts/<checkout_id>/`
- `POST /checkouts/<checkout_id>/place/`
- `GET /payment-options/`
- `GET /purchases/`
- `GET /purchases/<purchase_id>/`
- `GET /orders/`
- `GET /orders/<order_id>/`

The accepted parent/child persistence model remains the source of truth. Online payment response fields may contain provider redirect/client-secret data when that provider is actually enabled; provider readiness is not inferred.

## Other v1 families already present

The same `/api/v1/` namespace also includes organization onboarding/members, Garment Designs/versions/review, Artwork authoring/IP, Designed Products, Manufacturer listings/capabilities, RFQs/invitations/quotes/selection, Designer storefront management, production operations/QC/fulfillment and organization finance/settlements. These are **not** automatically part of the future Customer Flutter contract merely because they exist in v1.

Server-to-server payment callbacks are exposed under `/payment-webhooks/<provider>/` with signature verification; they are not Customer-app endpoints.

## Contract-freeze questions intentionally deferred

The next checkpoint must decide and test, rather than assume:

- Customer mobile authentication/session/token strategy and CSRF implications.
- signup/provisioning/recovery policy, especially because password reset and email verification are currently absent.
- exact request/response schemas and nullable fields.
- error envelope normalization.
- pagination/filter/search contracts.
- locale/content-selection rules.
- currency/decimal serialization rules.
- upload/media URL lifetime and authentication behavior.
- idempotency/retry rules exposed to mobile clients.
- compatibility/deprecation policy.

No API redesign or contract freeze is performed by WEB v1.0 release preparation.
