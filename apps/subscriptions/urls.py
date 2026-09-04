from django.urls import path

from apps.accounts.views import business_start
from .views import designer_subscription, manufacturer_subscription, team_invitation_accept

urlpatterns = [
    path("app/business/start/", business_start, name="business-start"),
    path("designer/subscription/", designer_subscription, name="designer-subscription"),
    path("manufacturer/subscription/", manufacturer_subscription, name="manufacturer-subscription"),
    path("team/invitations/accept/<str:token>/", team_invitation_accept, name="team-invitation-accept"),
]
