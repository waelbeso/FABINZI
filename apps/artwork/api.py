from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.design.models import DecorationZone, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Organization
from .models import Artwork, ArtworkVersion, DesignedProduct, IPCase
from .public import decorate_public_artwork, public_artwork_queryset
from .services import (
    add_artwork_asset,
    add_ip_case_evidence,
    add_product_placement,
    create_artwork,
    create_artwork_revision,
    create_designed_product,
    create_ip_case,
    moderate_ip_case,
    publish_designed_product,
    require_artwork_draft,
    review_artwork_version,
    set_ip_declaration,
    submit_artwork_version,
    user_can_view_artwork,
)


class ArtworkVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArtworkVersion
        fields = ["id", "version_number", "status", "color_profile", "production_notes", "metadata", "submitted_at", "reviewed_at", "review_notes"]
        read_only_fields = ["id", "version_number", "status", "submitted_at", "reviewed_at", "review_notes"]


class ArtworkSerializer(serializers.ModelSerializer):
    versions = ArtworkVersionSerializer(many=True, read_only=True)

    class Meta:
        model = Artwork
        fields = ["id", "organization", "title", "description", "tags", "status", "created_at", "updated_at", "versions"]
        read_only_fields = ["id", "status", "created_at", "updated_at", "versions"]


class PublicArtworkSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    designer = serializers.SerializerMethodField()
    approved_version_id = serializers.SerializerMethodField()
    preview = serializers.SerializerMethodField()
    production_methods = serializers.SerializerMethodField()
    suitability = serializers.SerializerMethodField()
    product_types = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(read_only=True)

    def _decorated(self, obj):
        if not hasattr(obj, "public_version"):
            decorate_public_artwork(obj)
        return obj

    def get_designer(self, obj):
        return {"id": obj.organization_id, "name": obj.organization.display_name}

    def get_approved_version_id(self, obj):
        obj = self._decorated(obj)
        return obj.public_version.pk if obj.public_version else None

    def get_preview(self, obj):
        obj = self._decorated(obj)
        if not obj.public_preview:
            return None
        media = obj.public_preview.media_asset
        metadata = media.metadata or {}
        return metadata.get("public_url") or metadata.get("static_url") or media.provider_asset_id

    def get_production_methods(self, obj):
        return self._decorated(obj).public_methods

    def get_suitability(self, obj):
        return self._decorated(obj).public_suitability

    def get_product_types(self, obj):
        return self._decorated(obj).public_product_types


class ArtworkListCreateAPIView(APIView):
    def get(self, request):
        if request.user.is_staff:
            qs = Artwork.objects.all()
        else:
            qs = Artwork.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
        return Response(ArtworkSerializer(qs, many=True).data)

    def post(self, request):
        org = get_object_or_404(Organization, pk=request.data.get("organization"))
        artwork = create_artwork(
            organization=org,
            actor=request.user,
            title=request.data.get("title", "").strip(),
            description=request.data.get("description", ""),
            tags=request.data.get("tags", []),
            request=request,
        )
        return Response(ArtworkSerializer(artwork).data, status=status.HTTP_201_CREATED)


class ArtworkPublicAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        qs = public_artwork_queryset().filter(versions__status=ArtworkVersion.Status.APPROVED).distinct()
        q = request.query_params.get("q", "").strip()
        method = request.query_params.get("method", "").strip().lower()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(organization__display_name__icontains=q))
        if method in {"print", "embroidery"}:
            key = f"versions__metadata__suitable_for_{method}"
            qs = qs.filter(Q(**{key: True}) | Q(versions__metadata__public_production_methods__contains=[method])).filter(versions__status=ArtworkVersion.Status.APPROVED).distinct()
        return Response(PublicArtworkSerializer(qs.order_by("-updated_at"), many=True).data)


class ArtworkPublicDetailAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk):
        artwork = get_object_or_404(public_artwork_queryset(), pk=pk, status=Artwork.Status.APPROVED)
        decorate_public_artwork(artwork)
        if not artwork.public_version:
            return Response(status=404)
        return Response(PublicArtworkSerializer(artwork).data)


class ArtworkDetailAPIView(APIView):
    def get(self, request, pk):
        artwork = get_object_or_404(Artwork, pk=pk)
        if not user_can_view_artwork(request.user, artwork):
            return Response(status=403)
        return Response(ArtworkSerializer(artwork).data)


class ArtworkVersionDetailAPIView(APIView):
    def patch(self, request, version_id):
        version = get_object_or_404(ArtworkVersion, pk=version_id)
        require_artwork_draft(version, request.user)
        serializer = ArtworkVersionSerializer(version, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ArtworkRevisionAPIView(APIView):
    def post(self, request, pk):
        version = create_artwork_revision(artwork=get_object_or_404(Artwork, pk=pk), actor=request.user, request=request)
        return Response(ArtworkVersionSerializer(version).data, status=201)


class ArtworkAssetAPIView(APIView):
    def post(self, request, version_id):
        asset = add_artwork_asset(
            version=get_object_or_404(ArtworkVersion, pk=version_id),
            actor=request.user,
            media_asset=get_object_or_404(MediaAsset, pk=request.data.get("media_asset")),
            kind=request.data.get("kind"),
            label=request.data.get("label", ""),
            request=request,
        )
        return Response({"id": asset.id, "kind": asset.kind, "media_asset": asset.media_asset_id}, status=201)


class IPDeclarationAPIView(APIView):
    def post(self, request, version_id):
        declaration = set_ip_declaration(
            version=get_object_or_404(ArtworkVersion, pk=version_id),
            actor=request.user,
            rights_basis=request.data.get("rights_basis"),
            rights_holder_name=request.data.get("rights_holder_name", ""),
            third_party_content=bool(request.data.get("third_party_content", False)),
            details=request.data.get("details", ""),
            accepts_ip_policy=bool(request.data.get("accepts_ip_policy", False)),
            request=request,
        )
        return Response({"id": declaration.id, "rights_basis": declaration.rights_basis, "accepts_ip_policy": declaration.accepts_ip_policy}, status=201)


class SubmitArtworkVersionAPIView(APIView):
    def post(self, request, version_id):
        version = submit_artwork_version(version=get_object_or_404(ArtworkVersion, pk=version_id), actor=request.user, request=request)
        return Response(ArtworkVersionSerializer(version).data)


class ArtworkReviewAPIView(APIView):
    def post(self, request, version_id):
        version = review_artwork_version(
            version=get_object_or_404(ArtworkVersion, pk=version_id),
            reviewer=request.user,
            decision=request.data.get("decision"),
            notes=request.data.get("notes", ""),
            request=request,
        )
        return Response(ArtworkVersionSerializer(version).data)


class DesignedProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = DesignedProduct
        fields = ["id", "organization", "garment_version", "artwork_version", "title", "description", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "created_at", "updated_at"]


class DesignedProductListCreateAPIView(APIView):
    def get(self, request):
        qs = DesignedProduct.objects.all() if request.user.is_staff else DesignedProduct.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
        return Response(DesignedProductSerializer(qs, many=True).data)

    def post(self, request):
        product = create_designed_product(
            organization=get_object_or_404(Organization, pk=request.data.get("organization")),
            actor=request.user,
            garment_version=get_object_or_404(GarmentDesignVersion, pk=request.data.get("garment_version")),
            artwork_version=get_object_or_404(ArtworkVersion, pk=request.data.get("artwork_version")),
            title=request.data.get("title", "").strip(),
            description=request.data.get("description", ""),
            request=request,
        )
        return Response(DesignedProductSerializer(product).data, status=201)


class ProductPlacementAPIView(APIView):
    def post(self, request, product_id):
        placement = add_product_placement(
            product=get_object_or_404(DesignedProduct, pk=product_id),
            actor=request.user,
            decoration_zone=get_object_or_404(DecorationZone, pk=request.data.get("decoration_zone")),
            transform=request.data.get("transform", {}),
            production_method=request.data.get("production_method"),
            request=request,
        )
        return Response({"id": placement.id, "decoration_zone": placement.decoration_zone_id, "production_method": placement.production_method}, status=201)


class PublishDesignedProductAPIView(APIView):
    def post(self, request, product_id):
        product = publish_designed_product(product=get_object_or_404(DesignedProduct, pk=product_id), actor=request.user, request=request)
        return Response(DesignedProductSerializer(product).data)


class IPCaseCreateAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        artwork = get_object_or_404(Artwork, pk=request.data.get("artwork")) if request.data.get("artwork") else None
        product = get_object_or_404(DesignedProduct, pk=request.data.get("designed_product")) if request.data.get("designed_product") else None
        case = create_ip_case(
            actor=request.user if request.user.is_authenticated else None,
            artwork=artwork,
            designed_product=product,
            reporter_name=request.data.get("reporter_name", "").strip(),
            reporter_email=request.data.get("reporter_email", "").strip(),
            claimant_rights=request.data.get("claimant_rights", ""),
            allegation=request.data.get("allegation", ""),
            request=request,
        )
        return Response({"id": case.id, "status": case.status}, status=201)


class IPCaseEvidenceAPIView(APIView):
    def post(self, request, case_id):
        evidence = add_ip_case_evidence(
            case=get_object_or_404(IPCase, pk=case_id),
            actor=request.user,
            media_asset=get_object_or_404(MediaAsset, pk=request.data.get("media_asset")),
            description=request.data.get("description", ""),
            request=request,
        )
        return Response({"id": evidence.id}, status=201)


class IPCaseModerateAPIView(APIView):
    def post(self, request, case_id):
        case = moderate_ip_case(
            case=get_object_or_404(IPCase, pk=case_id),
            reviewer=request.user,
            status=request.data.get("status"),
            resolution=request.data.get("resolution", IPCase.Resolution.NONE),
            notes=request.data.get("notes", ""),
            request=request,
        )
        return Response({"id": case.id, "status": case.status, "resolution": case.resolution})
