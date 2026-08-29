from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Safely reconcile a complete pre-existing schema with Django migration history."

    def handle(self, *args, **options):
        existing_tables = set(connection.introspection.table_names())
        recorder = MigrationRecorder(connection)
        recorder_table = recorder.Migration._meta.db_table

        if recorder_table not in existing_tables:
            if self._baseline_complete_schema(existing_tables, recorder):
                return
            self.stdout.write(
                "django_migrations does not exist and no complete FABINZI schema was detected; normal migrate will initialize the database."
            )
            return

        self._reconcile_notifications_0002(recorder, existing_tables)

    def _managed_model_tables(self):
        tables = set()
        for model in django_apps.get_models(include_auto_created=True):
            opts = model._meta
            if opts.proxy or opts.swapped or not opts.managed:
                continue
            tables.add(opts.db_table)
        return tables

    def _baseline_complete_schema(self, existing_tables, recorder):
        required_tables = self._managed_model_tables()
        present_required = required_tables & existing_tables

        if not present_required:
            return False

        missing = required_tables - existing_tables
        if missing:
            sample = ", ".join(sorted(missing)[:12])
            raise RuntimeError(
                "Database contains FABINZI tables but has no django_migrations history, and the schema is incomplete. "
                "Refusing to baseline migration history automatically. "
                f"Missing {len(missing)} managed table(s), including: {sample}."
            )

        recorder.ensure_schema()
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        nodes = set()
        for leaf in loader.graph.leaf_nodes():
            nodes.update(loader.graph.forwards_plan(leaf))

        for app_label, migration_name in sorted(nodes):
            recorder.record_applied(app_label, migration_name)

        self.stdout.write(
            self.style.WARNING(
                "Detected a complete existing FABINZI schema with no django_migrations table. "
                f"Created the migration recorder and baselined {len(nodes)} migration(s) without altering application tables."
            )
        )
        return True

    def _reconcile_notifications_0002(self, recorder, existing_tables):
        app = "notifications"
        migration = "0002_preferences_and_delivery"
        parent = "0001_initial"
        expected_tables = {
            "notifications_notificationpreference",
            "notifications_notificationdelivery",
        }

        if recorder.migration_qs.filter(app=app, name=migration).exists():
            self.stdout.write(f"{app}.{migration} already recorded; no reconciliation needed.")
            return

        present = expected_tables & existing_tables
        if not present:
            self.stdout.write(
                f"{app}.{migration} is not recorded and its tables do not exist; normal migrate will apply it."
            )
            return

        if present != expected_tables:
            missing = ", ".join(sorted(expected_tables - present))
            existing = ", ".join(sorted(present))
            raise RuntimeError(
                "Refusing to fake a partially present notifications schema. "
                f"Existing: {existing or 'none'}; missing: {missing or 'none'}."
            )

        if not recorder.migration_qs.filter(app=app, name=parent).exists():
            raise RuntimeError(
                f"{app}.{migration} tables exist but parent migration {app}.{parent} is not recorded. "
                "Refusing to create inconsistent migration history."
            )

        recorder.record_applied(app, migration)
        self.stdout.write(
            self.style.WARNING(
                f"Recorded {app}.{migration} as applied because all expected tables already exist."
            )
        )
