# FABINZI WEB v1.0 — Migration Baseline

The WEB v1.0 release freeze introduces **no new Django migration** relative to integration base `802dc0f091287f778d4e623caa375a32c67f97dc`.

The authoritative local migration list is machine-readable in `release-manifest.json` and contains:

- `apps/accounts/migrations/0001_initial.py`
- `apps/accounts/migrations/0002_alter_user_is_active.py`
- `apps/artwork/migrations/0001_initial.py`
- `apps/audit/migrations/0001_initial.py`
- `apps/checkout/migrations/0001_initial.py`
- `apps/checkout/migrations/0002_commerce_parent_cart.py`
- `apps/design/migrations/0001_initial.py`
- `apps/finance/migrations/0001_initial.py`
- `apps/integrations/migrations/0001_initial.py`
- `apps/integrations/migrations/0002_seed_providers.py`
- `apps/manufacturer_marketplace/migrations/0001_initial.py`
- `apps/media/migrations/0001_initial.py`
- `apps/media/migrations/0002_rename_media_asset_index.py`
- `apps/notifications/migrations/0001_initial.py`
- `apps/notifications/migrations/0002_preferences_and_delivery.py`
- `apps/operations/migrations/0001_initial.py`
- `apps/organizations/migrations/0001_initial.py`
- `apps/organizations/migrations/0002_align_index_names.py`
- `apps/platform_ops/migrations/0001_initial.py`
- `apps/storefront/migrations/0001_initial.py`
- `apps/storefront/migrations/0002_visual_studio_elements.py`

Accepted PLG CI #342 also applied Django/framework migrations for `admin`, `auth`, `contenttypes`, `otp_static`, `otp_totp`, `sessions`, `sites` and `two_factor` successfully on a fresh PostgreSQL database.

Final Release Candidate CI must again pass `makemigrations --check --dry-run`, migration reconciliation and fresh `migrate --noinput`. The CI also fails if release-preparation changes modify local migration files relative to the integration base.

Rollback must not assume every migration is reversible. If a later release introduces destructive schema/data changes, the migration-specific recovery plan must be defined before deployment.
