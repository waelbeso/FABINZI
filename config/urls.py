from django.urls import include, path
from apps.accounts.views import app_home, profile_preferences
from apps.platform_ops.views import healthz, home, placeholder_surface
from apps.integrations.admin_site import fabinzi_admin_site
from apps.organizations.views import designer_portal, manufacturer_portal, submit_onboarding

urlpatterns = [
    path("", home, name="home"),
    path("app/", app_home, name="app-home"),
    path("app/settings/preferences/", profile_preferences, name="profile-preferences"),
    path("studio/", placeholder_surface, {"surface": "Studio"}, name="studio"),
    path("artwork/", placeholder_surface, {"surface": "Artwork Marketplace"}, name="artwork"),
    path("designer/", designer_portal, name="designer"),
    path("manufacturer/", manufacturer_portal, name="manufacturer"),
    path("onboarding/<int:pk>/submit/", submit_onboarding, name="submit-onboarding"),
    path("healthz/", healthz, name="healthz"),
    path("api/v1/", include(("api.urls", "v1"), namespace="v1")),
    path("account/", include(("two_factor.urls", "two_factor"), namespace="two_factor")),
    path("Maneg/", fabinzi_admin_site.urls),
]
