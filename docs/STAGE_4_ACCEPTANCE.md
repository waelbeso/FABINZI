# Stage 4 — Manufacturer Marketplace — COMPLETE

Stage 4 establishes the verified Manufacturer discovery and pre-production sourcing layer. It deliberately stops before checkout, payment, production orders, and fulfillment, which belong to later stages.

## Delivered
- Public Marketplace exposes only verified, active Manufacturers with published listings.
- Bilingual Manufacturer listing headline/overview plus public contact controls.
- Declared MOQ, lead-time range, current available monthly capacity, materials, methods, markets, certifications, sampling and RFQ availability.
- Structured Manufacturer capabilities for cut & sew, print, embroidery, sampling, pattern making, finishing, packaging, and other services.
- Public image-only Manufacturer portfolio assets.
- Designer RFQs tied to a published Designed Product.
- Confidential invitations to eligible published Manufacturers.
- Manufacturer decline / quote workflow with MOQ, unit price, setup/sample/shipping estimates, lead time, validity and notes.
- Designer quote comparison endpoint and one-time Manufacturer selection.
- Selection records a sourcing decision only; it does not create an order or move money.
- Tenant isolation and role-based server-side authorization for Designer and Manufacturer actions.
- Audit events and in-app notifications for sourcing lifecycle events.
- Responsive public and portal web surfaces.
- DRF API endpoints for listing management, discovery, capabilities, portfolio, RFQs, invitations, quotes and selection.
- `/Maneg/` admin registrations.
- Automated Stage 4 tests.

## Acceptance Gate
Stage 4 is accepted only when GitHub CI passes migration drift check, migrations, Django system check, and the complete pytest suite.
