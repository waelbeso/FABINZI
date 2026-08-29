# FABINZI Backup & Recovery

This document separates **repository architecture**, **hosting-provider capability**, and **operationally verified state**. A production release must not claim that a backup or restore has succeeded unless an operator has actually verified it.

## Systems of record

- PostgreSQL is the durable transactional system of record for accounts, organizations, catalog, Commerce, production, fulfillment, finance, notifications, integration metadata and audit records.
- Redis/Render Key Value is Celery transport/result infrastructure, not the durable business system of record.
- Production private uploaded media uses the configured Amazon S3 integration. Application-disk storage is not an accepted production private-media recovery strategy.
- `DJANGO_SECRET_KEY` and `INTEGRATION_ENCRYPTION_KEY` are independent deployment secrets. A database backup cannot recover a lost integration encryption key.

## Render PostgreSQL capability

`render.yaml` declares a paid `basic-256mb` Render PostgreSQL instance. Current Render documentation states that paid Render PostgreSQL instances receive continuous point-in-time recovery (PITR). The available recovery window depends on the Render workspace plan (currently documented as 3 days for Hobby and 7 days for Pro or higher). Render also supports on-demand logical exports and currently retains those exports for seven days.

**Not verified by this repository:**

- the FABINZI Render workspace plan,
- the exact recovery window visible in the account,
- whether an on-demand logical export has been created,
- whether an off-platform backup exists,
- whether a restore drill has been completed,
- any measured RPO or RTO.

These are account-owner operational checks, not facts that source code can prove.

## Launch requirements for the operator

Before a production go-live decision, the account owner should:

1. Open the Render database Recovery page and record the actual PITR recovery window available to the FABINZI database.
2. Create a logical export or establish an approved off-platform `pg_dump` process for longer retention if required by the operating policy.
3. Store independent copies of deployment secrets in an approved secret manager/password vault.
4. Confirm S3 bucket recovery controls appropriate to the private-media policy, such as versioning/lifecycle settings where the chosen S3 account supports them.
5. Perform and document a restore drill into an isolated recovery database before relying on any stated RPO/RTO.

## Recovery runbook

1. Stop or isolate write traffic if recovery is required.
2. Restore PostgreSQL using Render PITR to a new instance or restore a verified logical export into a clean database.
3. Validate the recovered database before cutover; do not overwrite the only known-good source while validating recovery.
4. Restore deployment secrets from the independent secret store.
5. Configure the recovered application with the recovered database and existing durable private-media provider.
6. Run migration reconciliation, `migrate`, `check`, and production `check --deploy` against the recovered environment.
7. Validate authentication, `/healthz/`, `/readyz/`, private-media authorization, a representative purchase/order chain, finance consistency, and `/Maneg/` access.
8. Start Celery worker/Beat only after transactional integrity is confirmed.
9. Record the recovery timestamp, source restore point, validation evidence, cutover decision, and measured recovery duration.

## Migration rollback

FABINZI does not claim that every Django migration is safely reversible. The preferred launch rollback is application rollback to a known compatible source revision plus database recovery when a schema/data migration is not safely reversible. Before a migration with destructive data implications, create/verify a recoverable database point and document the migration-specific rollback plan.
