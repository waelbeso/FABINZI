import logging

from django.db import DatabaseError

from apps.accounts.guest_identity import ensure_guest_identity
from apps.organizations.models import Organization
from .models import MaintenanceWindow, PlatformAnnouncement
from .seo import seo_context

logger = logging.getLogger(__name__)


def _audiences_for(request):
    audiences = {"all"}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        if user.is_staff:
            audiences.add("staff")
        try:
            audiences.update(
                user.groups.filter(
                    name__in=["customers", "designers", "manufacturers"]
                ).values_list("name", flat=True)
            )
        except DatabaseError:
            logger.exception("Audience lookup failed; using safe default audience")
    else:
        audiences.add("customers")
    return audiences


def _shell_identity(request):
    user = getattr(request, "user", None)
    identity = {
        "authenticated": bool(user and user.is_authenticated),
        "designer": False,
        "manufacturer": False,
        "staff": bool(user and user.is_authenticated and user.is_staff),
        "superuser": bool(user and user.is_authenticated and user.is_superuser),
        "guest": False,
    }
    if not identity["authenticated"]:
        if not request.path.startswith(("/Maneg/", "/api/", "/healthz/", "/readyz/")):
            ensure_guest_identity(request)
            identity["guest"] = True
        return identity

    try:
        kinds = set(
            user.business_memberships.filter(
                is_active=True,
                organization__verification_status=Organization.VerificationStatus.ACTIVE,
            ).values_list("organization__kind", flat=True)
        )
        identity["designer"] = Organization.Kind.DESIGNER in kinds
        identity["manufacturer"] = Organization.Kind.MANUFACTURER in kinds
    except DatabaseError:
        logger.exception("Role-aware shell lookup failed; rendering minimum account navigation")
    return identity


def active_announcements(request):
    shell_identity = _shell_identity(request)
    try:
        announcements = PlatformAnnouncement.active().filter(
            audience__in=_audiences_for(request)
        )
        maintenance = MaintenanceWindow.current()
        return {
            "platform_announcements": announcements,
            "maintenance_warning": (
                maintenance
                if maintenance and maintenance.mode == MaintenanceWindow.Mode.BANNER_ONLY
                else None
            ),
            "fabinzi_identity": shell_identity,
        }
    except DatabaseError:
        logger.exception("Platform announcement lookup failed; rendering without operational banners")
        return {
            "platform_announcements": (),
            "maintenance_warning": None,
            "fabinzi_identity": shell_identity,
        }


__all__ = ["active_announcements", "seo_context"]
