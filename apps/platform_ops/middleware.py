from django.shortcuts import render
from .models import MaintenanceWindow

class MaintenanceModeMiddleware:
    SAFE_PREFIXES = ("/Maneg/", "/healthz/", "/static/", "/account/")
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.path.startswith(self.SAFE_PREFIXES):
            return self.get_response(request)
        window = MaintenanceWindow.current()
        if window and window.mode == MaintenanceWindow.Mode.RESTRICT:
            return render(request, "platform_ops/maintenance.html", {"maintenance": window}, status=503)
        return self.get_response(request)
