# Changelog

## 1.0.0 — FABINZI WEB v1.0 Release Preparation — 2026-08-30

### Product baseline included

- Public FABINZI Web and trust/legal baseline surfaces.
- Customer storefront discovery, Artwork Marketplace, Manufacturer directory, optional Visual Studio customization, Cart/Checkout, parent/child Commerce and purchase/order visibility.
- Designer Portal for profile/team, garment design, Artwork, products, RFQs, storefront, fulfillment and finance visibility.
- Manufacturer Portal for capabilities, opportunities/RFQs, quotes, assigned production, QC, packing/ready-to-ship, canonical fulfillment/shipment and finance visibility.
- MFA-protected `/Maneg/` operational Control Center.
- Versioned `/api/v1/` boundary sharing the accepted domain/service layer.

### Release-readiness freeze

- Added one authoritative semantic application version source: `config/release.py`.
- Frozen Python at 3.12.14 for the WEB v1.0 release contract.
- Preserved `requirements.txt` as the supported dependency envelope and added `constraints-release.txt` for the exact previously-green dependency resolution.
- Added machine-readable and human-readable release manifests.
- Added route, capability, migration, configuration, deployment/rollback, reproducibility, limitations and preliminary API inventories.
- Added focused release-contract tests and exact-source CI traceability.
- Added semantic version to the safe `/healthz/` payload while keeping deployment source identity limited to non-secret branch/commit/service metadata.

### Explicitly not claimed

No production deployment, live provider health, live S3 connectivity, backup restore drill, legal approval, public support coordinates, Flutter work, API contract freeze, or deferred Global Live E2E completion is claimed by this release-preparation checkpoint.
