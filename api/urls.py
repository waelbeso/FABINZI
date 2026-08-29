from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.design.api import CreateRevisionAPIView, DecorationZoneAPIView, DesignAssetAPIView, GarmentDesignDetailAPIView, GarmentDesignListCreateAPIView, SizeRowAPIView, SubmitVersionAPIView, TechnicalReviewAPIView, VersionDetailAPIView
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
    path("designs/", GarmentDesignListCreateAPIView.as_view(), name="design-list-create"),
    path("designs/<int:pk>/", GarmentDesignDetailAPIView.as_view(), name="design-detail"),
    path("designs/<int:pk>/revisions/", CreateRevisionAPIView.as_view(), name="design-revision"),
    path("design-versions/<int:version_id>/", VersionDetailAPIView.as_view(), name="design-version-detail"),
    path("design-versions/<int:version_id>/submit/", SubmitVersionAPIView.as_view(), name="design-version-submit"),
    path("design-versions/<int:version_id>/sizes/", SizeRowAPIView.as_view(), name="design-version-size"),
    path("design-versions/<int:version_id>/decoration-zones/", DecorationZoneAPIView.as_view(), name="design-version-zone"),
    path("design-versions/<int:version_id>/assets/", DesignAssetAPIView.as_view(), name="design-version-asset"),
    path("design-versions/<int:version_id>/review/", TechnicalReviewAPIView.as_view(), name="design-version-review"),
]
