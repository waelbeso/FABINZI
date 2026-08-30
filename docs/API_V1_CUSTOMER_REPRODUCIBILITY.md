# FABINZI Customer API v1 — Contract Reproducibility

## Baseline

The Customer contract is derived from the formally accepted FABINZI WEB v1.0 backend baseline (`APP_VERSION 1.0.0`). The API-freeze branch began from integration SHA `461c9079b5e53e51e5af4f6d564b891fe7e20b47`, produced by integrating WEB v1.0 RC3 only into `feature/web-productization`.

The exact frozen Customer API candidate is designated only after all contract-affecting files are complete. CI verifies it checks out the exact PR head rather than a synthetic merge commit.

## Runtime/dependency contract

- Python: `3.12.14`
- supported envelope: `requirements.txt`
- exact proven resolution: `constraints-release.txt`
- install: `python -m pip install -r requirements.txt -c constraints-release.txt`
- `python -m pip check` required.

The Customer checkpoint intentionally adds only the native-auth dependency family required by the contract:

- `djangorestframework-simplejwt>=5.5.1,<6.0`
- exact release constraint: `djangorestframework-simplejwt==5.5.1`

The SimpleJWT token-blacklist Django app is enabled for refresh rotation/revocation. No accepted FABINZI application migration history is rewritten. CI still requires `makemigrations --check --dry-run`, migration-state reconciliation and a fresh PostgreSQL migrate.

## Contract source set

The deterministic Customer contract consists of:

- `api/customer.py`
- `api/customer_urls.py`
- `api/customer_upload.py`
- `api/exceptions.py`
- relevant `config/settings.py` JWT/throttle/exception settings
- `docs/api/fabinzi-customer-api-v1.openapi.json`
- `docs/API_V1_CUSTOMER_CONTRACT.md`
- `docs/FLUTTER_API_HANDOFF.md`
- `docs/CUSTOMER_API_V1_ENDPOINT_INVENTORY.md`
- `contracts/customer-api-v1-manifest.json`
- `contracts/customer-api-v1-fixtures.json`
- Customer API auth/contract/Commerce/upload/OpenAPI/drift/security tests.

The manifest freezes the expected route/method/auth inventory and contract constants. Drift tests compare it with actual Django URL/view behavior and the committed OpenAPI document. CI generates SHA-256 evidence for the packaged contract source files.

## Frozen-candidate rule

Exactly one Git SHA is designated as `FABINZI Customer API v1 — Frozen Contract Candidate` after implementation, docs, schema, fixtures, drift protection and artifact generation are complete.

Any later change to Customer API code, OpenAPI, manifest, fixtures, human contract, handoff documentation, dependency resolution or other contract-affecting source invalidates that candidate. A new exact SHA and complete CI are then required.

## Required candidate CI

The candidate must pass the complete repository CI on PostgreSQL/Redis test services, including:

- exact source checkout
- Python 3.12.14
- exact dependency install + `pip check`
- `makemigrations --check --dry-run`
- migration reconciliation
- fresh migrate
- Django check
- collectstatic
- production `check --deploy`
- entire pytest suite
- Public/Customer Web regressions
- Artwork/Studio regressions
- Designer regressions
- Manufacturer regressions
- `/Maneg/` regressions
- Production Launch Gate regressions
- WEB v1.0 release-contract regressions
- Customer auth/contract/OpenAPI/drift/security/tenant/Commerce/payment/idempotency/upload tests
- all required legacy artifacts
- `customer-api-v1-contract` artifact.

No skips/xfails may be introduced merely to manufacture GREEN.

## Customer contract artifact

Successful candidate CI creates `customer-api-v1-contract` containing only source-controlled/sanitized contract material and generated evidence:

- OpenAPI
- human contract
- Flutter handoff
- endpoint inventory
- manifest
- synthetic fixtures
- reproducibility document
- exact source SHA evidence
- Python/dependency evidence
- `pip check`
- test inventory/summary
- SHA-256 checksums.

The artifact must not contain real Customer records, passwords, tokens, provider server credentials, private storage keys, database/Redis DSNs or other secrets.

## Reproducibility boundary

This freezes the source/runtime Customer API contract, not external provider health or bit-for-bit infrastructure. Paymob/Stripe production operation, Mailgun/Twilio delivery, live S3 connectivity, live Celery execution and the previously deferred remote Global Live E2E remain outside repository-only contract reproducibility and are not represented as passed.
