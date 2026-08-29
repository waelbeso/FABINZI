# Stage 3 — Artwork & Designed Products + IP Governance — COMPLETE

Stage 3 keeps Artwork, Garment Design, Designed Product and Customer Customization as distinct concepts.

## Delivered
- Designer-owned Artwork with immutable numbered Artwork Versions after submission/review.
- Artwork preview, private production-source and private rights-evidence assets.
- Mandatory IP Declaration with explicit rights basis, rights holder, third-party-content flag and IP-policy acceptance.
- Third-party Artwork cannot be submitted without private rights evidence.
- Artwork moderation workflow: Draft → Submitted → Approved / Revision Required / Rejected.
- Public Artwork Marketplace exposes only approved Artwork.
- Designed Product domain combines exactly an approved Garment Design Version and approved Artwork Version from the same Designer business.
- Artwork placements are constrained to Decoration Zones of the selected garment version and enforce print/embroidery compatibility.
- Designed Product publication gate requires approved inputs and at least one placement.
- IP/copyright case intake targeting exactly one Artwork or Designed Product.
- Private IP case evidence.
- Staff IP case moderation with takedown, restoration and rejected-claim outcomes.
- Takedown suspends affected Artwork and published Designed Products.
- Tenant isolation and Designer role authorization.
- Audit events and in-app notifications for review decisions.
- DRF API, Designer web surfaces, public Artwork Marketplace, and `/Maneg/` administration.
- Automated Stage 3 tests.

## Explicit Boundaries
- Customer Customization is NOT implemented in Stage 3.
- Printing and embroidery remain Manufacturer capabilities; Stage 3 only records production-method compatibility on Decoration Zones/placements.
- Checkout, manufacturing execution, fulfillment and finance remain later stages.

## Acceptance Gate
Stage 3 is accepted when GitHub CI passes migration drift check, migrations, Django system check and the complete pytest suite.
