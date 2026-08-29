from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Safely reconcile known pre-existing schema objects with Django migration history."

    def handle(self, *args, **options):
        self._reconcile_notifications_0002()

    def _reconcile_notifications_0002(self):
        app = "notifications"
        migration = "0002_preferences_and_delivery"
        expected_tables = {
            "notifications_notificationpreference",
            "notifications_notificationdelivery",
        }

        recorder = MigrationRecorder(connection)
        if recorder.migration_qs.filter(app=app, name=migration).exists():
            self.stdout.write(f"{app}.{migration} already recorded; no reconciliation needed.")
            return

        existing_tables = set(connection.introspection.table_names())
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

        recorder.record_applied(app, migration)
        self.stdout.write(
            self.style.WARNING(
                f"Recorded {app}.{migration} as applied because all expected tables already exist."
            )
        )
