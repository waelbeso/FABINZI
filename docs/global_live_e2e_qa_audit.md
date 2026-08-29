# FABINZI — Global Live E2E QA Audit

## Checkpoint bootstrap

This checkpoint starts from the exact integrated Web product SHA:

`3330a0c13711335f8e8a1f281e63ff1e17311a24`

Source branch: `feature/web-productization`.

Work branch: `work/global-live-e2e-qa`.

This file is intentionally documentation-only. No product behavior, architecture, deployment settings, security controls, integrations, or accepted domain contracts are changed by this bootstrap commit.

Before any implementation change, the actual QA/demo deployment must be independently audited and the following must be established from repository/deployment evidence rather than historical assumptions:

- canonical QA/demo URL;
- exact deployed branch and commit SHA;
- web, PostgreSQL, Redis, Celery worker, and Celery beat configuration;
- static and private-media behavior;
- allowed hosts, CSRF origins, HTTPS and secure-cookie settings;
- demo seed state;
- configured integration/provider state for payments, notifications, storage, and error reporting;
- exact deployment identity/timestamp where available.

The final Global Live E2E acceptance must prove that the exact accepted repository SHA equals the exact deployed QA SHA, with normal CI GREEN, explicit deployed-browser live E2E GREEN, at least 20 live screenshots, and complete manual visual review.

Status at bootstrap: **LIVE ENVIRONMENT AUDIT PENDING — NO IMPLEMENTATION CHANGES STARTED**.
