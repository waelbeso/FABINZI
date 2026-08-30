# FABINZI WEB v1.0 — Canonical Web Route Inventory

This is the release-facing route inventory for the integrated WEB v1.0 product. It records application routes; it does not create a new routing architecture.

## Public / trust / metadata

| Route | Purpose |
| --- | --- |
| `/` | FABINZI public home |
| `/robots.txt` | robots policy |
| `/sitemap.xml` | public sitemap |
| `/site.webmanifest` | Web manifest |
| `/favicon.ico` | favicon |
| `/apple-touch-icon.png` | Apple touch icon |
| `/icon-192.png`, `/icon-512.png` | manifest icons |
| `/share/fabinzi-1200x630.png` | social preview fallback |
| `/about/` | About |
| `/terms/` | Terms |
| `/privacy/` | Privacy |
| `/returns/` | Refunds & Returns |
| `/shipping/` | Shipping & Fulfillment |
| `/support/` | Contact & Support |
| `/store/` | storefront marketplace |
| `/store/<slug>/` | public storefront |
| `/store/<store_slug>/<product_slug>/` | public product |
| `/artwork/` | Artwork Marketplace |
| `/artwork/<pk>/` | public Artwork detail |
| `/artwork/media/<pk>/` | authorized public Artwork preview media |
| `/manufacturers/` | public Manufacturer capability directory |
| `/manufacturers/<pk>/` | public Manufacturer detail |

## Customer / authenticated Web

| Route | Purpose |
| --- | --- |
| `/app/` | Customer account home |
| `/app/settings/preferences/` | account language/theme preferences |
| `/notifications/` | notification center |
| `/cart/` | active Cart |
| `/cart/add/<product_id>/` | add published product |
| `/cart/items/<pk>/update/` | update CartItem quantity/state |
| `/cart/items/<pk>/remove/` | remove CartItem |
| `/cart/checkout/` | create/start Cart checkout |
| `/studio/` | Customer Visual Studio projects |
| `/studio/<pk>/` | Studio project |
| `/studio/<project_id>/checkout/` | Studio checkout start |
| `/media/private/<pk>/` | authorized Customer Studio private media |
| `/checkout/<pk>/` | checkout detail/shipping |
| `/purchases/` | Parent CustomerPurchase list |
| `/purchases/<pk>/` | Parent CustomerPurchase detail |
| `/purchases/<pk>/confirmation/` | purchase confirmation |
| `/orders/` | child CustomerOrder list |
| `/orders/<pk>/` | child CustomerOrder detail |
| `/orders/<pk>/production/` | order production/fulfillment visibility |

## Designer Web

`/designer/`, `/designer/profile/`, `/designer/team/`, `/designer/designs/`, `/designer/designs/<pk>/`, `/designer/artworks/`, `/designer/artworks/<pk>/`, `/designer/products/`, `/designer/products/<pk>/`, `/designer/rfqs/`, `/designer/rfqs/<pk>/`, `/designer/store/`, `/designer/store/products/<pk>/`, `/designer/fulfillment/`, `/designer/finance/`.

Authorized Designer private media: `/media/designer-private/<pk>/`.

Shared onboarding routes: `/onboarding/<pk>/edit/`, `/onboarding/<pk>/submit/`.

## Manufacturer Web

`/manufacturer/`, `/manufacturer/profile/`, `/manufacturer/team/`, `/manufacturer/capabilities/`, `/manufacturer/opportunities/`, `/manufacturer/marketplace/`, `/manufacturer/opportunities/<pk>/`, `/manufacturer/quotes/`, `/manufacturer/quotes/<pk>/`, `/manufacturer/production/`, `/manufacturer/production/<pk>/`, `/manufacturer/production/<pk>/qc/`, `/manufacturer/production/<pk>/ready-to-ship/`, `/manufacturer/production/<pk>/shipment/`, `/manufacturer/production/<job_id>/media/<asset_type>/<pk>/`, `/manufacturer/finance/`.

Manufacturer remains a production partner; these routes do not create a catalog-seller role.

## Shared operational routes

- `/finance/` — authenticated finance dashboard surface.
- `/healthz/` — safe liveness/application-version/source-identity diagnostic.
- `/readyz/` — database readiness only.
- `/api/v1/` — versioned REST boundary; inventoried separately and not contract-frozen here.

## Authentication

`django-two-factor-auth` URL patterns are mounted at the root by `two_factor.urls`. FABINZI overrides the login template for product branding while preserving the package wizard/token/backup-device flow. Package-owned route internals are not duplicated as a second FABINZI contract.

The repository currently has no Customer automated password-reset route and no Customer email verification/activation route.

## `/Maneg/` Control Center

Stable custom product routes beneath the OTP-required `FabinziAdminSite`:

- `/Maneg/` dashboard
- `/Maneg/users/`, `/Maneg/users/<pk>/`
- `/Maneg/organizations/`, `/Maneg/organizations/<pk>/`
- `/Maneg/verification/`, `/Maneg/verification/<pk>/`
- `/Maneg/design-review/`, `/Maneg/design-review/<pk>/`
- `/Maneg/artwork-ip/`
- `/Maneg/artwork-ip/version/<pk>/`
- `/Maneg/artwork-ip/case/<pk>/`
- `/Maneg/catalog/`
- `/Maneg/orders/`
- `/Maneg/production/`
- `/Maneg/finance/`
- `/Maneg/integrations/`, `/Maneg/integrations/<pk>/`
- `/Maneg/notifications/`
- `/Maneg/announcements/`
- `/Maneg/maintenance/`
- `/Maneg/audit/`
- `/Maneg/system/`
- `/Maneg/private/<asset_type>/<pk>/`
- `/Maneg/expert/`

The same AdminSite also exposes Django Admin authentication/model CRUD routes for registered models. Those framework-generated model paths are internal administration mechanics, not a separately promised public API surface.

## Indexing rule

Public discovery/trust routes are the indexable set. Customer/account/Cart/Checkout/Studio, Designer, Manufacturer workspace, `/Maneg/`, `/api/`, health/readiness and private-media routes remain excluded from public indexing by the accepted robots/application policy.
