# Stage 2 — Garment Design Domain — COMPLETE

Stage 2 implements FABINZI's Garment Design domain without merging it with Artwork, Designed Products, Customer Customization, or Manufacturer capabilities.

## Delivered
- Garment Design ownership scoped to approved Designer businesses.
- Immutable numbered Garment Design Versions after submission/review.
- Technical specifications and construction notes.
- Structured Size Chart rows.
- Decoration Zones with print/embroidery suitability and normalized geometry.
- Product Images and private Pattern / Tech Pack / 3D / Technical assets.
- Cloudflare Images is allowed for image media; private/general technical assets are blocked from Cloudflare Images and require private access.
- Technical submission gate requiring base material, technical specs, size chart, tech pack, and product image.
- Staff Technical Review: Approved / Revision Required / Rejected.
- Revision creation preserving prior technical definition while keeping review history immutable.
- Tenant isolation and role checks.
- Audit events and in-app review notifications.
- DRF endpoints and Designer web surfaces.
- `/Maneg/` administration registrations.
- Automated Stage 2 tests.

## Acceptance Gate
Stage 2 is accepted when GitHub CI passes migration drift check, migrations, Django system check, and the full pytest suite.
