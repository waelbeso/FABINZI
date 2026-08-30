# FABINZI WEB v1.0 — Deployment & Rollback Contract

No production deployment occurs in this checkpoint.

## Repository-defined production topology

`render.yaml` defines `fabinzi-web`, paid `fabinzi-db`, Redis-compatible `fabinzi-redis`, `fabinzi-worker` and `fabinzi-beat`. Production services track `main`; the release-preparation branch and Draft PR #9 are not production revisions.

Web startup through `render-start.sh` is:

1. `python manage.py reconcile_migration_state`
2. `python manage.py migrate --noinput`
3. `python manage.py collectstatic --noinput`
4. Gunicorn startup.

No demo seed or provider connection test runs automatically.

## Future deployment contract

A later explicit release action must identify one accepted Git SHA, confirm GREEN CI, verify environment values, establish a recoverable database point, verify production S3 before private writes, deploy through the approved `main`/Render process, verify `/readyz/`, prove `/healthz/` reports the intended source commit, then perform non-destructive smoke checks and only the provider/worker checks actually required for the enabled release.

## Rollback

- Application-only regression: roll back to a known schema-compatible source revision.
- Migration/data incompatibility: source rollback alone is insufficient; use the database recovery runbook in `docs/BACKUP_AND_RECOVERY.md`.
- Do not overwrite the only known-good database while validating recovery.
- Keep `INTEGRATION_ENCRYPTION_KEY` and other deployment secrets independently recoverable; a database restore cannot reconstruct a lost encryption key.
- Validate authentication, readiness, private-media authorization, representative Commerce state, finance consistency and `/Maneg/` before cutover.

This checkpoint does not claim that a rollback or restore drill has been executed.
