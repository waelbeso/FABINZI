# FABINZI /Maneg/ Control Center — Repo-first audit

Audit baseline: `feature/web-productization` at `f24151813e2ec771d452e787f0dded345cbd55ad`, created by merging the formally accepted Manufacturer Portal checkpoint (`18c9db21bb92a7402b1d4b891dcc4795d8564034`) into the integration branch. This document is the mandatory first commit on `work/maneg-control-center-productization`; no /Maneg/ implementation code was changed before this audit.

## Executive finding

FABINZI already has a broad, real platform-administration backend and a custom OTP-required Django Admin site at `/Maneg/`. It is **not** missing an administration architecture. The gap is productization: today `/Maneg/` is a lightly branded stock Django Admin with broad model registrations and a few custom actions/templates. The correct checkpoint implementation is therefore additive:

1. retain the existing `FabinziAdminSite(AdminSiteOTPRequired)` as the authentication/MFA and expert Django Admin surface;
2. add a FABINZI-styled Control Center as custom routes inside that same AdminSite, so its `admin_view`/OTP gate remains authoritative;
3. apply explicit Django model permissions to every custom read and mutation, with stricter permission combinations for high-risk operations;
4. reuse existing domain services and audit records for state transitions; do not duplicate Commerce, Store, Artwork, Studio, Designer, Manufacturer, production, fulfillment, or finance domains;
5. leave stock ModelAdmin screens available as an expert fallback, while making the custom Control Center the primary `/Maneg/` operating experience.

## Existing route, privacy, authentication, MFA and theme foundation

| Requirement | Actual repository state | Classification |
| --- | --- | --- |
| `/Maneg/` route | `config/urls.py` maps `Maneg/` to `fabinzi_admin_site.urls`. | Already implemented and usable |
| Admin authentication | `FabinziAdminSite` subclasses `two_factor.admin.AdminSiteOTPRequired`. | Already implemented and usable |
| MFA stack | `django_otp`, TOTP/static plugins, `two_factor`, `OTPMiddleware`, and two-factor URL patterns are installed; `LOGIN_URL` is `two_factor:login`. | Already implemented and usable |
| Staff/superuser authorization | Django Admin site + ModelAdmin permission machinery exists. Existing service functions often use `is_staff` for staff review. | Implemented; custom Control Center must add explicit per-model permissions |
| `/Maneg/` privacy | `SecurityHeadersMiddleware` applies `X-Robots-Tag: noindex, nofollow, noarchive` to non-public URL names; robots.txt disallows `/Maneg/`; sitemap is explicit public-only. | Already implemented and usable; custom templates should also emit robots meta |
| Maintenance lockout prevention | `MaintenanceModeMiddleware.SAFE_PREFIXES` includes `/Maneg/`, health/readiness, static, account paths. | Already implemented and usable |
| EN/AR | Global LocaleMiddleware + public locale override support English and Arabic. | Implemented; stock Admin is not product-quality bilingual |
| Light/Dark/System | `accounts.User` persists `theme_preference` with system/light/dark and `language_preference`. | Already implemented; new Control Center should reuse it |
| Existing visual branding | `templates/admin/base_site.html` uses the approved FABINZI logo and `static/css/admin.css`, but otherwise inherits stock `admin/base.html`. | Partially implemented |

### MFA conclusion

Do not build parallel OTP. Custom `/Maneg/` views must be registered under the existing `FabinziAdminSite` and wrapped by its `admin_view`, preserving `AdminSiteOTPRequired`. Dedicated tests are missing and must prove unauthenticated, non-staff, staff-without-verified-device, OTP-verified staff, permission-scoped staff, and superuser behavior.

## Platform operations models

### Announcement Banner

`PlatformAnnouncement` already persists:
- EN/AR title and message;
- severity (`info`, `success`, `warning`, `maintenance`, `critical`);
- audience (`all`, customers, designers, manufacturers, staff);
- enabled state;
- start/end schedule;
- dismissibility;
- optional EN/AR CTA and URL;
- priority and creator metadata.

`PlatformAnnouncement.active()` is time-window aware and the context processor filters by real audience. Admin saves are audited through `AuditedOpsAdmin`.

**Classification: already implemented backend; stock Admin only. No new announcement model is required.**

### Maintenance Mode

`MaintenanceWindow` already persists enabled state, mode (`banner` or `restrict`), EN/AR messages, start/end schedule, creator and updated timestamp. `MaintenanceModeMiddleware` enforces real 503 restriction for non-safe surfaces and keeps `/Maneg/` reachable. Banner-only mode is exposed by the context processor. Admin saves are audited.

**Classification: already implemented backend; stock Admin only. No new maintenance model is required.**

A custom Control Center can compute truthful retry/return guidance from the real end time without inventing a second maintenance state.

## Users / groups

`accounts.User` extends `AbstractUser`; stock `UserAdmin` and `GroupAdmin` are registered on the FABINZI AdminSite. User status, staff/superuser flags, groups/permissions, theme and language are therefore administrable now.

Gaps:
- no FABINZI Control Center user list/detail;
- no dedicated audited user-suspension wrapper;
- stock UserAdmin can mutate high-risk flags directly;
- no safe MFA-status presentation in `/Maneg/` tests/UI yet;
- no focused account audit history presentation.

**Classification: implemented but primarily stock Admin; high-risk custom workflow partially missing.**

Control Center should never render password hashes, OTP device secrets/keys/tokens, session secrets, or reset tokens. User suspension must require explicit permission/confirmation, protect against unsafe self-lockout/escalation cases, and append an audit event.

## Organizations, memberships, onboarding and verification

Actual models: `Organization`, `Membership`, `DesignerProfile`, `ManufacturerProfile`, `OnboardingApplication`, `VerificationDocument`.

Important real invariants/capabilities:
- organization kinds are Designer/Manufacturer;
- verification states are draft/pending/active/rejected/suspended;
- membership roles are type-constrained in `Membership.clean()`;
- verification documents are required to reference PRIVATE `MediaAsset` records;
- `review_application()` permits staff only, only reviews submitted applications, keeps organization status synchronized, notifies members, and audits the decision;
- stock Onboarding Admin has POST-only approve/revision/reject endpoints that already call `review_application()`;
- Organization and Membership themselves are still editable via ordinary ModelAdmin/inlines.

**Classification:** onboarding review is implemented and service-backed; organization/membership administration is stock Admin and partly too raw for primary Control Center use.

Gaps to productize:
- searchable organizations + member/role visibility;
- explicit Designer/Manufacturer verification queues/details;
- secure staff-only access to verification documents without weakening PRIVATE media policy;
- audited organization suspension/restriction workflow;
- preserve owner/role invariants rather than raw inline mutation in custom flows.

## Garment Design technical review

Actual domain exists: `GarmentDesign`, `GarmentDesignVersion`, `SizeChartRow`, `DecorationZone`, `DesignAsset`, `TechnicalReview`.

`design.services.review_version()` is already the correct staff review contract: staff-only, submitted-version-only, validates decision, creates `TechnicalReview`, synchronizes version/design status, sends EN/AR notifications, and records audit events. Technical assets are PRIVATE except explicit product images.

Current ModelAdmin is mostly generic registration; it does not provide a focused technical review workflow.

**Classification: service/backend fully implemented; primary staff review UI genuinely missing.**

Control Center should inspect persisted technical specs/size charts/zones/assets and call `review_version()` for review decisions. It must not silently edit Designer technical content or fabricate geometry.

## Artwork / IP moderation

Actual domain includes `Artwork`, `ArtworkVersion`, `ArtworkAsset`, `ArtworkReview`, `IPDeclaration`, `IPCase`, `IPCaseEvidence`, `DesignedProduct`, and `ArtworkPlacement`.

Existing services enforce the accepted privacy/publication model:
- PREVIEW, SOURCE, RIGHTS_EVIDENCE are distinct asset kinds;
- production source and rights evidence remain private;
- approval creates/enables a separate public preview derivative;
- non-approval/revision state revokes public preview derivatives;
- `review_artwork_version()` is staff-only, submitted-only, creates review history, updates status, publishes/revokes preview state, notifies, audits;
- IP case moderation is exposed through service-backed Admin actions (`moderate_ip_case`) and audited;
- public preview is not the private source/evidence.

Current Admin nevertheless exposes raw related models and IP reporter fields to any staff user with corresponding Django permissions.

**Classification: moderation backend/service implemented; stock Admin presentation; permission/privacy productization required.**

Custom `/Maneg/` must permission-gate private source, rights evidence, IP evidence and reporter/staff-note detail more strictly than generic browsing, and must never expose those through public/media routes.

## Designed Products and Store / Catalog

`DesignedProduct` remains the accepted product-design aggregate linked to approved Garment/Artwork versions and placements. Store is the existing `Storefront` → `StoreProduct` → `ProductVariant` domain. Stock ModelAdmins expose listings, relationships, prices, status and variants.

**Classification: domain implemented; stock Admin only.**

Control Center should be an inspection/moderation surface over these exact records. It must not create Maneg-specific product/catalog copies, mockups, manufacturing renders, or alternate pricing.

## Customer commerce / orders

The accepted distinction is present in the real Admin registrations/models:
- customer parent context: Cart → Checkout → `CustomerPurchase`;
- operational children: `CustomerOrder` → `OrderItem` → Production/fulfillment.

Both `CustomerPurchase` and `CustomerOrder` are registered separately. Payment attempts and webhook events are real records; webhook events are read-only/no-add in Admin.

**Classification: domain implemented; operational investigation is stock Admin only.**

Control Center should explicitly present parent purchase and child orders as separate linked sections and show persisted payment state only. It must not expose provider secrets or treat provider payloads as customer-facing data.

## Production, QC, fulfillment and shipment

Canonical models are already present: `ProductionJob`, `ProductionMilestone`, `QCInspection`, `ProductionAsset`, `FulfillmentRecord`, `FulfillmentEvent`.

Current Admin:
- exposes ProductionJob + milestones;
- makes QCInspection read-only/no-add;
- exposes the canonical FulfillmentRecord (no second shipment model);
- makes FulfillmentEvent read-only/no-add;
- registers ProductionAsset.

Accepted Manufacturer services remain the authoritative normal transition path. Generic ModelAdmin can still edit some production/fulfillment records directly.

**Classification: backend implemented; stock Admin inspection; custom intervention surface should be conservative/read-mostly and use real services where available.**

No second production, QC, packing, shipment or tracking records should be introduced.

## Finance / settlements / payouts

Actual finance models: `FinancePolicy`, `FinanceAccount`, `OrderFinance`, `LedgerEntry`, `PayoutProfile`, `SettlementRequest`, `FinanceAdjustment`.

Strong existing service contracts already cover:
- actual ledger-derived balances (`account_balance`);
- finance recognition only after canonical delivery;
- payout-profile submit/review;
- settlement request/review/cancel;
- marking approved settlements paid with required external reference and ledger entry;
- staff adjustments;
- staff checks and audit records.

Admin already makes OrderFinance and Ledger effectively read-only and FinanceAdjustment no-add; however PayoutProfile, SettlementRequest and FinancePolicy remain ordinary editable ModelAdmins.

**Classification: backend/service fully implemented; secure product UI missing; stock Admin fallback is broader than desired.**

Control Center must use real balances only, mask payout destination detail, never expose full payment/payout credentials, and require explicit finance Django permissions plus existing service authorization for mutations.

## Integrations / payments / storage

`IntegrationConfig` supports only actual seeded providers:
- COD (seeded enabled);
- Paymob, Stripe, Mailgun, Twilio, Amazon S3, Cloudflare Images, Sentry (seeded disabled).

It persists enabled state, non-secret JSON config, encrypted secrets, last test status/message/time and updater. `IntegrationConfigAdminForm` is write-only for secrets (`PasswordInput(render_value=False)`). Secrets are encrypted via the existing encryption key architecture and never returned by the form. Admin save/test actions are audited.

`test_connection()` performs real remote/provider checks for Stripe, Paymob, Mailgun, Twilio, S3 and Cloudflare Images; COD is an internal no-network capability. The current Sentry branch only proves configuration presence and explicitly says runtime event delivery remains deployment-controlled; it is **not** a live Sentry delivery test.

**Classification: integration configuration/test backend implemented; custom Control Center missing. Sentry live connection test intentionally unsupported by current backend.**

Control Center must label Sentry truthfully as configuration/runtime status rather than claiming a successful network connection. It must never render encrypted secret material, encryption keys, S3 keys, webhook secrets or provider credentials.

Private-media production behavior is configured by `PRIVATE_MEDIA_STORAGE_MODE`; production/local misuse fails closed in settings. Control Center may report mode/configuration status, not credentials.

## Notifications

Actual records: `Notification`, `NotificationPreference`, `NotificationDelivery`. Delivery records persist real channel/provider/status/attempt/error/sent timestamps and are read-only in Admin. Existing tests verify opt-in behavior and recipient scoping.

**Classification: implemented; stock Admin only.**

Control Center should expose delivery diagnostics and configuration state, while avoiding broad display of notification bodies that may contain private business/customer content.

## Audit Log

`AuditEvent` persists actor/action/object/id/metadata/IP/time. The model rejects updates after insertion (append-only). Admin disables add/change/delete.

**Classification: already implemented and strong; product-quality filtering/safe metadata rendering missing.**

Control Center must stay read-only, support useful filters, and sanitize sensitive metadata keys/values before rendering. No ordinary Control Center route may delete/change audit history.

## Security / system status

Truthful signals already available:
- `ENVIRONMENT`, `DEBUG`;
- database readiness (`readyz` runs `SELECT 1`);
- Redis URL/Celery broker configuration exists;
- private media mode;
- integration persisted states;
- Sentry enabled/configured state;
- secure cookie/HSTS/SSL/security setting booleans;
- maintenance state.

There is **no persisted/verified backup status**, **no uptime metric**, **no security score**, and no current verified Celery-worker health endpoint. `healthz` only reports service process response; `readyz` verifies database connectivity.

**Classification: partial truthful system signals; do not invent the missing health/monitoring concepts.**

Control Center may perform a real, bounded Redis ping and DB query. For Celery it should report configuration only unless a real worker response is actually obtained; no green “worker healthy” assumption. Never render SECRET_KEY, DATABASE_URL, REDIS_URL, encryption keys, Sentry DSN or credentials.

## Demo/admin utilities and Celery controls

`seed_demo` and migration reconciliation are management commands, not ordinary operational UI. `FABINZI_DEMO_SEED_ENABLED` gates demo seeding. Celery configuration and notification dispatch schedule exist, but no safe web-based Celery task-control console is implemented.

**Classification: management-command capability only; intentionally unsupported as ordinary `/Maneg/` mutation controls for this checkpoint.**

Do not add fake worker/task controls just to populate the Control Center.

## Current test posture

Existing suites cover stages 0–9 plus all accepted Web Productization checkpoints, including Commerce, public/customer, Artwork/Studio, Designer and Manufacturer real-browser regressions. Foundation/communications tests cover optional integrations disabled by default, COD enabled, announcement scheduling, maintenance behavior, append-only audit, readiness DB checks, notification scoping/opt-in and security headers.

There are currently **no dedicated `/Maneg/` product acceptance tests or `/Maneg/` Selenium artifact tests**. MFA behavior is provided by `AdminSiteOTPRequired` but lacks the required checkpoint-level acceptance coverage.

**Classification: previous regressions implemented; Maneg acceptance/browser suite genuinely missing.**

## Admin registrations — keep as expert fallback

The custom OTP AdminSite currently registers operational models across:
- Accounts/User/Group;
- Organizations/profiles/onboarding/memberships/documents;
- Garment Design/version/size/zones/assets/reviews;
- Artwork/IP/designed products/placements/assets/declarations/cases/evidence;
- Manufacturer marketplace/RFQ/quotes/selections/listings/capabilities;
- Store/variants/Studio customization;
- Cart/Checkout/Purchase/Orders/Payment records;
- Production/QC/Fulfillment/assets/events;
- Finance/ledger/payout/settlements;
- Notifications/deliveries/preferences;
- Integrations;
- Announcement/Maintenance;
- MediaAsset;
- AuditEvent.

This operational breadth should be retained. Productization must not remove useful ModelAdmin power merely to make the new UI simpler.

## Concrete implementation plan derived from the audit

### 1. Keep the same AdminSite/MFA perimeter
- Extend `FabinziAdminSite` with custom Control Center URLs/index.
- Wrap every page in `admin_view` so OTP verification remains mandatory.
- Add a FABINZI `/Maneg/` base shell with noindex meta, existing logo, account language/theme preferences, EN/AR RTL/LTR, desktop/tablet/mobile navigation.
- Keep ModelAdmin URLs available under the same site as expert fallback.

### 2. Explicit permission matrix
- Require Django `view_*` permission for each domain page.
- Require `change_*` (and where appropriate multiple related permissions) for mutations.
- Superuser retains full access.
- High-risk actions (user suspension, onboarding decisions, IP moderation, finance/settlement, integrations, maintenance) are POST-only, CSRF-protected, explicit/confirmed and audited.
- Hidden buttons are never the authorization mechanism.

### 3. Primary Control Center areas backed by real data
Productize a compact IA rather than one page per model:
- Overview;
- Users;
- Organizations + verification/Designer/Manufacturer review;
- Design review;
- Artwork/IP + Designed Product relationships;
- Catalog/Store;
- Purchases/Orders;
- Production/Fulfillment;
- Finance/Settlements/Payouts;
- Notifications;
- Integrations;
- Announcement;
- Maintenance;
- Audit Log;
- Security/System Status.

### 4. Reuse service-backed mutations
Use existing services for:
- onboarding review;
- Garment Design version review;
- Artwork version/IP moderation;
- finance payout/settlement/adjustment transitions;
- integration connection tests;
- existing production/fulfillment transitions where a staff intervention is genuinely exposed.

Add only small staff-oriented wrappers where genuinely missing, notably audited safe user suspension and organization suspension, plus platform-ops form/service wrappers if needed for the custom UI. No duplicate domain models.

### 5. Secure private technical/evidence access
Add narrow staff-only `/Maneg/` media endpoints only for records the staff actor has the specific review permission to inspect. Preserve PUBLIC preview versus PRIVATE design/source/rights/IP/verification evidence distinctions. Never provide a generic “all private media” browser/download endpoint.

### 6. Real dashboard/system data only
Use database counts for actual pending review/exception states. Empty querysets render polished Empty States. Security/system page reports only observed/configured facts; DB/Redis checks may be live and bounded. No GMV, revenue, rankings, traffic, uptime, backup state, security score, fake alerts or fake integration health.

### 7. Testing and browser artifact
Add dedicated acceptance coverage for authentication/MFA/permissions/privacy/mutations/audit/localization/theme/SEO plus all areas A–P in the master brief. Add connected real-Chrome journeys A–L and exactly 17 required screenshots under `artifacts/maneg-browser-qa`; update CI to upload `maneg-control-center-browser-qa` independently while preserving the three accepted artifact families.

## Explicit non-goals / locked architectures

This checkpoint will not redesign or duplicate:
- Commerce parent purchase/cart/checkout architecture;
- Public/Customer web;
- Artwork Marketplace or Visual Studio persistence/validation;
- Designer Portal;
- Manufacturer Portal;
- Manufacturer production routing;
- canonical FulfillmentRecord/shipment flow;
- finance ledger/accounting domain;
- API v1 customer contract;
- Flutter.

A change to an accepted domain is permitted only if a genuine regression is discovered and documented.

## Audit decision

**Proceed with additive `/Maneg/` Control Center productization on top of the existing OTP-required FABINZI AdminSite.** No backend rewrite is justified. Announcement and Maintenance models already exist. The major work is a coherent, permission-scoped, audited, bilingual/responsive internal operations interface plus focused staff wrappers, secure evidence access, acceptance/browser tests and artifact QA.