import base64
import os
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Provision the controlled FABINZI demo admin TOTP device for explicit live QA only."

    def handle(self, *args, **options):
        if not settings.FABINZI_DEMO_SEED_ENABLED:
            raise CommandError(
                "Demo QA provisioning is disabled. Set FABINZI_DEMO_SEED_ENABLED=true explicitly before running this command."
            )

        secret = re.sub(r"\s+", "", os.environ.get("DEMO_ADMIN_TOTP_SECRET", "")).upper()
        if not secret:
            raise CommandError("DEMO_ADMIN_TOTP_SECRET is required and must be supplied through protected environment configuration.")
        try:
            padding = "=" * ((8 - len(secret) % 8) % 8)
            key = base64.b32decode(secret + padding, casefold=True)
        except Exception as exc:
            raise CommandError("DEMO_ADMIN_TOTP_SECRET must be a valid base32 TOTP secret.") from exc
        if not 10 <= len(key) <= 40:
            raise CommandError("DEMO_ADMIN_TOTP_SECRET must decode to between 10 and 40 bytes.")

        User = get_user_model()
        try:
            admin = User.objects.get(username="fabinzi_demo_admin", is_staff=True, is_superuser=True, is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError("Controlled demo admin is missing. Run the guarded seed_demo command first.") from exc

        device, created = TOTPDevice.objects.get_or_create(
            user=admin,
            name="global-live-e2e",
            defaults={"confirmed": True, "key": key.hex()},
        )
        device.confirmed = True
        device.key = key.hex()
        device.last_t = -1
        device.drift = 0
        device.save(update_fields=["confirmed", "key", "last_t", "drift"])

        verb = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Controlled demo admin TOTP device {verb}. Secret value was not printed."))
