# Stage 5 — Store & Studio — COMPLETE

Stage 5 delivers the customer-facing Store and Studio domains while keeping checkout, payment, orders, manufacturing execution, and finance out of scope for their later roadmap stages.

## Delivered
- One branded Storefront per approved Designer business with globally unique slug and bilingual public content.
- Public catalog exposes only Published Storefronts and Published Store Products.
- Store Product is a commercial presentation of a Stage 3 Published Designed Product; it does not replace or merge the Designed Product domain.
- Product variants with SKU, size, color, price adjustment, optional stock quantity, and active state.
- Public product image validation and storefront logo validation.
- Made-to-order and stock display modes without stock reservation or order creation.
- Optional Customer Customization kept as its own model/domain, separate from Artwork and Designed Product.
- Customer Studio Projects with selected variant, quantity, notes, optional customization, and Ready for Checkout state.
- Normalized text/image Customization Elements constrained to valid Stage 2 Decoration Zones.
- Cross-tenant Designer isolation and customer ownership isolation.
- Studio project immutability after Ready state.
- Audit events for Store and Studio state changes.
- Public and authenticated DRF APIs, responsive Django web surfaces, and `/Maneg/` administration.
- Automated Stage 5 tests.

## Explicitly deferred
- Cart / Checkout / COD / Paymob / Stripe: Stage 6.
- Order creation, production jobs, QC and shipping execution: Stage 7.
- Ledger, settlements, payouts, commissions and finance reporting: Stage 8.

## Acceptance gate
Stage 5 is accepted only when GitHub CI passes migration drift check, migrations, Django system check, and the complete pytest suite.
