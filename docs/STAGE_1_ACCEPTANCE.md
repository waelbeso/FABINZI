# Stage 1 — Designer & Manufacturer Onboarding Acceptance

Status: **COMPLETE**

Stage 1 implements the business identity, self-service onboarding, membership/role, verification and staff-review foundation required by the FABINZI master brief. It does not implement Garment Design, Artwork, Manufacturing Offers, commerce, routing or finance.

## Delivered

- Shared `Organization` tenant model with explicit Designer / Manufacturer type.
- Designer-specific and Manufacturer-specific onboarding profiles.
- Self-service `/designer/` and `/manufacturer/` onboarding entry points.
- Draft creation plus editing before submission and after Revision Required.
- Owner membership created atomically with every new business application.
- Tenant-aware business memberships with Designer- and Manufacturer-specific role validation.
- Owner/Manager team-member management API with last-owner protection.
- Draft → Submitted → Revision Required / Approved / Rejected workflow.
- Organization verification state synchronized with review decisions.
- Staff-only review actions inside the branded `/Maneg/` Control Center.
- Verification-document records connected only to private Stage-0 `MediaAsset` objects.
- Authenticated API endpoint for attaching owned private verification assets.
- In-app review result notifications.
- Append-only audit events for application creation, editing, submission, member changes and review decisions.
- DRF v1 endpoints for creating, retrieving, editing and submitting Designer/Manufacturer onboarding.
- DRF v1 team membership endpoints.
- Server-side access checks and tenant-isolation utilities.
- Automated tests for creation, editing, required manufacturer registration, submission, review, notification, audit, staff authorization, tenant isolation, team membership, last-owner protection, private verification documents, web onboarding and API authentication.

## Acceptance gate

Stage 1 is complete because:

1. A signed-in user can create a Designer onboarding draft.
2. A signed-in user can create a Manufacturer onboarding draft.
3. The creator becomes the business Owner membership.
4. Draft and Revision Required applications can be edited and resubmitted.
5. Manufacturer submission refuses an application without commercial registration.
6. Terms acceptance is required before submission.
7. Submission moves the application to `Submitted` and the organization to `Pending verification`.
8. Only staff can approve, reject or request revision.
9. Approval activates the organization.
10. Rejection marks the organization rejected.
11. Revision Required returns the organization to draft verification state and increments revision count.
12. Owners/Managers can manage tenant members using valid roles.
13. The last active owner cannot be removed.
14. Material workflow and membership actions create audit records.
15. Review decisions generate in-app notifications.
16. A user outside the business cannot pass tenant access checks.
17. Verification documents must reference private media and cannot attach another user's private asset.
18. API onboarding and membership endpoints require authentication.

## Deliberately deferred by the master roadmap

- Detailed Manufacturer capabilities and opportunity eligibility: Stage 4.
- Garment Designs and technical packages: Stage 2.
- Artwork and Designed Products: Stage 3.
- Payment and payout execution: Stages 6 and 8.

Stage 1 does not invent a separate invitation service because the master specification defines team roles but does not mandate email invitation semantics. The membership boundary required by later stages is fully implemented and tenant-aware.
