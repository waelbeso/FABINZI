from .models import MaintenanceWindow, PlatformAnnouncement

def _audiences_for(request):
    audiences = {"all"}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        if user.is_staff:
            audiences.add("staff")
        audiences.update(user.groups.filter(name__in=["customers", "designers", "manufacturers"]).values_list("name", flat=True))
    else:
        audiences.add("customers")
    return audiences

def active_announcements(request):
    announcements = PlatformAnnouncement.active().filter(audience__in=_audiences_for(request))
    maintenance = MaintenanceWindow.current()
    return {"platform_announcements": announcements, "maintenance_warning": maintenance if maintenance and maintenance.mode == MaintenanceWindow.Mode.BANNER_ONLY else None}
