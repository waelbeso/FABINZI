import logging

from django.db import DatabaseError
from django.shortcuts import render

from .models import MaintenanceWindow

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response


class MaintenanceModeMiddleware:
    SAFE_PREFIXES = ("/Maneg/", "/healthz/", "/readyz/", "/static/", "/account/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.SAFE_PREFIXES):
            return self.get_response(request)

        try:
            window = MaintenanceWindow.current()
        except DatabaseError:
            # Maintenance mode is operational metadata, not a dependency that
            # should take the public site down if the database is starting,
            # briefly unavailable, or migrations are still settling.
            logger.exception("Maintenance mode lookup failed; continuing without maintenance restriction")
            window = None

        if window and window.mode == MaintenanceWindow.Mode.RESTRICT:
            return render(request, "platform_ops/maintenance.html", {"maintenance": window}, status=503)
        return self.get_response(request)
