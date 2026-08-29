import logging

from django.db import DatabaseError

from .models import MaintenanceWindow, PlatformAnnouncement

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


def active_announcements(request):
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
        }
    except DatabaseError:
        # Announcements and banners are optional presentation data. They must
        # never turn otherwise healthy pages into a 500 response.
        logger.exception("Platform announcement lookup failed; rendering without operational banners")
        return {"platform_announcements": (), "maintenance_warning": None}
