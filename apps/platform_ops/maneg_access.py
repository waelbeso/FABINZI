from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice


def mfa_configured(user):
    if not user or not user.is_authenticated:
        return False
    return (
        TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        or StaticDevice.objects.filter(user=user).exists()
    )


def _private_headers(response):
    response.headers.setdefault("Cache-Control", "private, no-store")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    # Keep ordinary Control Center form submissions genuinely same-origin so
    # Django's CSRF Origin validation remains authoritative. Private media
    # responses retain their stricter no-referrer policy in media services.
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def maneg_staff_required(view):
    """Protect the productized Control Center without coupling it to AdminSite.

    Existing configured MFA remains mandatory. A staff user with no confirmed
    device is allowed to reach /Maneg/ so MFA setup cannot become a permanent
    lockout; the UI reports that state truthfully.

    Historical denial semantics are intentionally preserved: unauthenticated
    users and authenticated non-staff users are redirected through the login
    gate without exposing Control Center state. Domain authorization remains
    inside each operational view and therefore returns server-side 403 when a
    staff user lacks the required permission.
    """

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not user.is_active or not user.is_staff:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if mfa_configured(user):
            verified = getattr(user, "is_verified", None)
            if not callable(verified) or not verified():
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return _private_headers(view(request, *args, **kwargs))

    return wrapped


def maneg_superuser_required(view):
    @wraps(view)
    @maneg_staff_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("This Control Center operation is restricted to the Platform Owner/superuser.")
        return view(request, *args, **kwargs)

    return wrapped


@maneg_superuser_required
def stock_admin_redirect(request):
    return redirect("admin:index")
