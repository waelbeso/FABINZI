# FABINZI Demo & QA Runbook

## Safety rules

The demo dataset is created only by the manual Django management command:

```bash
python manage.py seed_demo
```

The command refuses to run unless:

```text
FABINZI_DEMO_SEED_ENABLED=true
```

It also requires all four demo password environment variables. It never runs from migrations, application startup, Docker startup, Render deployment startup, Celery worker startup, Beat startup, or request handling.

For normal production operation:

```text
FABINZI_DEMO_SEED_ENABLED=false
```

## Demo accounts

The command creates/reconciles these real account roles using the existing permissions architecture:

- FABINZI Platform Admin — Django staff/superuser for `/Maneg/` and normal OTP setup.
- Designer — owner of an approved active Designer organization.
- Manufacturer — owner of an approved active Manufacturer organization.
- Customer — normal active customer account.

Emails and passwords come from environment variables. Passwords are never printed by the command and are not stored in Git.

## Demo Designer catalog

The Designer owns five approved Garment Designs:

1. Bag — 320 GSM cotton canvas, print zone.
2. Cap — 260 GSM cotton twill, embroidery zone.
3. Men's T-Shirt — 180 GSM combed cotton jersey, DTF/DTG-compatible print zones.
4. Women's T-Shirt — 170 GSM cotton-elastane jersey, print customization zone.
5. Dress — 150 GSM viscose blend, plain/non-customized QA configuration.

The command creates valid version, size chart, technical JSON, decoration zone, and product-image metadata records where supported by the current domain model.

## Demo Artwork

Three approved Artwork records are created:

- `Blank Base` — an intentional no-placement record used to represent plain Store Products within the current StoreProduct/DesignedProduct schema.
- `Cairo Lines` — original print-oriented QA artwork.
- `Needle Star` — original compact print/embroidery QA artwork.

All demo graphics are original SVG files committed under `static/demo/`; no third-party copyrighted graphics are used.

## Ready Designed Product

`Cairo Lines Men's T-Shirt` combines:

- approved Men's T-Shirt garment version,
- approved Cairo Lines artwork version,
- Front Chest decoration zone,
- normalized placement transform,
- `print` production method.

This provides a ready-designed purchase path separate from plain purchase and Customer Customization.

## Demo storefront

The published `FABINZI Demo Studio` storefront contains:

- Men's T-Shirt - Plain — customizable, made to order.
- Women's T-Shirt - Customizable — customizable, made to order.
- Cap - Embroidery Ready — customizable, made to order.
- Canvas Bag - Printable — customizable, made to order.
- Day Dress - Plain — customization disabled.
- Cairo Lines Ready T-Shirt — ready-designed product.

Each product has an active deterministic QA SKU/variant and a stable static demo image reference.

## Demo Manufacturer

`FABINZI Demo Manufacturing` is an approved active Manufacturer with a published marketplace listing and capabilities for:

- Garments & Bags / cut-and-sew
- DTF / DTG printing
- computerized embroidery
- garment finishing
- retail packaging

Profile data includes QA legal identifiers, address, contact person, phone, website, Google Maps URL, capacities, materials, GSM range, and equipment metadata supported by the current models.

## Manufacturing opportunities/offers

The seed creates three Designer RFQs with Manufacturer invitations and submitted quotes:

1. QA Men's T-Shirt Production
2. QA Cap Embroidery Production
3. QA Canvas Bag Printing Production

The Men's T-Shirt offer is selected so a matching customer order can exercise Manufacturer assignment/routing. The other quotes remain useful for marketplace/offer QA.

## Customer QA records

The Customer receives three Studio projects:

1. a READY plain Men's T-Shirt project with a draft checkout and QA shipping address,
2. a DRAFT Women's T-Shirt customization project containing a sample text element,
3. a READY Cairo Lines Ready T-Shirt project.

The current repository does not contain a separate persistent CustomerProfile/default-address model. Shipping contact/address is captured by `CheckoutSession`; therefore the seed provides a realistic draft checkout address rather than inventing a nonexistent profile field.

## Idempotency

Natural demo identifiers are reused where practical. Re-running `seed_demo` must not create uncontrolled duplicate users, organizations, catalog items, RFQs, quotes, capabilities, or Studio projects. The command also avoids resetting existing customer orders or destructive workflow history.

Automated tests verify the disabled safety switch and idempotent object counts.

## End-to-end QA checklist

### Public/customer

1. Open `/store/` and the demo storefront/product pages.
2. Confirm plain, customizable, and ready-designed products are visible.
3. Sign in as Customer and open `/studio/`.
4. Open the pre-seeded customizable project and verify the customization element.
5. Use the READY plain project to create/complete checkout with COD.
6. Confirm the order appears in `/orders/` and notifications are created.
7. Repeat with the Ready Designed Product.
8. Verify language preference can switch English/Arabic and direction changes LTR/RTL.
9. Verify Light/Dark/System preference persistence.

### Designer

1. Sign in as Designer.
2. Verify the five Garment Designs in `/designer/designs/`.
3. Verify the three Artwork records in `/designer/artworks/` and the public artwork marketplace.
4. Verify Designed Products and storefront.
5. Verify RFQs and Manufacturer quotes in `/designer/rfqs/`.

### Manufacturer

1. Sign in as Manufacturer.
2. Verify the marketplace listing and capabilities.
3. Verify RFQ invitations/quotes.
4. For a confirmed matching Men's T-Shirt order, assign the selected Manufacturer.
5. Progress production milestones.
6. Request QC and record PASS.
7. Pack the order.
8. Ship it with carrier and tracking number.
9. Mark it delivered when QA is complete.

### Platform Admin

1. Sign in with the Admin credentials and complete OTP setup/verification through the normal two-factor flow.
2. Open `/Maneg/`.
3. Verify users, organizations, designs, artwork, storefront, RFQs/quotes, orders, operations, integrations, notifications, platform operations, audit, finance, settlements, and payout records are visible according to registered admin models.

## Production smoke endpoints

Expected unauthenticated checks:

```text
GET /healthz/        -> 200
GET /readyz/         -> 200 when PostgreSQL is reachable
GET /api/v1/health/  -> 200
GET /                -> 200
GET /store/           -> 200
GET /artwork/         -> 200
```

Authenticated surfaces such as `/app/`, `/studio/`, `/designer/`, `/manufacturer/`, and `/Maneg/` may redirect to the configured login/two-factor flow when no authenticated session exists; that redirect is expected behavior, not a failure.

## Acceptance evidence

Do not mark the pre-Flutter deployment accepted until CI is green, the Render deployment is healthy, the seed has been run manually with the safety flag, all four account credentials are verified, and the required business journeys have been exercised against the live Render database.
