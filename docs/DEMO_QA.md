# FABINZI Demo & QA Runbook

## Safety boundary

Demo/QA data is created only by the explicit management command:

```bash
python manage.py seed_demo
```

The command refuses to run unless `FABINZI_DEMO_SEED_ENABLED=true` and protected demo passwords are supplied. It is not called by migrations, Docker startup, Render startup, web requests, Celery worker startup or Beat startup.

Production must keep `FABINZI_DEMO_SEED_ENABLED=false`. The production `render.yaml` does not request demo passwords.

## Deterministic QA identities

The guarded seed creates/reconciles the existing roles and permissions architecture:

- FABINZI Platform Admin
- Designer organization owner
- Manufacturer organization owner
- Customer

Emails/passwords are environment values and are never printed or committed.

For the controlled live-QA Admin, the repository also provides:

```bash
python manage.py provision_demo_admin_otp
```

This command is separately guarded by the demo enable flag, requires `DEMO_ADMIN_TOTP_SECRET` from protected environment configuration, validates the base32 secret, provisions the confirmed `global-live-e2e` TOTP device and never prints the secret. It does not weaken `/Maneg/` MFA.

## Seed content

The seed provides deterministic approved Garment Designs, Artwork, Designed Products, a published Designer storefront/catalog, a verified Manufacturer listing/capabilities, RFQs/invitations/quotes/selections, Studio projects and customer checkout-ready records. The dataset exists to exercise the accepted architecture rather than create a parallel demo architecture.

Core identities preserved by the dataset include:

- plain, customizable and ready-designed customer product paths,
- Designer Artwork and storefront paths,
- Manufacturer RFQ/quote/selection paths,
- production/QC/packing/fulfillment paths,
- in-app notification and finance visibility,
- `/Maneg/` operational visibility.

## Idempotency

Natural QA identifiers are reused where practical. Re-running `seed_demo` must not create uncontrolled duplicate users, organizations, products, RFQs, quotes, capabilities or Studio projects, and it must not reset historical production/customer workflow records merely to make a test pass.

## Repository browser QA vs live QA

Normal CI browser tests use deterministic test databases and Chrome to prevent regressions. They are repository evidence, not proof of a deployed environment.

Actual Global Live E2E requires a real isolated non-production deployment and the dedicated manual `Global Live E2E QA` workflow. It must never be replaced with localhost, Django `live_server`, Django test client, mocks or normal CI screenshots.

## Deferred Global Live E2E state

The earlier Global Live E2E checkpoint was intentionally passed forward because its blocker was **A — QA environment/configuration failure**, not a source product regression. It was not live-accepted.

The durable unresolved register is:

`docs/DEFERRED_LIVE_E2E.md`

Original evidence recorded there includes source SHA `4adf44afbf777bacdf8377f1bb65d6522ce36ac7`, CI #309 / Run `33278567789`, 232 passed / 0 failed, and the complete unresolved live-validation list.

Do not mark those items complete during Production Launch Gate, API freeze or Flutter work.

## Planned post-Flutter return

After Flutter, resume the deferred gate by provisioning an isolated QA stack, deploying the exact then-current compatible source SHA, configuring protected QA identities and private S3, running guarded seed + Admin OTP provisioning, proving deployment identity, executing the real remote Chrome lifecycle, generating the required 20-shot artifact, manually inspecting every screenshot, and validating the Customer/Designer/Manufacturer/`/Maneg/`, Commerce, production/fulfillment, isolation, payment, async, localization/theme/responsive gates.

## Safe QA operating rules

- Never point the QA Blueprint at production PostgreSQL or Redis.
- Never use production customer accounts.
- Never reuse production messaging/payment credentials unless an explicitly safe sandbox/test configuration is intended.
- Never automatically seed production.
- Never commit QA passwords or TOTP secrets.
- Never disable MFA, CSRF, tenant isolation or private-media authorization to make QA pass.
- Only claim provider/Celery health when the deployed environment has actually been checked.
