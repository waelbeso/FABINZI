# FABINZI Customer API v1 — Contract Freeze

**Contract:** FABINZI Customer API v1  
**Base path:** `/api/v1/customer/`  
**Backend baseline:** FABINZI WEB v1.0  
**Backend application version:** `1.0.0`  
**Checkpoint integration baseline:** `461c9079b5e53e51e5af4f6d564b891fe7e20b47`  
**Predecessor WEB v1.0 RC3:** `ce856773a58b47826b23d60f011255beda78db13`

This document is the authoritative human description of the first Customer-mobile API contract. The exact frozen candidate SHA is recorded only after all contract-affecting source, documentation, schema, fixtures, drift protection, tests, and CI artifact generation are complete. Until formal checkpoint acceptance, the Draft PR remains the review surface and is not merged.

## 1. Scope and architecture boundary

The frozen contract is intentionally narrower than the historical mixed `/api/v1/` namespace. It contains only public Customer discovery and Customer-authenticated native-client operations under `/api/v1/customer/`.

It preserves the accepted backend architecture:

`Cart → Checkout → one Parent CustomerPurchase`

Each CartItem maps to:

`one CustomerOrder → one OrderItem → one ProductionJob → one canonical FulfillmentRecord`

The Customer API presents the parent Purchase first. Operational child records are exposed only as Customer-friendly nested item/fulfillment state where useful. Flutter is not required to understand Manufacturer assignment, sourcing RFQs, QC orchestration, finance allocation, or internal production control.

Manufacturer remains a production partner, not a catalog seller. No second shipment or fulfillment architecture exists in this contract.

## 2. Explicit exclusions

The Customer contract does **not** include:

- Designer onboarding/workspace or Garment Design authoring/review.
- Designer private Artwork authoring, rights evidence, moderation, Store management, RFQs or quote selection.
- Manufacturer private listing/capability management, RFQ invitations/quotes, production execution, QC, packing or shipment mutation.
- Finance, payout or settlement APIs.
- Internal Production/Operations assignment/milestone/QC mutation APIs.
- `/Maneg/` or Django Admin internals.
- Internal audit logs, moderation notes, commissions, unit manufacturing cost, capacity data, payout information or private technical packages.
- `/api/v1/payment-webhooks/<provider>/`; payment webhooks are server-to-server and remain outside Flutter.
- Legacy public Manufacturer discovery, which is not required by the Customer mobile journey.

Existing excluded APIs continue to operate for their accepted Web/backend use cases; excluding them from this contract is not a removal.

## 3. Authentication

Native Customer routes use `Authorization: Bearer <access-token>` and JWT authentication only. The SSR Web application remains unchanged on Django sessions, `SessionAuthentication`, CSRF middleware and secure cookies.

### Login

`POST /api/v1/customer/auth/login/`

Request:

```json
{"username":"customer.example","password":"<password>"}
```

Successful response returns:

- `token_type = "Bearer"`
- access JWT
- refresh JWT
- `access_expires_in = 900`
- `refresh_expires_in = 2592000`

Invalid credentials and inactive accounts both return a generic `401 invalid_credentials`; the endpoint does not disclose whether the username exists or whether the account is inactive.

### Token policy

- Access token lifetime: **15 minutes / 900 seconds**.
- Refresh token lifetime: **30 days / 2,592,000 seconds**.
- Refresh tokens rotate on successful refresh.
- The previous refresh token is blacklisted after rotation.
- Reuse of a rotated/revoked refresh token fails.
- Refresh checks the current account is still active.
- Invalid/expired access tokens return a standardized 401 Customer error.
- Invalid/expired/blacklisted refresh tokens return `401 invalid_refresh_token`.

### Logout and multiple devices

`POST /api/v1/customer/auth/logout/` requires a valid access token and the device's refresh token in the JSON body. It blacklists that refresh token. The presented access token is not a server session and naturally expires at its short lifetime.

Different devices may hold independent refresh tokens. Logging out one device does not revoke other device refresh tokens.

### HTTPS and browser security

Production already fails closed unless the public base URL is HTTPS. Credentials/tokens are never placed in URLs. Native JWT endpoints are not forced through browser CSRF semantics. The SSR Web CSRF configuration is **not** disabled or weakened. No permissive CORS policy is added for the native application.

## 4. Registration and recovery policy

The current WEB/backend baseline does not implement a controlled Customer self-signup lifecycle, automated Customer password reset, Customer email verification/account activation, or social login. Therefore the frozen bootstrap truthfully reports:

- `signup: false`
- `password_reset: false`
- `email_verification: false`
- `account_activation: false`
- `social_login: false`

The future Flutter app must not present those capabilities as available until the backend contract is deliberately extended in a future compatible or versioned change.

## 5. Current Customer identity

`GET /api/v1/customer/me/`

Returns only mobile-relevant fields:

- internal Customer `id` (opaque application identifier; do not derive business meaning)
- username
- display/first/last name
- email
- language preference
- theme preference
- `account_state = active`

`PATCH /me/` accepts only `language` (`en|ar`) and `theme` (`system|light|dark`). Identity/privilege/staff/password fields are not writable through this endpoint.

## 6. Localization

The native contract uses `Accept-Language`.

- Values beginning with `ar` select Arabic where an Arabic product/message label exists.
- Otherwise English is returned.
- User-entered proper names are not automatically translated.
- Machine status/code values remain stable and language-neutral.
- Human labels/messages may be localized.

The API does not require the native client to parse English text to understand status or navigation.

## 7. Money

All Customer monetary values use one explicit object:

```json
{"amount":"500.00","currency":"EGP"}
```

Rules:

- `amount` is a fixed two-decimal **string**, never a JSON float.
- `currency` is an uppercase three-letter code, or `null` only for an empty Cart before a currency exists.
- The server is the pricing authority. Flutter-calculated values are display estimates only and are never accepted as checkout authority.

## 8. Datetimes

Django/DRF serializes timestamps as ISO-8601 timezone-aware strings. A field is `null` only when the resource state has no corresponding timestamp yet, such as `placed_at`, `confirmed_at`, `read_at`, `ready_at`, `shipped_at` or `delivered_at`.

The client must not infer state only from a timestamp; use the corresponding machine status.

## 9. Identifiers

Identifiers are opaque.

- Public Storefront/Product writes use stable slugs plus Variant SKU where available.
- Parent CustomerPurchase public reference is its UUID `reference` and is the canonical purchase navigation identifier.
- Customer-friendly nested child items may expose the child order UUID as `reference`, but Flutter should navigate/order-history from the **parent Purchase reference**.
- Studio project, element, Cart item, checkout, notification and private media identifiers are scoped opaque integers. They must not be guessed or treated as authorization; every private lookup is server-scoped to the authenticated Customer.

## 10. Pagination

Intentional paginated lists use DRF page-number pagination:

```json
{
  "count": 25,
  "next": "https://…?page=2",
  "previous": null,
  "results": []
}
```

- default page size: **20**
- `page_size` may request a smaller/larger page up to **50**
- maximum: **50**
- invalid page input uses the Customer error contract.

Paginated families: Stores, Products, Artwork, Studio projects, Purchases and Notifications.

## 11. Filtering/search

Frozen discovery filters:

- Storefronts: `q`
- Products: `q`, `store=<slug>`, `customizable=true|false`
- Artwork: `q`, `method=print|embroidery`

Unknown future filters must not be assumed to exist. Invalid values on frozen filters return validation errors rather than silently changing meaning.

## 12. Error envelope

Customer JSON API errors use:

```json
{
  "error": {
    "code": "not_found",
    "message": "The requested resource was not found.",
    "fields": {},
    "request_id": "…"
  }
}
```

The same request ID is exposed in `X-Request-ID` where the Customer helper builds the response.

Frozen machine codes include:

- `authentication_required`
- `invalid_credentials`
- `token_expired`
- `invalid_token`
- `invalid_refresh_token`
- `permission_denied`
- `not_found`
- `validation_error`
- `conflict`
- `rate_limited`
- `invalid_state`
- `payment_error`
- `upload_error`
- `service_unavailable`
- `unsupported_media_type`

Semantics:

- `400` invalid request/field data.
- `401` authentication/token failure.
- `403` authenticated but forbidden action where existence hiding is not required.
- `404 not_found` for missing Customer-visible resources **and cross-Customer private resource lookups**. This intentionally hides whether another Customer owns a guessed ID.
- `409` state/idempotency conflict.
- `413` upload exceeds the frozen limit.
- `415` wrong request content type for multipart upload.
- `429 rate_limited` throttle response.
- `503` required storage/payment initiation service unavailable.

Validation errors are not globally converted to 404. Only actual 404 responses under `/api/v1/customer/` are normalized to `error.code = not_found`.

## 13. Null, optional and boolean semantics

- A field listed as nullable in the OpenAPI schema may be present with JSON `null`.
- Optional response fields may be omitted when a representation legitimately differs between list/detail forms; the OpenAPI schema marks them accordingly.
- For PATCH requests, omission means **leave unchanged**.
- The contract never uses string booleans such as `"yes"`, `"no"`, `"true"` or `"false"`. Boolean values are JSON `true`/`false`.
- Read-only output fields are not writable simply because they appear in a response.

## 14. Catalog and Ready Designed Products

Only published Storefronts and published StoreProducts are Customer-visible. Product responses expose Customer-relevant data only: localized title/description, public images, Store slug/name, Variant SKU/options/authoritative price/availability, fulfillment mode, lead-time field when modeled, customization eligibility and decoration-zone data on detail.

A product whose accepted DesignedProduct has persisted Artwork placements is represented as `kind = ready_designed`; otherwise the plain non-Studio cart kind is `plain`. A customizable product may also be used through a separately persisted Studio project.

Private Designer technical packages, internal cost, Manufacturer data and moderation fields are not serialized.

## 15. Artwork Marketplace

Only approved Artwork with an approved version and safe public preview media appears. Frozen fields include title/description/tags, creator public display name, approved version identifier, safe preview, production methods, suitability/product-type metadata that the existing public model explicitly permits, and update timestamp.

No licensing guarantee is invented. Approval/public suitability indicates platform state, not a legal warranty.

## 16. Studio contract

A Studio response contains enough persisted state for a native client to reconstruct the Customer project:

- project identifier/status
- Store/Product slugs and localized title
- selected Variant
- quantity/notes
- authoritative unit price
- Decoration Zones and persisted normalized geometry
- customization elements
- element kind: `text | image | artwork`
- text/private media/approved Artwork reference as applicable
- selected production method
- persisted transform
- style object
- source URL abstraction
- timestamps/Ready state.

Transforms preserve the accepted normalized model: `x`, `y`, `scale`, `rotation`; the server normalizes/validates placement. Flutter must not convert this persistence contract to guessed pixel coordinates.

Ready validation is server authoritative. A project cannot become Ready or enter checkout when publication, Variant, ownership, element, Artwork/method or transform rules are invalid.

## 17. Private Customer upload

Endpoint:

`POST /api/v1/customer/studio-projects/<project_id>/uploads/`

Contract:

- content type: `multipart/form-data`
- field: `file`
- accepted decoded image formats: PNG, JPEG, WebP
- maximum accepted upload size: **10 MiB / 10,485,760 bytes**
- wrong request media type: `415 unsupported_media_type`
- larger than limit: `413 upload_error`
- malformed/unsupported image: `400 upload_error`
- unavailable required production private storage: `503 service_unavailable`
- private Customer/project ownership remains enforced.

Successful metadata includes only an opaque asset ID, MIME type, size, decoded width/height and an authenticated application URL such as `/api/v1/customer/media/4001/`.

The response never contains S3 credentials, bucket credentials, encryption secrets or raw internal storage keys.

## 18. Protected media

`GET /api/v1/customer/media/<asset_id>/` requires Customer JWT authentication and scopes the asset to:

- private access
- the authenticated uploader
- the protected Studio-upload metadata marker.

An unrelated Customer receives `404 not_found`, not an ownership disclosure.

In local development/test storage, the authorized application may stream the file. In production S3 mode, the authorized application currently redirects to a short-lived signed GET URL generated by the existing storage service with a **300-second** expiry. Responses are private/no-store and non-indexable where applicable. No permanent public Customer-upload URL is part of the contract.

## 19. Cart

Cart supports the three accepted paths:

- `plain`
- `ready_designed`
- `studio`

Plain/Ready Designed writes identify Store/Product and Variant SKU. Studio Cart items reference a Customer-owned **Ready** Studio project. The server derives and validates product kind; a client cannot relabel a product to bypass rules.

Cart responses contain server-authoritative unit/line/cart totals. Quantity >1 remains quantity on one CartItem and later one operational child order for that line.

## 20. Checkout

Creating/reviewing/placing checkout re-runs authoritative backend rules. The server validates, as applicable:

- Store/Product publication
- DesignedProduct availability
- active Variant and stock/made-to-order rules
- quantity
- Studio ownership and Ready state
- approved Artwork eligibility
- production method and normalized transforms
- single Cart currency
- current server price.

Shipping fields are the only Customer-writable checkout detail fields. A finalized checkout is immutable.

## 21. Placement idempotency

`POST /api/v1/customer/checkouts/<checkout_id>/place/` requires `Idempotency-Key`.

Frozen syntax: 8–80 characters containing only ASCII letters, digits, `.`, `_`, `:`, `-`.

Semantics:

- first valid placement: `201`, one canonical Parent CustomerPurchase and one PaymentAttempt.
- same Customer + checkout + key + payment provider retry: `200` and the same canonical Purchase (`idempotent_replay = true`).
- same key with a different payment provider: `409 conflict`.
- a different key after the checkout is already placed: `409 conflict`.
- the client key itself is not persisted in clear text; a namespaced SHA-256-derived server value is stored in the existing PaymentAttempt idempotency field.

The mechanism does not add or redesign Commerce persistence.

## 22. Payment contract

Customer-visible payment methods are limited to the existing `cod`, `paymob`, `stripe` model, and `GET /payment-options/` returns **only methods currently available according to server configuration**. Online providers must be enabled and have a successful configured test state before they appear.

Placement may return:

- provider
- payment attempt machine status
- redirect URL where applicable
- provider client secret only where required for supported client-side provider continuation.

It never returns provider server secret keys.

For Paymob/Stripe, a client response or redirect does **not** mark the Purchase successful. Signed server webhook processing remains authoritative. Payment webhook routes are excluded from Flutter.

No real charge is executed by the contract tests.

## 23. Purchases, child item status and fulfillment

`GET /purchases/` and `/purchases/<uuid>/` use the parent CustomerPurchase as canonical Customer history.

The detail may include Customer-friendly nested items with:

- child UUID reference
- title/SKU/size/color/quantity
- unit/line money
- Customer-facing order status/code/label
- whether customized
- Studio project reference where relevant
- canonical FulfillmentRecord-derived status/label/carrier/tracking/timestamps.

It does not expose Manufacturer identity, ProductionJob internals, RFQ/quote state, QC internals, finance allocation or operations permissions.

Tracking is returned only when persisted in the canonical FulfillmentRecord; the API does not fabricate courier state.

## 24. Notifications and deep-link targets

Notifications are paginated and expose stable machine `type`, localized title/body, read state, timestamps and a resource-oriented target.

When an existing Web notification points to a Customer order/purchase, the Customer adapter resolves it to:

```json
{"resource":"purchase","reference":"<parent-purchase-uuid>"}
```

Flutter should route by resource/reference rather than parse English copy or temporary Web URLs.

Notification preferences expose actual modeled email/SMS toggles and E.164 phone input. External Mailgun/Twilio delivery is not implied by enabling a preference.

## 25. Throttling

Default repository throttle policy relevant to this contract:

- anonymous discovery: `120/hour`
- authenticated Customer requests: `1200/hour`
- login: `10/minute`
- refresh: `30/minute`
- Studio upload: `30/hour`
- checkout placement: `20/hour`

These values are deployment-configurable through the existing environment configuration. Clients must handle `429 rate_limited` generically and must not depend on undocumented anti-abuse internals.

## 26. API compatibility policy

`/api/v1/customer/` is the first stable Customer mobile contract.

Compatible v1 evolution may include:

- new optional endpoints
- new optional response fields
- new nullable/optional fields where old clients can ignore them
- new enum values where clients implement an unknown/fallback state
- additional filters that do not change existing filter meaning.

Breaking changes require deliberate versioning, normally a future major API prefix (for example v2), including:

- removing/renaming frozen routes or required fields
- changing field types or money/identifier semantics
- making optional fields required
- changing auth scheme/lifetimes in a way that invalidates the client lifecycle
- reinterpreting existing enum values
- changing parent Purchase/Commerce semantics
- weakening private-media authorization.

Deprecated v1 behavior must be documented before removal. Flutter v1 must ignore unknown response fields and handle unknown future machine enum values defensively.

## 27. Machine contract and fixtures

- OpenAPI: `docs/api/fabinzi-customer-api-v1.openapi.json`
- Endpoint inventory: `docs/CUSTOMER_API_V1_ENDPOINT_INVENTORY.md`
- Sanitized deterministic examples: `contracts/customer-api-v1-fixtures.json`
- Contract manifest: `contracts/customer-api-v1-manifest.json`
- Flutter handoff: `docs/FLUTTER_API_HANDOFF.md`

Contract/drift tests compare the frozen route/method/auth inventory and key OpenAPI semantics against actual URL/view behavior. CI packages the source-controlled contract and source SHA into the `customer-api-v1-contract` artifact.

## 28. Known truthful limitations

The following do not become PASS merely because a mobile contract now exists:

- no Customer self-signup lifecycle in this baseline
- no automated password reset
- no Customer email verification/account activation
- no social login
- external payment-provider production health is not proven by repository tests
- external SMS/email delivery is not proven by repository tests
- live production S3/provider connectivity is not proven by this repository-only checkpoint
- deferred Global Live E2E remains explicitly UNRESOLVED until the planned post-Flutter return.

These limitations do not change the frozen contract behavior above and must remain visible to the future Flutter phase.
