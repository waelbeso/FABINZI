from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Membership, Organization
from .serializers import DesignerCreateSerializer, ManufacturerCreateSerializer, OnboardingApplicationSerializer
from .services import create_designer_onboarding, create_manufacturer_onboarding, submit_application


def _application_for(user, kind):
    membership = Membership.objects.filter(user=user, is_active=True, organization__kind=kind).select_related("organization", "organization__onboarding_application").first()
    return membership.organization.onboarding_application if membership else None


class BusinessOnboardingView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    kind = None

    def get(self, request):
        application = _application_for(request.user, self.kind)
        if not application:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(OnboardingApplicationSerializer(application).data)

    def post(self, request):
        if _application_for(request.user, self.kind):
            return Response({"detail": "An onboarding application already exists for this business type."}, status=409)
        serializer_class = DesignerCreateSerializer if self.kind == Organization.Kind.DESIGNER else ManufacturerCreateSerializer
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org_data = data.pop("organization")
        data.pop("accept_terms", None)
        data["terms_accepted"] = True
        data["terms_accepted_at"] = timezone.now()
        if self.kind == Organization.Kind.DESIGNER:
            application = create_designer_onboarding(user=request.user, organization_data=org_data, profile_data=data, request=request)
        else:
            application = create_manufacturer_onboarding(user=request.user, organization_data=org_data, profile_data=data, request=request)
        return Response(OnboardingApplicationSerializer(application).data, status=status.HTTP_201_CREATED)


class DesignerOnboardingAPIView(BusinessOnboardingView):
    kind = Organization.Kind.DESIGNER


class ManufacturerOnboardingAPIView(BusinessOnboardingView):
    kind = Organization.Kind.MANUFACTURER


class SubmitOnboardingAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        application = None
        for kind in (Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER):
            candidate = _application_for(request.user, kind)
            if candidate and candidate.pk == pk:
                application = candidate
                break
        if not application:
            return Response({"detail": "Not found."}, status=404)
        submit_application(application=application, actor=request.user, request=request)
        return Response(OnboardingApplicationSerializer(application).data)
