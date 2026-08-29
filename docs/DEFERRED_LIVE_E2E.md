# FABINZI Deferred Global Live E2E Register

Status: **UNRESOLVED — intentionally deferred until the planned post-Flutter return.**

This document is a durable acceptance-control register. The Global Live E2E QA checkpoint was passed forward as a program decision because its remaining blocker was external QA provisioning/configuration, not a source-code product regression. Passing it forward did **not** convert any item below to PASS.

## Original checkpoint evidence

- Repository: `waelbeso/FABINZI`
- Checkpoint: `FABINZI — Global Live E2E QA`
- Original working branch: `work/global-live-e2e-qa`
- Original final source SHA: `4adf44afbf777bacdf8377f1bb65d6522ce36ac7`
- Original PR: `#7`
- Original PR target: `feature/web-productization`
- Original base SHA: `3330a0c13711335f8e8a1f281e63ff1e17311a24`
- Original normal CI: `#309`
- Original Run ID: `33278567789`
- Original result: **232 passed / 0 failed**
- Existing warning: one non-blocking Django deprecation warning
- Failure class: **A — QA environment/configuration failure**

## Deferred reason

The repository-side QA architecture, deployment identity surface, guarded demo seeding, Admin OTP provisioning command, live-environment audit and remote Chrome harness existed and normal source regressions were GREEN. The isolated non-production Render QA environment was not provisioned/running, and the required protected QA identities, Admin TOTP and QA private-storage configuration were unavailable. No product regression was established from that blocker.

## Deferred live-validation gates

All items below remain unresolved:

- [ ] isolated QA stack provisioning
- [ ] exact deployed QA SHA proof
- [ ] protected QA identities
- [ ] protected Admin TOTP
- [ ] QA private S3 configuration
- [ ] actual remote Chrome Global Live E2E execution
- [ ] Customer live lifecycle proof
- [ ] Designer live lifecycle proof
- [ ] Manufacturer live lifecycle proof
- [ ] `/Maneg/` live lifecycle proof
- [ ] Commerce parent/child live proof
- [ ] Production/QC/Fulfillment live proof
- [ ] tenant/RBAC live isolation
- [ ] private-media live isolation
- [ ] payment safety live validation
- [ ] Celery/async live validation
- [ ] EN/LTR live validation
- [ ] AR/RTL live validation
- [ ] Light/Dark/System live validation
- [ ] responsive live validation
- [ ] required 20-shot live artifact
- [ ] manual review of all 20 live screenshots

## Required post-Flutter return plan

The planned return must:

1. Provision an isolated QA stack.
2. Deploy the exact then-current integrated Web/API/Flutter-backend-compatible SHA.
3. Configure protected QA identities.
4. Configure isolated QA private S3 storage.
5. Run the guarded QA seed.
6. Provision Admin OTP through the protected environment path.
7. Run the live-environment audit and prove the deployed SHA.
8. Run the actual remote Chrome Global Live E2E lifecycle.
9. Generate the required 20 live screenshots.
10. Manually inspect all 20 screenshots.
11. Validate Customer lifecycle.
12. Validate Designer lifecycle.
13. Validate Manufacturer lifecycle.
14. Validate `/Maneg/` lifecycle.
15. Validate Commerce parent/child persistence and visibility.
16. Validate ProductionJob/QC/packing/FulfillmentRecord/tracking lifecycle.
17. Validate tenant/RBAC isolation.
18. Validate private-media isolation.
19. Validate payment safety for whichever providers are actually enabled.
20. Validate Celery/async behavior that is actually required and configured.
21. Validate EN/LTR, AR/RTL, Light/Dark/System and responsive behavior.
22. Formally close this deferred gate only after all required live evidence is complete.

## Closure rule

Do not mark this file resolved, delete the checklist, or rewrite the historical evidence merely because later repository-side checkpoints pass. It may be closed only by a future checkpoint that actually completes the deferred live validation and records the exact deployed environment, exact repository SHA, live workflow evidence, screenshot artifact and manual visual review.
