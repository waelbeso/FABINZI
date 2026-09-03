from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.platform_ops.staff_roles import ROLE_SPECS


class Command(BaseCommand):
    help = "Create/update deterministic FABINZI internal staff groups without assigning any users."

    @transaction.atomic
    def handle(self, *args, **options):
        for role_name, spec in ROLE_SPECS.items():
            permissions = Permission.objects.filter(
                content_type__app_label__in=spec["view_apps"],
                codename__startswith="view_",
            )
            selected = {permission.pk: permission for permission in permissions}

            missing = []
            for natural in spec["extra_permissions"]:
                app_label, codename = natural.split(".", 1)
                permission = Permission.objects.filter(
                    content_type__app_label=app_label,
                    codename=codename,
                ).first()
                if permission is None:
                    missing.append(natural)
                else:
                    selected[permission.pk] = permission

            if missing:
                raise CommandError(
                    f"Cannot bootstrap {role_name}; missing permissions: {', '.join(sorted(missing))}"
                )

            # Integrations are intentionally not assignable to any normal staff role.
            if any(permission.content_type.app_label == "integrations" for permission in selected.values()):
                raise CommandError(f"Unsafe integrations permission resolved for {role_name}.")

            group, created = Group.objects.get_or_create(name=role_name)
            group.permissions.set(selected.values())
            self.stdout.write(
                f"{'CREATED' if created else 'UPDATED'} {role_name}: {len(selected)} permissions"
            )

        self.stdout.write(self.style.SUCCESS("FABINZI internal staff roles bootstrapped; no users were assigned."))
