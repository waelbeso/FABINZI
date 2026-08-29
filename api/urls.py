from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.api import DesignerOnboardingAPIView, ManufacturerOnboardingAPIView, OrganizationMemberDetailAPIView, OrganizationMembersAPIView, SubmitOnboardingAPIView, VerificationDocumentAPIView


class ApiHealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok", "service": "fabinzi", "api": "v1"})


app_name = "v1"
urlpatterns = [
    path("health/", ApiHealthView.as_view(), name="health"),
    path("onboarding/designer/", DesignerOnboardingAPIView.as_view(), name="designer-onboarding"),
    path("onboarding/manufacturer/", ManufacturerOnboardingAPIView.as_view(), name="manufacturer-onboarding"),
    path("onboarding/<int:pk>/submit/", SubmitOnboardingAPIView.as_view(), name="submit-onboarding"),
    path("onboarding/<int:application_id>/documents/", VerificationDocumentAPIView.as_view(), name="onboarding-document"),
    path("businesses/<int:organization_id>/members/", OrganizationMembersAPIView.as_view(), name="business-members"),
    path("businesses/<int:organization_id>/members/<int:membership_id>/", OrganizationMemberDetailAPIView.as_view(), name="business-member-detail"),
]
