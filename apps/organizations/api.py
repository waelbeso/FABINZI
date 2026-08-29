from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.media.models import MediaAsset
from .designer_services import attach_designer_verification_document, secure_add_or_update_member, secure_deactivate_member
from .models import Membership, OnboardingApplication, Organization, VerificationDocument
from .serializers import DesignerCreateSerializer, ManufacturerCreateSerializer, MemberMutationSerializer, OnboardingApplicationSerializer, VerificationDocumentCreateSerializer
from .services import create_designer_onboarding, create_manufacturer_onboarding, require_org_access, submit_application, update_onboarding


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
        data = serializer.validated_data.copy()
        org_data = data.pop("organization")
        data.pop("accept_terms", None)
        data["terms_accepted"] = True
        data["terms_accepted_at"] = timezone.now()
        if self.kind == Organization.Kind.DESIGNER:
            application = create_designer_onboarding(user=request.user, organization_data=org_data, profile_data=data, request=request)
        else:
            application = create_manufacturer_onboarding(user=request.user, organization_data=org_data, profile_data=data, request=request)
        return Response(OnboardingApplicationSerializer(application).data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        application = _application_for(request.user, self.kind)
        if not application:
            return Response(status=404)
        if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
            return Response({"detail": "Application is locked in its current state."}, status=409)
        org = application.organization
        org_payload = request.data.get("organization", {})
        allowed_org = {"display_name", "legal_name", "email", "phone", "website", "address_line1", "address_line2", "city", "region", "country"}
        org_data = {k: v for k, v in org_payload.items() if k in allowed_org}
        profile = org.designer_profile if org.kind == Organization.Kind.DESIGNER else org.manufacturer_profile
        profile_payload = request.data.get("profile", {})
        allowed_profile = {"studio_name", "portfolio_url", "legal_registration_number", "tax_number", "payout_information", "social_links"} if org.kind == Organization.Kind.DESIGNER else {"commercial_registration", "tax_number", "google_maps_url", "primary_contact_person", "contact_job_title", "whatsapp", "daily_capacity", "monthly_capacity", "payout_information", "manufacturing_categories", "equipment", "capability_summary", "certifications"}
        profile_data = {k: v for k, v in profile_payload.items() if k in allowed_profile}
        if request.data.get("accept_terms") is True:
            profile_data["terms_accepted"] = True
            if not profile.terms_accepted_at:
                profile_data["terms_accepted_at"] = timezone.now()
        try:
            update_onboarding(application=application, actor=request.user, organization_data=org_data, profile_data=profile_data, request=request)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        return Response(OnboardingApplicationSerializer(application).data)


class DesignerOnboardingAPIView(BusinessOnboardingView):
    kind = Organization.Kind.DESIGNER


class ManufacturerOnboardingAPIView(BusinessOnboardingView):
    kind = Organization.Kind.MANUFACTURER


class SubmitOnboardingAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        application = get_object_or_404(OnboardingApplication.objects.select_related("organization"), pk=pk)
        try:
            submit_application(application=application, actor=request.user, request=request)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        return Response(OnboardingApplicationSerializer(application).data)


class OrganizationMembersAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, organization_id):
        org = get_object_or_404(Organization, pk=organization_id)
        require_org_access(request.user, org)
        data = [{"id": m.id, "user_id": m.user_id, "username": m.user.username, "email": m.user.email, "role": m.role, "is_active": m.is_active} for m in org.memberships.select_related("user").order_by("joined_at")]
        return Response(data)

    def post(self, request, organization_id):
        org = get_object_or_404(Organization, pk=organization_id)
        serializer = MemberMutationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(get_user_model(), pk=serializer.validated_data["user_id"])
        try:
            membership = secure_add_or_update_member(organization=org, actor=request.user, user=user, role=serializer.validated_data["role"], request=request)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        return Response({"id": membership.id, "user_id": membership.user_id, "role": membership.role, "is_active": membership.is_active}, status=201)


class OrganizationMemberDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, organization_id, membership_id):
        membership = get_object_or_404(Membership.objects.select_related("organization"), pk=membership_id, organization_id=organization_id)
        try:
            secure_deactivate_member(membership=membership, actor=request.user, request=request)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        return Response(status=204)


class VerificationDocumentAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, application_id):
        application = get_object_or_404(OnboardingApplication.objects.select_related("organization"), pk=application_id)
        serializer = VerificationDocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = get_object_or_404(MediaAsset, pk=serializer.validated_data["media_asset_id"])

        if application.organization.kind == Organization.Kind.DESIGNER:
            try:
                document = attach_designer_verification_document(
                    application=application,
                    actor=request.user,
                    media_asset=asset,
                    document_type=serializer.validated_data["document_type"],
                    description=serializer.validated_data.get("description", ""),
                    request=request,
                )
            except PermissionDenied as exc:
                return Response({"detail": str(exc)}, status=403)
            except ValidationError as exc:
                return Response({"detail": exc.messages}, status=400)
            return Response({"id": document.id, "document_type": document.document_type, "media_asset_id": document.media_asset_id}, status=201)

        # Manufacturer onboarding behavior remains unchanged in this Designer-only checkpoint.
        require_org_access(request.user, application.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
        if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
            return Response({"detail": "Verification documents cannot be changed in the current state."}, status=409)
        if asset.access != MediaAsset.Access.PRIVATE:
            return Response({"detail": "Verification documents must use a private media asset."}, status=400)
        if asset.uploaded_by_id and asset.uploaded_by_id != request.user.id:
            return Response({"detail": "You cannot attach another user's private asset."}, status=403)
        document = VerificationDocument.objects.create(application=application, media_asset=asset, document_type=serializer.validated_data["document_type"], description=serializer.validated_data.get("description", ""))
        return Response({"id": document.id, "document_type": document.document_type, "media_asset_id": document.media_asset_id}, status=201)
