# FABINZI WEB v1.0 — Capability Inventory

This inventory freezes what the accepted Web product actually exposes. It does not add unsupported features.

## Customer / public Web

- Public FABINZI discovery with published storefronts, products, approved Artwork and active verified Manufacturer capability listings.
- English/LTR and Arabic/RTL rendering; Light/Dark/System theme behavior.
- Customer authenticated app home and language/theme preferences.
- Artwork Marketplace public browse/detail and approved preview media.
- Manufacturer public capability directory/detail.
- Plain or Studio-linked CartItems.
- Cart quantity update/removal and Cart checkout.
- Checkout shipping snapshot and payment option discovery.
- COD internal payment path; optional Paymob/Stripe only when configured/enabled/tested successfully.
- One Parent `CustomerPurchase` per Cart checkout with one child `CustomerOrder`/`OrderItem`/`ProductionJob`/`FulfillmentRecord` per CartItem.
- Purchase and child-order visibility including fulfillment status.
- Optional Visual Studio projects for eligible products, private uploads, text/image/approved-Artwork elements, decoration-zone placement/transform data, validation and Ready state.
- In-app notifications and user delivery preferences.
- Branded trust, error, maintenance and authentication surfaces.

Not present: automated Customer password reset or email verification/account activation.

## Designer Portal

- Designer organization profile and team visibility/management according to existing RBAC.
- Garment Design list/detail, versions/revisions, technical data, size information, decoration zones and review workflow through the accepted domain layer.
- Artwork list/detail, revisions, assets, IP declaration/review workflow and Designed Products/placements.
- Designed Product/storefront catalog visibility and publication controls supported by current services.
- Manufacturing RFQ list/detail and selected manufacturing sourcing visibility.
- Designer storefront and product management surfaces.
- Fulfillment visibility for relevant customer production lines.
- Finance visibility, earnings/settlement surfaces supported by current finance domain.
- Authorized Designer private-media delivery.

## Manufacturer Portal

- Manufacturer organization profile/team.
- Production capability management.
- RFQ opportunities/invitations.
- Manufacturing quote creation/detail and selection visibility.
- Assigned `ProductionJob` list/detail.
- Production execution transitions exposed by the accepted portal/domain layer.
- QC recording.
- Packing / Ready to Ship transition.
- Shipment/tracking recording through the **canonical `FulfillmentRecord`** path.
- Production evidence/private media under authorization.
- Manufacturer finance visibility.

Manufacturer is a production partner, **not** a catalog seller. No second fulfillment/shipment subsystem exists.

## `/Maneg/` Control Center

OTP/MFA-protected platform administration includes:

- operational dashboard;
- users;
- organizations;
- onboarding/verification;
- Garment Design technical review;
- Artwork/IP review and IP cases;
- catalog oversight;
- orders/Parent Purchase and child operational visibility;
- production/QC/fulfillment oversight;
- finance oversight;
- integration configuration and controlled connection tests;
- notification operations;
- announcements;
- maintenance windows;
- append-oriented audit-log visibility;
- system status;
- authorized private evidence;
- expert Django Admin access for registered models.

## Cross-cutting runtime capability

- PostgreSQL transactional persistence.
- Redis-compatible Celery broker/result transport.
- Celery worker plus Beat notification dispatch schedule.
- WhiteNoise static delivery in production.
- production private-media mode fails closed to S3 integration configuration.
- health/readiness endpoints.
- encrypted integration secrets.
- API throttling, CSRF/session security, HSTS/cookie/header controls, tenant/RBAC enforcement and private-route noindex policy.

Provider adapter presence is not evidence of production provider health.
