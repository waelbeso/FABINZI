# FABINZI Backup & Disaster-Recovery Baseline

Production must not rely on application-disk persistence.

## PostgreSQL

- Automated provider/database backups at least daily at initial production stage.
- Target initial RPO: 24 hours; tighten before material transaction volume.
- Target initial RTO: 4 hours; validate against hosting capability before launch.
- Retain at least 14 daily restore points and 3 monthly restore points at initial production stage.
- Keep backups outside the primary application instance.
- Perform a documented restore exercise at least quarterly and before major infrastructure changes.

## Object storage

- S3 critical/private production objects should use bucket versioning where supported and an explicit retention lifecycle.
- Application MediaAsset metadata is part of the PostgreSQL backup and is required to reconstruct provider references.
- Cloudflare Images asset identifiers and transformation metadata must remain represented in the application database/export process.

## Secrets and encryption material

- `DJANGO_SECRET_KEY` and `INTEGRATION_ENCRYPTION_KEY` are deployment secrets and must be backed up in an external secret manager/password vault controlled by FABINZI operations.
- Losing the integration encryption key may make provider credentials unrecoverable; database backup alone is insufficient.

## Restore runbook

1. Provision clean application, PostgreSQL and Redis infrastructure.
2. Restore PostgreSQL from the selected tested restore point.
3. Restore deployment secrets independently.
4. Validate migrations and `manage.py check`.
5. Validate S3/Cloudflare provider references using `/Maneg/` Test Connection.
6. Start Celery workers only after transactional DB integrity is confirmed.
7. Run smoke tests on authentication, `/healthz/`, private-media authorization and Control Center access.
8. Record the exercise and measured RPO/RTO.
