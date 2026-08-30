# FABINZI — Flutter Customer API Handoff

This is a server-contract handoff only. It contains **no Flutter/Dart implementation** and does not authorize the Flutter checkpoint to begin until the API v1 Customer Contract Freeze is formally accepted.

## Contract to consume later

- Customer API base path: `/api/v1/customer/`
- Backend baseline: FABINZI WEB v1.0 / `APP_VERSION 1.0.0`
- Human contract: `docs/API_V1_CUSTOMER_CONTRACT.md`
- Machine contract: `docs/api/fabinzi-customer-api-v1.openapi.json`
- Endpoint inventory: `docs/CUSTOMER_API_V1_ENDPOINT_INVENTORY.md`
- Sanitized examples: `contracts/customer-api-v1-fixtures.json`
- Contract metadata: `contracts/customer-api-v1-manifest.json`

The exact frozen source SHA is the candidate accepted by the final Customer API freeze CI/artifact. Do not bind the client to an earlier checkpoint SHA.

## Native authentication lifecycle

Use Bearer JWT only for the Customer-native routes.

1. Login with `POST /auth/login/` using an existing account.
2. Store access and refresh tokens using a platform-appropriate secure credential store in the later mobile phase; never put tokens in URLs, logs, analytics, crash breadcrumbs or plaintext app preferences.
3. Access token lifetime: 15 minutes.
4. Refresh token lifetime: 30 days.
5. Refresh rotates; replace the locally stored refresh token only after a successful refresh response.
6. Old rotated refresh tokens are blacklisted and must not be retried indefinitely.
7. On `401 token_expired`/`invalid_token`, attempt the normal refresh lifecycle where a valid refresh token exists.
8. On `401 invalid_refresh_token`, clear that device's native session and return to sign-in.
9. Logout sends the device refresh token to `/auth/logout/`, then removes local tokens.
10. Multiple devices are independent; one device logout does not imply global logout.

The SSR Web application has a separate Django session + CSRF security model. Do not copy browser CSRF/session handling into the native client and do not request a permissive CORS change merely for native networking.

## Account capabilities the UI must not invent

The current baseline has no Customer self-signup, automated password reset, email verification/account activation or social login. The future mobile UI must not expose functioning buttons/flows for those features until the server contract is deliberately extended.

## Bootstrap

Call `/bootstrap/` as the safe capability/version source. It gives:

- contract/API/backend versions
- supported locales
- auth token lifetimes/rotation behavior
- unsupported account capabilities
- page-size limits
- upload formats/limit
- authoritative checkout policy.

Do not infer capabilities from hidden Web pages or legacy mixed `/api/v1/` endpoints.

## Locale and theme

- Send `Accept-Language: ar` for Arabic; otherwise use English.
- Persist user preference through `PATCH /me/` when the Customer changes language/theme.
- Theme values: `system`, `light`, `dark`.
- The server localizes human labels/copy where available; machine enum/status values remain stable.
- Arabic visual RTL layout is a future Flutter presentation concern; do not rewrite normalized Studio coordinates based on RTL.

## Money handling

Parse money from the server object:

```json
{"amount":"500.00","currency":"EGP"}
```

Treat `amount` as a decimal string. Do not parse through binary floating point for checkout calculations. Display-side arithmetic must never be sent as authoritative price. The server reprices/revalidates Cart and checkout.

## Datetimes

Use the API's ISO-8601 timezone-aware timestamps. Nullable lifecycle timestamps mean that event has not yet occurred. Always use the machine `status` as the primary state.

## Pagination

Paginated lists use:

- `count`
- `next`
- `previous`
- `results`

Default page size is 20; maximum requested size is 50. The future client may follow `next` or calculate page numbers, but must preserve auth headers and locale. Do not assume a list is complete after one page.

## Error handling

Branch behavior on `error.code`, not English `message` text.

Important codes:

- auth: `authentication_required`, `invalid_credentials`, `token_expired`, `invalid_token`, `invalid_refresh_token`
- resource/security: `permission_denied`, `not_found`
- input/state: `validation_error`, `conflict`, `invalid_state`
- abuse/service: `rate_limited`, `upload_error`, `unsupported_media_type`, `payment_error`, `service_unavailable`

`error.fields` supplies field-level validation messages when available. `request_id` is a safe support correlation identifier.

Cross-Customer private lookups deliberately return `404 not_found`; the app must not distinguish “someone else owns it” from “does not exist.”

## Catalog journey

Use the frozen Customer discovery routes only:

- Stores list/detail
- Products list/detail
- Artwork list/detail.

Product writes should use Store/Product slugs and Variant SKU. Product detail exposes the Variant availability/price and Decoration Zones required for Studio.

Ready Designed Product is represented by `kind = ready_designed`. A normal non-placed product is `plain`; a Customer-created Studio item uses `kind = studio` when added by Studio project reference.

Do not call Designer/Manufacturer catalog-management APIs.

## Artwork Marketplace

Use only approved public Artwork returned by `/artworks/`. Supported search/filter contract:

- `q`
- `method=print|embroidery`

Use `approved_version_id` when creating a Studio Artwork element. Public preview URL is safe delivery metadata, not a production source-file URL or licensing warranty.

## Studio persistence

The server is the persistence source for Visual Studio state.

Recommended later-client sequence:

1. Create Studio project with Store/Product slugs and optional Variant SKU.
2. Enable customization.
3. Add text/image/Artwork elements.
4. Persist normalized transform after relevant edits.
5. Reload project when re-entering Studio rather than relying on a local-only scene.
6. Call validation before showing final readiness feedback.
7. Mark Ready using the server endpoint.
8. Create checkout only after Ready succeeds.

Transforms are normalized values `{x,y,scale,rotation}`. Do not invent pixel-coordinate persistence.

## Private image upload

Upload with `multipart/form-data`, field name `file`.

Accepted decoded formats:

- PNG
- JPEG
- WebP

Hard maximum: 10 MiB (10,485,760 bytes).

Handle:

- 400 invalid/malformed image
- 413 size limit
- 415 wrong request content type
- 429 upload throttle
- 503 private storage unavailable.

The response gives an opaque media asset ID and authenticated application `access_url`. Do not persist or attempt to derive raw provider keys.

When later displaying a protected image, fetch the application URL with the Bearer token. In S3 mode the server may answer with a short-lived 302 signed URL (currently 300 seconds). Treat signed URLs as ephemeral; do not store them as durable project data.

## Cart

The Cart response is server-authoritative.

For plain/Ready Designed:

- send `kind`
- Store slug
- Product slug
- Variant SKU
- quantity.

For Studio:

- send `kind = studio`
- Customer Studio project ID
- quantity only where intended; otherwise the server uses the Studio quantity.

The server validates actual product kind and rejects attempts to relabel products.

## Checkout

Create checkout from Cart or from a Ready Studio project. Then PATCH allowed shipping fields.

Do not send totals, discounts, price, Manufacturer or payment state. On every checkout/placement boundary the server revalidates publication, availability, Variant, quantity, Studio ownership/Ready state, Artwork/method/transform rules, currency and price.

## Idempotent purchase placement

Every `POST /checkouts/<id>/place/` requires a new operation-level `Idempotency-Key` that matches the frozen 8–80 character pattern.

Recommended future client behavior:

- Generate one random opaque key when the user starts a single placement action.
- Persist it long enough to safely retry network ambiguity for that checkout/payment choice.
- Retry the **same** key if the HTTP result is lost/unknown.
- Do not generate a new key merely because a retry button was tapped after a transport timeout.
- Same key/provider returns the same Purchase (`idempotent_replay=true`).
- Provider mismatch or a different key after placement returns 409 and should trigger Purchase/checkout refresh rather than another blind placement.

## Payments

Call `/payment-options/` and show only returned providers.

COD can complete synchronously according to current backend rules. Paymob/Stripe may return redirect/client-secret continuation data when server configuration allows them. The app must not declare online payment success from a provider SDK callback alone. Refresh the Purchase; server webhook state is authoritative.

Never call `/api/v1/payment-webhooks/` from Flutter.

## Purchase history and fulfillment

Use the **parent Purchase UUID** as the Customer order-history/navigation reference.

Purchase detail can contain multiple Customer-friendly nested items because each Cart line has its own downstream operational order. Do not model those child items as independent Customer purchases.

Use the nested canonical fulfillment fields for Customer visibility:

- status/label
- carrier if persisted
- tracking number if persisted
- tracking URL if persisted
- packed/shipped/delivered timestamps if persisted.

Do not display invented tracking or Manufacturer operational/QC/RFQ state.

## Notifications

Notifications are paginated. Render by stable `type`, localized title/body and read state.

For navigation, consume `target`:

```json
{"resource":"purchase","reference":"<parent-purchase-uuid>"}
```

Do not parse Web `destination` strings or notification English copy. A null `target` means the server has no frozen native navigation target for that notification.

Notification preference toggles represent user preferences only; they do not guarantee an external email/SMS provider is configured or delivered.

## Rate limiting and retries

Handle 429 through the standard error envelope. Avoid aggressive retry loops, especially for login, refresh, uploads and placement. Do not encode current server throttle values into business logic; they are documented defaults and may be operationally configured.

## Compatibility rules for the future Flutter client

To remain v1-compatible:

- ignore unknown response fields
- provide a fallback for unknown future enum/status values
- distinguish omitted PATCH fields from explicit nullable values
- do not assume optional fields are always present
- do not depend on database integer ordering
- use parent Purchase UUID for Customer purchase navigation
- use server authoritative money/status and persisted Studio state.

Breaking server changes require deliberate versioning rather than silently changing this contract.

## Payment/provider and external-service limitations

Repository CI does not prove live Paymob/Stripe charges, Mailgun/Twilio delivery, production S3 account connectivity, or live Celery execution. Those remain operational/deferred evidence items. The native app should treat server-reported availability/state as truth rather than assuming a provider is live from its name.

## Deferred live QA

`docs/DEFERRED_LIVE_E2E.md` remains **UNRESOLVED**. Its live deployment/browser/private-media/payment/Celery/locale/theme/responsive validation returns after Flutter as already planned. This handoff does not convert those deferred items to PASS.
