# FABINZI WEB v1.0 — Release Manifest

Authoritative semantic application version: **1.0.0**, defined only in `config/release.py`.

The exact Release Candidate source identity is the Git commit containing this manifest. It is intentionally not embedded inside the commit itself because doing so would create a self-referential SHA loop. Final CI, PR #9 metadata and the acceptance report record the exact candidate SHA.

## Proven predecessor

- Production Launch Gate: FINAL PASS / FORMALLY ACCEPTED / CLOSED.
- Accepted source SHA: `b05b2b0f3bed174aaf867bff9d10ef0b7cb3fbaa`.
- CI #342 / Run `33281214335`.
- 241 passed / 0 failed / 1 existing Django deprecation warning.
- Browser artifact `9723100271`.
- Digest `sha256:87c3ba0244639d086a4d729f55828ff31d3550c35d34072338b0847e0c33ee42`.
- Manual screenshot review: 12/12 PASS.
- Integrated only into `feature/web-productization` at `802dc0f091287f778d4e623caa375a32c67f97dc`.

## Release contract

- Python: **3.12.14**.
- Supported dependency envelope: `requirements.txt`.
- Exact WEB v1.0 dependency resolution: `constraints-release.txt`.
- Machine-readable manifest: `release-manifest.json`.
- Production topology: Django/Gunicorn, PostgreSQL, Redis-compatible transport, Celery worker/Beat, WhiteNoise static delivery.
- Production deployment is not performed by this checkpoint.

## Locked architecture

```text
Cart -> Checkout -> one Parent CustomerPurchase
Each CartItem -> one CustomerOrder -> one OrderItem -> one ProductionJob -> one FulfillmentRecord
```

```text
RFQ -> Manufacturing Quote -> Selection -> ProductionJob -> QC -> Packing -> Ready to Ship
-> canonical FulfillmentRecord -> Shipment / Tracking
```

Manufacturer remains a production partner, not a catalog seller. No second fulfillment/shipment architecture is introduced.

## Frozen records

See the route, capability, migration, configuration, deployment/rollback, reproducibility, limitations and preliminary API v1 inventory documents listed in `release-manifest.json`.

`docs/DEFERRED_LIVE_E2E.md` remains **UNRESOLVED**. No deferred item is converted to PASS by this release freeze; the planned return remains after Flutter.
