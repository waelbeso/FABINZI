# FABINZI Production Launch Gate Audit

Checkpoint: **repository-side production readiness**. This document does not replace the deferred live register and does not assert a production deployment.

## Locked integration base

- PR #7 was integrated only into `feature/web-productization`.
- Production Launch Gate integration base: `17ad9011fbf4a7caa339073603ac11ef17fdef68`.
- `main` was not part of this checkpoint integration.

## Security / runtime audit

Repository controls include:

- DEBUG off in production policy.
- explicit production secret key requirement; development fallback rejected outside DEBUG.
- explicit HTTPS `FABINZI_PUBLIC_BASE_URL` outside DEBUG.
- production private-media mode fixed to S3; local private media rejected outside development/test.
- secure/HttpOnly session and CSRF cookies, SameSite=Lax.
- SSL redirect, HSTS, frame denial, content-type nosniff, same-origin referrer and opener policies.
- custom permissions/resource headers.
- CSRF protection with branded failure recovery and no rejection-reason leakage.
- private-route `noindex`/`nofollow` plus robots exclusions.
- OTP/MFA for `/Maneg/`.
- encrypted integration secrets.
- authorized private-media access paths.
- existing tenant/RBAC, audit, finance/payout and upload protections from the accepted domain architecture.

No security control was weakened for the launch gate.

## Legal / public trust surfaces

Repository launch surfaces now include About, Terms, Privacy, Refunds & Returns, Shipping & Fulfillment, and Contact & Support in English/Arabic.

The copy intentionally does **not** claim company registration, licensing, certifications, universal refund rights, guaranteed delivery SLAs, lawyer review, provider health or public support coordinates that have not been supplied/approved by the operator.

Jurisdiction-specific legal review and public support coordinates remain account-owner pre-go-live responsibilities.

## Account lifecycle

Implemented: login, logout, authenticated account surfaces, privileged two-factor authentication and invalid authentication handling through Django/two-factor flows.

Not implemented in the current repository: customer-facing automated password-reset and email verification/account-activation token flows. The launch gate does not invent them. This is a known product limitation to resolve before broad self-service customer account rollout if the intended operating model requires those features.

## Public error / maintenance experience

Branded bilingual 400, 403, 404, 500 and CSRF recovery surfaces exist. Maintenance restriction uses the real database-backed `MaintenanceWindow` and returns HTTP 503 while keeping configured operational safe prefixes available.

DRF throttling remains the API 429 mechanism using the configured anonymous/authenticated rate policies; this checkpoint does not invent a separate site-wide 429 source.

## SEO / indexing

Public/indexable routes are explicitly allowlisted. Canonical URLs, hreflang, Open Graph/Twitter metadata, social fallback image, robots and sitemap are generated from the configured public origin. Public trust pages are in the sitemap. Customer account, Cart/Checkout, Studio, Designer, Manufacturer operational workspace, `/Maneg/`, API, health/readiness and private-media surfaces remain excluded from public indexing.

## Brand / accessibility / responsive baseline

The approved SVG logo is unchanged. Runtime endpoints provide favicon, Apple touch icon, manifest icons and social preview fallback. Base templates retain semantic nav, skip link, language direction, persisted theme behavior and responsive mobile navigation. Launch trust/error templates use headings/sections, accessible navigation, mobile wrapping, visible recovery actions and reduced-motion handling.

This checkpoint does not claim formal WCAG certification.

## Performance / delivery source audit

- production static files use WhiteNoise compressed manifest storage.
- generated brand binaries carry cache headers.
- robots/sitemap/manifest outputs carry bounded public cache headers.
- existing major public/portal queries use select/prefetch patterns in accepted productized views.
- no destructive load test or performance SLA is claimed.
- focused real-Chrome CI checks assert no page-level horizontal overflow or debug/traceback leakage on launch evidence surfaces.

## Dependencies

The launch gate reviewed the existing Python 3.12 / Django 5.2 / DRF / psycopg / Redis client / Celery / Gunicorn / WhiteNoise / cryptography / boto3 / Sentry / Selenium dependency envelope. No major dependency architecture upgrade was introduced. Selenium remains a repository test dependency in the current single requirements file; separating dev/runtime requirements may be considered later but is not required to change accepted runtime behavior.

## Payments

- COD is an internal provider path and requires no external credential.
- Stripe and Paymob are optional and require enabled `IntegrationConfig` plus successful Test Connection before checkout use.
- remote payment creation uses idempotency keys.
- Stripe and Paymob webhook signature helpers use HMAC comparison; Stripe includes timestamp tolerance.
- purchase/order confirmation uses database transactions/select-for-update and idempotent confirmed-state returns.
- one parent CustomerPurchase and operational child orders remain unchanged.

No live card charge, payment success, provider health or webhook delivery is claimed by this repository audit.

## Async / integrations

Celery uses Redis for broker/result backend with late acknowledgment, reject-on-worker-lost, startup retry and task time limits. Beat dispatches pending external notification delivery once per minute. Live worker execution remains part of the deferred external validation where required.

Provider source support: COD, Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images, Sentry. Actual configured/production-ready state is account/environment data and is not inferred here.

## Backup / recovery

`BACKUP_AND_RECOVERY.md` documents Render's current paid-Postgres PITR capability separately from unverified FABINZI operational execution. No restore drill, workspace recovery window, off-platform backup, RPO or RTO is claimed as completed.

## Deferred Global Live E2E

`DEFERRED_LIVE_E2E.md` remains **UNRESOLVED**. The previous failure class stays **A — QA environment/configuration failure**. Nothing in this Production Launch Gate converts the deferred remote deployment/Chrome/20-shot/isolation/payment/async proof to PASS.
