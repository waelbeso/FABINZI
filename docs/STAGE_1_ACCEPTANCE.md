# Stage 1 — Designer & Manufacturer Onboarding Acceptance

Status: **IMPLEMENTED**

Stage 1 builds only the business identity, self-service onboarding, membership/role, verification and staff-review foundation required by the FABINZI master brief. It does not implement Garment Design, Artwork, Manufacturing Offers, commerce, routing or finance.

## Delivered

- Shared `Organization` tenant model with explicit Designer / Manufacturer type.
- Designer-specific and Manufacturer-specific onboarding profiles.
- Self-service `/designer/` and `/manufacturer/` onboarding entry points.
- Owner membership created atomically with every new business application.
- Tenant-aware business memberships and role validation.
- Draft → Submitted → Revision Required / Approved / Rejected workflow.
- Organization verification state synchronized with review decisions.
- Staff-only review actions inside the branded `/Maneg/` Control Center.
- Verification-document records connected to private Stage-0 `MediaAsset` objects.
- In-app review result notifications.
- Append-only audit events for application creation, submission and decisions.
- DRF v1 endpoints for creating, retrieving and submitting Designer/Manufacturer onboarding.
- Server-side access checks and tenant-isolation utilities.
- Automated tests for creation, required manufacturer registration, submission, review, notification, audit, staff authorization, tenant isolation, web onboarding and API authentication.

## Acceptance gate

Stage 1 is accepted when:

1. A signed-in user can create a Designer onboarding draft.
2. A signed-in user can create a Manufacturer onboarding draft.
3. The creator becomes the business Owner membership.
4. Manufacturer submission refuses an application without commercial registration.
5. Terms acceptance is required before submission.
6. Submission moves the application to `Submitted` and the organization to `Pending verification`.
7. Only staff can approve, reject or request revision.
8. Approval activates the organization.
9. Rejection marks the organization rejected.
10. Revision Required returns the organization to draft verification state and increments revision count.
11. Material workflow actions create audit records.
12. Review decisions generate in-app notifications.
13. A user outside the business cannot pass tenant access checks.
14. Verification documents must reference private media.
15. API onboarding endpoints require authentication.

## Deliberately deferred

- Detailed Manufacturer capabilities and opportunity eligibility: Stage 4.
- Garment Designs and technical packages: Stage 2.
- Artwork and Designed Products: Stage 3.
- Payment and payout execution: Stages 6 and 8.
- Full invitation lifecycle for adding team members: not required by the Stage 1 acceptance gate; the tenant-aware Membership model and admin management foundation are present.
