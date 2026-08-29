from django.urls import include, path
from two_factor.urls import urlpatterns as tf_urls

from apps.accounts.views import app_home, profile_preferences
from apps.platform_ops.views import healthz, home, placeholder_surface
from apps.integrations.admin_site import fabinzi_admin_site
from apps.organizations.views import designer_portal, edit_onboarding, manufacturer_portal, submit_onboarding

urlpatterns = [
    path("", home, name="home"),
    path("app/", app_home, name="app-home"),
    path("app/settings/preferences/", profile_preferences, name="profile-preferences"),
    path("studio/", placeholder_surface, {"surface": "Studio"}, name="studio"),
    path("artwork/", placeholder_surface, {"surface": "Artwork Marketplace"}, name="artwork"),
    path("designer/", designer_portal, name="designer"),
    path("manufacturer/", manufacturer_portal, name="manufacturer"),
    path("onboarding/<int:pk>/edit/", edit_onboarding, name="edit-onboarding"),
    path("onboarding/<int:pk>/submit/", submit_onboarding, name="submit-onboarding"),
    path("healthz/", healthz, name="healthz"),
    path("api/v1/", include(("api.urls", "v1"), namespace="v1")),
    path("", include(tf_urls)),
    path("Maneg/", fabinzi_admin_site.urls),
]
