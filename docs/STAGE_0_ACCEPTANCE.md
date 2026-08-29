# Stage 0 — Engineering Foundation Acceptance

Stage 0 establishes infrastructure and cross-cutting platform foundations only. It intentionally does not implement later FABINZI business domains.

## Acceptance checklist

- [x] Greenfield Django + DRF project structure and versioned API foundation.
- [x] PostgreSQL production database configuration and clean initial migrations.
- [x] Redis + Celery background-job foundation.
- [x] Custom User with persisted Light/Dark/System theme and Arabic/English preference.
- [x] Arabic/English + RTL/LTR-aware template foundation.
- [x] FABINZI design tokens derived from approved logo colors.
- [x] Approved master SVG carried forward unchanged as the canonical repository brand asset.
- [x] Custom `/Maneg/` Django Control Center branding.
- [x] OTP/TOTP-protected Control Center foundation via django-two-factor-auth.
- [x] Append-only application audit-event foundation.
- [x] Integration configuration model with encrypted write-only secret payload support.
- [x] Provider enable/disable and safe Test Connection framework.
- [x] COD, Paymob, Stripe, Mailgun, Twilio, S3, Cloudflare Images and Sentry provider records supported.
- [x] COD seeded enabled; optional external integrations seeded disabled.
- [x] Logical MediaAsset model with provider and public/private classification.
- [x] Production non-image storage guard requiring S3 when used outside DEBUG.
- [x] In-app Notification domain foundation independent of external channels.
- [x] Global bilingual announcements with audience filtering foundation.
- [x] Scheduled Maintenance Mode with `/Maneg/`, account/MFA and health-check bypass.
- [x] Sentry runtime foundation, disabled until configured.
- [x] Secure-cookie/HSTS production baseline.
- [x] CI with PostgreSQL/Redis services and automated tests.
- [x] Backup and disaster-recovery baseline documentation.

## Explicit non-goals for Stage 0

Designer onboarding, Manufacturer onboarding, Garment Design, Artwork, catalog commerce, Studio, manufacturing routing, real checkout/payment transaction flows, finance settlement, and Flutter are later stages.
