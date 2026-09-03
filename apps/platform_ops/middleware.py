import logging

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.db import DatabaseError
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.translation import activate

from .maneg_access import mfa_configured
from .models import MaintenanceWindow
from .seo import INDEXABLE_URL_NAMES

logger = logging.getLogger(__name__)


class PublicLocaleMiddleware:
    """Allow stable crawlable language alternates via ?lang=en|ar without mutating user preferences."""

    SUPPORTED = {"en", "ar"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = request.GET.get("lang") if request.method in {"GET", "HEAD"} else None
        if language in self.SUPPORTED:
            activate(language)
            request.LANGUAGE_CODE = language
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/super/") and request.user.is_authenticated:
            if not request.user.is_active or not request.user.is_staff or not request.user.is_superuser:
                return HttpResponseForbidden("Stock Django Admin is restricted to the FABINZI Platform Owner/superuser.")
            if mfa_configured(request.user):
                verified = getattr(request.user, "is_verified", None)
                if not callable(verified) or not verified():
                    return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        match = getattr(request, "resolver_match", None)
        if not match or match.url_name not in INDEXABLE_URL_NAMES:
            response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
        if request.path.startswith(("/Maneg/", "/super/")):
            response.headers.setdefault("Cache-Control", "private, no-store")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class MaintenanceModeMiddleware:
    SAFE_PREFIXES = ("/Maneg/", "/super/", "/healthz/", "/readyz/", "/static/", "/account/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.SAFE_PREFIXES):
            return self.get_response(request)

        try:
            window = MaintenanceWindow.current()
        except DatabaseError:
            logger.exception("Maintenance mode lookup failed; continuing without maintenance restriction")
            window = None

        if window and window.mode == MaintenanceWindow.Mode.RESTRICT:
            return render(request, "platform_ops/maintenance.html", {"maintenance": window}, status=503)
        return self.get_response(request)
