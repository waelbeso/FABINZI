from django.http import HttpResponse
from django.utils import timezone
from .models import MaintenanceWindow

class SecurityHeadersMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        response.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy","same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies","none")
        return response

class MaintenanceModeMiddleware:
    SAFE_PREFIXES=("/Maneg/","/healthz/","/readyz/","/static/","/account/")
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        if request.path.startswith(self.SAFE_PREFIXES): return self.get_response(request)
        now=timezone.now(); active=MaintenanceWindow.objects.filter(is_enabled=True,starts_at__lte=now,ends_at__gte=now).first()
        if active and not (request.user.is_authenticated and request.user.is_staff):
            return HttpResponse("FABINZI is temporarily under maintenance.",status=503,headers={"Retry-After":"300"})
        return self.get_response(request)
