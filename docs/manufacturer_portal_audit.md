# FABINZI Manufacturer Portal — Repo-First Audit

Base / integration SHA: `cdf08d5aa625d9b1b13fe5502ec0475bcd93180c`

This audit precedes Manufacturer Portal implementation and treats the repository as the source of truth. It intentionally does not reopen the accepted Commerce, Public/Customer, Artwork/Studio or Designer architecture.

## Locked business boundary

Manufacturer is an operational production partner. The authenticated Manufacturer workspace must not create or manage `Storefront`, `StoreProduct`, customer retail pricing, public catalog products, or Designer Artwork publication. Printing and embroidery remain Manufacturer capabilities. Public Manufacturer marketplace publication remains separate from the authenticated production workspace.

## Evidence-based capability map

| Requested capability | Current repository evidence | Classification | Implementation direction |
| --- | --- | --- | --- |
| Manufacturer organization / onboarding | `Organization(kind=manufacturer)`, `ManufacturerProfile`, `OnboardingApplication`, verification states and audited submit/review services | Already implemented and productizable | Reuse real states; build dedicated Manufacturer access/onboarding UI without bypassing verification |
| Multi-organization tenant context | Manufacturer views currently select first/all memberships; accepted Designer portal has session-backed tenant resolution | Partially implemented | Add Manufacturer-specific active-org context with safe foreign-org fallback |
| Profile | Real Organization + ManufacturerProfile fields exist; live Manufacturer profile allowlist does not | Partially implemented | Add audited active-profile service with a safe non-sensitive allowlist; keep legal/verification-sensitive fields locked outside onboarding/review flow |
| Team / RBAC | Shared Membership roles include Owner, Manager, Production Manager, Operator, QC, Accountant; last-owner logic exists; accepted Designer portal has stronger Manager/Owner protection | Partially implemented | Reuse Membership architecture and mirror accepted secure Owner rules; no invitation claims beyond existing-user lookup |
| Capabilities | `ManufacturerListing` + `ManufacturerCapability` with cut/sew, print, embroidery, sampling, pattern, finishing, packaging, other | Already implemented and productizable | Use persisted values only; authenticated capability management must not imply retail catalog ownership |
| Public Manufacturer marketplace | Published `ManufacturerListing`, public API/views and public sitemap entries | Already implemented | Preserve as separate public surface; do not use public listing fields to fabricate private operational metrics |
| Designer sourcing RFQs | `RFQ`, `RFQInvitation`, Designer create/open flow, Manufacturer invitation notifications | Already implemented and productizable | Tenant-scope opportunities to invitations for selected Manufacturer org only |
| Manufacturing quotes | `ManufacturerQuote`, submit service, Designer-owned `ManufacturerSelection`, audit + notifications | Already implemented and productizable | Build Manufacturer quote UI on existing service; never allow self-selection or foreign quote mutation |
| Assigned customer production | `CustomerOrder` child, `OrderItem`, `ProductionJob`, selected Manufacturer assignment service | Already implemented and productizable | Operate at assigned child/job level; hide parent-purchase/payment internals |
| Production workflow | Job states, five persisted milestones, guarded transitions with `select_for_update`, audit events | Already implemented and productizable | Build operational job workspace and legal-action UI around existing services |
| QC | `QCInspection`, QC roles, request/record services, persistent inspection history | Already implemented and productizable | Reuse actual decisions/checklist/notes only; no fabricated quality metrics |
| Packing / readiness | QC pass moves canonical fulfillment to `READY_TO_PACK`; `pack_order` moves to `PACKED` | Already implemented and productizable | Present actual state labels; `PACKED` is the real shipment-ready state, not a new model |
| Shipment / tracking | Canonical `FulfillmentRecord` carries carrier/tracking URL/number and shipment time; `ship_order` validates and notifies customer | Already implemented and productizable | Use same record; no second shipment system and no carrier integration claims |
| Finance / settlements | FinanceAccount, immutable-style ledger, OrderFinance manufacturer payable, PayoutProfile, SettlementRequest, real balance computation | Already implemented and productizable | Add Manufacturer-org-filtered finance UI; preserve Owner/Manager/Accountant role restriction and masked payout destination |
| Notifications | Bilingual in-app Notification plus optional user preferences/delivery records | Already implemented and productizable | Use in-app notification center; do not claim email/SMS delivery unless configured |
| Private storage | PRIVATE MediaAsset, local-test/S3 production mode, fail-closed S3 configuration, private/no-store responses | Already implemented foundation | Add exact job-scoped Manufacturer production-media authorization surface |
| Designer technical files | Garment `DesignAsset` includes PATTERN / TECH_PACK / 3D / TECHNICAL; private storage enforced for non-product-image assets | API/domain only for Manufacturer | Allow only production-required assets for the assigned job’s exact garment version; never generic Designer browsing |
| Artwork production source | `ArtworkAsset.SOURCE` is private; `RIGHTS_EVIDENCE` is separately typed | API/domain only for Manufacturer | Assigned-job route may allow exact SOURCE for job’s artwork version; explicitly deny Rights Evidence and IP evidence |
| Customer Studio private media | `CustomizationElement.IMAGE` requires protected customer-private upload and project ownership | API/domain only for Manufacturer | Allow only exact image elements belonging to the assigned OrderItem StudioProject; preserve transform coordinates without RTL mirroring |
| Existing Manufacturer Web | `/manufacturer/`, `/manufacturer/marketplace/`, `/manufacturer/production/`, `/manufacturer/finance/` are thin/generic views | Web UI missing | Replace/extend with dedicated production-quality Manufacturer workspace |
| Manufacturer SEO/privacy | robots.txt already disallows `/manufacturer/`; private sitemap contains only public manufacturer marketplace | Partially implemented | Add noindex/nofollow/noarchive meta/headers to all authenticated Manufacturer routes |
| Manufacturer acceptance/browser suite | Stage 4/7/8 backend tests exist; no Manufacturer Portal acceptance/browser suite or artifact | Web QA missing | Add comprehensive acceptance/security tests, Chrome A–H journeys and dedicated 17-screenshot artifact |

## Security gaps to close

1. Manufacturer Web views do not currently have an active tenant selector/context comparable to the accepted Designer workspace.
2. The legacy Manufacturer invitations read API checks membership existence but not the stronger quote role/active Manufacturer context used by service mutations.
3. Generic Manufacturer finance Web aliases the cross-organization finance dashboard and can mix multiple organization kinds for a multi-role user; Manufacturer finance must be scoped to the selected Manufacturer tenant.
4. Current Manufacturer team flow is not productized. The shared legacy member service allows Manager-level calls that are weaker than the secure Owner rules already used by Designer. Manufacturer Web mutations will enforce the accepted secure Owner protections.
5. There is no Manufacturer job-scoped private production asset serving route. Existing Studio and Designer private routes correctly deny generic Manufacturer access and must remain unchanged.
6. Manufacturer production list currently aggregates all Manufacturer memberships instead of one resolved active tenant.
7. Current Manufacturer pages are minimal, largely English-only, and lack the checkpoint’s responsive/RTL/theme/SEO product requirements.

## Private production media rule

Manufacturer private-media authorization will be relationship based, not raw MediaAsset ownership based. A request must resolve an assigned `ProductionJob`, verify the selected Manufacturer tenant and authorized role, and then prove the requested asset is one of the following for that exact job:

- a `ProductionAsset` explicitly attached to the job;
- a production-required private `DesignAsset` tied to the job’s exact garment version (e.g. pattern/tech pack/technical/actual 3D only if present);
- an `ArtworkAsset.SOURCE` tied to the job’s exact artwork version;
- a customer-private Studio image element tied to the job’s exact `OrderItem.studio_project`.

The gate will deny Artwork `RIGHTS_EVIDENCE`, IP declarations/cases/evidence, verification documents, unrelated Designer files, unrelated Studio uploads, and assets belonging to another job/manufacturer. Storage remains fail-closed and responses retain private/no-store/noindex protections.

## PII rule

Manufacturer job pages will use operational references (`CustomerOrder.number`, item title/SKU, size/color/quantity/customization/production definitions) and will not expose payment data, customer account settings, unrelated orders, or parent purchase internals. Shipping identity/address will only be exposed if/where required for fulfillment and will come from the assigned order’s persisted shipping snapshot; it will not be shown on unrelated production surfaces.

## Backend extensions expected

No new marketplace, catalog, shipment or finance model is currently justified. The expected additive extensions are service/view authorization layers rather than new domain models:

- Manufacturer tenant context;
- live Manufacturer profile safe-update service;
- secure Manufacturer team mutations using existing Membership roles;
- capability update/deactivate service around existing ManufacturerCapability if needed by UI;
- job-scoped production-media authorization/serving;
- Manufacturer-specific server-rendered workflow views and forms;
- targeted API hardening where read/mutation parity requires it;
- acceptance/browser tests and CI artifact wiring.

A migration will only be added if a later implementation finding proves a required business state cannot be represented by the existing models.

## Implementation sequence

1. Establish Manufacturer tenant context and shared Manufacturer workspace shell/access states.
2. Productize Profile, Team and Capabilities using authoritative service-layer mutations.
3. Productize RFQ Opportunities and Manufacturer Quotes without changing Designer selection ownership.
4. Productize assigned Production list/detail, milestones and exact private production assets.
5. Productize QC, packing/real readiness state, shipment/tracking on canonical FulfillmentRecord.
6. Productize Manufacturer-only Finance/Settlements and in-app Notifications surfaces.
7. Enforce SEO/privacy, PII minimization, Web/API tenant parity, CSRF and server validation.
8. Add Manufacturer acceptance/security tests.
9. Add connected Selenium A–H journeys and all 17 required screenshots.
10. Extend CI with independent `manufacturer-portal-browser-qa` upload while preserving existing browser artifacts.
11. Run exact-SHA CI, download final artifact, manually inspect all 17 screenshots, fix any defects and rerun until fully green.

## Preserved accepted architecture

This checkpoint will not redesign Commerce checkout/parent purchase, public/customer Web, Artwork Marketplace, Visual Studio, Designer Portal, Storefront ownership, or Designer Artwork publication unless an actual regression proves a narrow compatibility fix is necessary.
