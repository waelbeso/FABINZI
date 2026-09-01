from django.urls import path

from .views import (
    designer_subscription,
    designer_team_v2,
    manufacturer_subscription,
    manufacturer_team_v2,
    team_invitation_accept,
)

urlpatterns = [
    path("designer/subscription/", designer_subscription, name="designer-subscription"),
    path("designer/team/", designer_team_v2, name="designer-team-v2-3"),
    path("manufacturer/subscription/", manufacturer_subscription, name="manufacturer-subscription"),
    path("manufacturer/team/", manufacturer_team_v2, name="manufacturer-team-v2-3"),
    path("team/invitations/accept/<str:token>/", team_invitation_accept, name="team-invitation-accept"),
]
