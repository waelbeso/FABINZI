# FABINZI — Global Live E2E QA Audit

## Checkpoint repository lock

Global Live E2E QA starts from the exact integrated Web product SHA:

`3330a0c13711335f8e8a1f281e63ff1e17311a24`

Source branch: `feature/web-productization`.

Work branch: `work/global-live-e2e-qa`.

PR #6 was merged only into `feature/web-productization`. `main` remains intentionally untouched at `91f358c08d89557893e983f1c0d247fd1b42b15f`.

Draft PR #7 is the review/CI surface for this checkpoint and must remain unmerged until explicit instruction.

## Actual live environment audit — 2026-08-29

A dedicated external GitHub Actions probe was used because the repository contains more than one historical Render Blueprint and no Render account connector is available in the current tool environment. The probe did not modify the deployed services.

Audit workflow run:

- workflow: `Live Environment Audit`
- run: `33276754066`
- branch SHA: `4d24aeaa0153035bb572a418dda640b4010b7292`
- evidence artifact: `global-live-environment-audit`
- artifact ID: `9721727846`
- artifact digest: `sha256:1e8e307ec8a7cfeeb6f11e76e5bba5840ff3aabce7c802698e2d45e624a04b17`

### Observed public Render candidates

Both repository-declared Render hostnames currently resolve and answer over HTTPS:

- `https://fabinzi-web.onrender.com`
- `https://fabinzi-prod-web.onrender.com`

Both returned identical application-level results during the audit:

| Probe | fabinzi-web | fabinzi-prod-web |
| --- | --- | --- |
| `/healthz/` | 200, `{"status": "ok", "service": "fabinzi"}` | same |
| `/readyz/` | 200, database `ok` | same |
| `/api/v1/health/` | 200 | same |
| `/` | 200 | same |
| `/robots.txt` | 404 | 404 |
| `/static/css/maneg-control-center.css` | 404 | 404 |

The homepage response is the old minimal FABINZI page (`Fashion design meets distributed manufacturing.` / `Enter FABINZI`). The accepted integrated Web branch contains a materially newer public product and defines `/robots.txt`, the productized Studio, portals, and `/Maneg/` assets. Therefore **neither live hostname is currently running the accepted integrated Web product**.

The live shape matches the current `main` branch much more closely: current `main` contains the same minimal home template and its URL configuration does not define `/robots.txt`. This is strong evidence that the live Render services are still on a `main`-era deployment, consistent with both checked-in Blueprints targeting `main`; however it is not exact-SHA proof.

### Deployment SHA status

**BLOCKED / UNKNOWN on the current live processes.**

The deployed application currently exposes no commit or branch identity. `/healthz/` contains only service liveness and `/readyz/` only database readiness. Render provides non-secret runtime metadata such as `RENDER_GIT_BRANCH` and `RENDER_GIT_COMMIT`, but this application revision does not surface them.

Global Live E2E acceptance therefore must not run against either current hostname as if it represented the accepted integration SHA. A source-controlled, non-secret deployment-identity surface is required before exact deployment consistency can be certified.

### Observed HTTPS/security behavior

Both live hostnames returned the following security characteristics on successful probes:

- HTTPS/HTTP2 through Render/Cloudflare
- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- `Cross-Origin-Opener-Policy: same-origin`
- restrictive `Permissions-Policy`
- Gunicorn reported as Render origin server

These are positive observations only; they do not compensate for stale product deployment.

## Repository deployment topology audit

The repository contains two current Render Blueprints. Both target branch `main`, so neither can be assumed to be the Global Live E2E QA deployment without Render-side evidence.

### `render.yaml`

Repository-declared topology:

- web: `fabinzi-web`, free, Frankfurt
- PostgreSQL: `fabinzi-db`, PostgreSQL 17, persistent paid plan
- key/value: `fabinzi-redis`, free, Frankfurt
- worker: `fabinzi-worker`, Starter
- beat: `fabinzi-beat`, Starter
- web health check: `/readyz/`
- `DJANGO_DEBUG=0`
- `ENVIRONMENT=production`
- SSL redirect enabled
- demo seed disabled
- Sentry disabled in the Blueprint group
- public base URL `https://fabinzi-web.onrender.com`

### `render-fresh.yaml`

Repository-declared alternate topology:

- web: `fabinzi-prod-web`
- PostgreSQL: `fabinzi-prod-db`
- key/value: `fabinzi-prod-redis`
- worker: `fabinzi-prod-worker`
- beat: `fabinzi-prod-beat`
- production security settings equivalent to the primary Blueprint
- `PRIVATE_MEDIA_STORAGE_MODE=s3`
- public base URL `https://fabinzi-prod-web.onrender.com`

The public probe proves that both web hostnames exist and their databases answer readiness. It **does not prove** the actual current status of the worker/beat/key-value resources or which database each service is attached to. Those remain unverified until deployment-side/runtime evidence is available.

## Runtime configuration audit from source

The accepted application requires:

- PostgreSQL via `DATABASE_URL` as durable system of record;
- Redis-compatible `REDIS_URL` for Celery broker and result backend;
- Celery late acknowledgements and reject-on-worker-lost;
- a 60-second Beat schedule for dispatching pending external notification deliveries;
- production secure session/CSRF cookies;
- HTTPS redirect and one-year HSTS outside DEBUG;
- encrypted integration secrets via `INTEGRATION_ENCRYPTION_KEY`;
- OTP/MFA protected `/Maneg/`;
- WhiteNoise compressed-manifest static delivery outside DEBUG.

## Private-media audit from source

Production private media fails closed unless durable S3 storage is available:

- local private media is explicitly rejected outside development/test;
- `PRIVATE_MEDIA_STORAGE_MODE=s3` requires an enabled Amazon S3 `IntegrationConfig`;
- private Studio images are uploaded with `CacheControl=private, no-store`;
- S3 reads return short-lived (300-second) presigned access only after application-level authorization;
- private media remain `MediaAsset.Access.PRIVATE`.

The current live deployment's actual Amazon S3 IntegrationConfig state is **not yet independently known**. Therefore live private-upload capability must not be assumed to work merely because the source architecture requires it.

## Integration/provider state audit

Canonical provider rows are database-backed and secrets are encrypted. Providers are:

- COD
- Paymob
- Stripe
- Mailgun
- Twilio
- Amazon S3
- Cloudflare Images
- Sentry

COD is internal. Other payment providers must be enabled and have successful Test Connection state before use. External email/SMS delivery similarly requires enabled + successfully tested Mailgun/Twilio. Sentry's deployment runtime is separately controlled by environment configuration.

**Actual live database provider states remain unknown** until authenticated `/Maneg/`/runtime inspection is possible on the intended QA deployment. No connectivity or delivery claim is made at this stage.

## Demo-data audit

The repository provides a manually invoked, guarded `seed_demo` command. It refuses to run unless `FABINZI_DEMO_SEED_ENABLED=true` and requires secret demo passwords. It is not run by migrations, deployment startup, worker startup, Beat startup, or request handling.

The actual current live databases' demo seed state is **unknown** and will not be inferred from repository documentation.

## Audit decision before implementation

The actual public services are stale relative to the accepted integration and cannot be used for formal Global Live E2E acceptance in their current state.

Smallest correct next requirements are:

1. add a non-secret deployed branch/SHA identity to health/runtime evidence using Render-provided metadata;
2. establish a QA deployment that runs the Global Live E2E candidate SHA without merging to `main`;
3. only after exact SHA equality is proven, run the dedicated live-browser journeys with protected QA credentials and collect final evidence.

No accepted Commerce, Public Web, Artwork/Studio, Designer, Manufacturer, or `/Maneg/` architecture is reopened by these QA observability/deployment-harness requirements.

**Current checkpoint status: LIVE ENVIRONMENT AUDIT COMPLETE; DEPLOYED PRODUCT IS STALE; GLOBAL LIVE E2E EXECUTION NOT YET ELIGIBLE.**
