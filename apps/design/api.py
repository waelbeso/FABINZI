from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.media.models import MediaAsset
from apps.organizations.models import Organization
from .models import DecorationZone, DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow, TechnicalReview
from .services import add_asset, create_design, create_revision, require_design_access, require_draft, review_version, submit_version, user_can_view_design


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GarmentDesignVersion
        fields = ["id","version_number","status","summary","base_material","construction_notes","technical_specs","submitted_at","reviewed_at","review_notes"]
        read_only_fields = ["id","version_number","status","submitted_at","reviewed_at","review_notes"]


class DesignSerializer(serializers.ModelSerializer):
    versions = VersionSerializer(many=True, read_only=True)
    class Meta:
        model = GarmentDesign
        fields = ["id","organization","title","description","category","status","created_at","updated_at","versions"]
        read_only_fields = ["id","status","created_at","updated_at","versions"]


class GarmentDesignListCreateAPIView(APIView):
    def get(self, request):
        qs = GarmentDesign.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct() if not request.user.is_staff else GarmentDesign.objects.all()
        return Response(DesignSerializer(qs, many=True).data)
    def post(self, request):
        org = get_object_or_404(Organization, pk=request.data.get("organization"))
        design = create_design(organization=org, actor=request.user, title=request.data.get("title", "").strip(), description=request.data.get("description", ""), category=request.data.get("category", ""), request=request)
        return Response(DesignSerializer(design).data, status=status.HTTP_201_CREATED)


class GarmentDesignDetailAPIView(APIView):
    def get(self, request, pk):
        design = get_object_or_404(GarmentDesign, pk=pk)
        if not user_can_view_design(request.user, design): return Response(status=403)
        return Response(DesignSerializer(design).data)


class VersionDetailAPIView(APIView):
    def patch(self, request, version_id):
        version = get_object_or_404(GarmentDesignVersion, pk=version_id); require_draft(version, request.user)
        serializer = VersionSerializer(version, data=request.data, partial=True); serializer.is_valid(raise_exception=True); serializer.save()
        return Response(serializer.data)


class CreateRevisionAPIView(APIView):
    def post(self, request, pk):
        version = create_revision(design=get_object_or_404(GarmentDesign, pk=pk), actor=request.user, request=request)
        return Response(VersionSerializer(version).data, status=201)


class SubmitVersionAPIView(APIView):
    def post(self, request, version_id):
        version = submit_version(version=get_object_or_404(GarmentDesignVersion, pk=version_id), actor=request.user, request=request)
        return Response(VersionSerializer(version).data)


class SizeRowAPIView(APIView):
    def post(self, request, version_id):
        version = get_object_or_404(GarmentDesignVersion, pk=version_id); require_draft(version, request.user)
        row = SizeChartRow.objects.create(version=version, size_label=request.data.get("size_label", "").strip(), measurements=request.data.get("measurements", {}), notes=request.data.get("notes", ""), sort_order=request.data.get("sort_order", 0))
        return Response({"id":row.id,"size_label":row.size_label,"measurements":row.measurements}, status=201)


class DecorationZoneAPIView(APIView):
    def post(self, request, version_id):
        version = get_object_or_404(GarmentDesignVersion, pk=version_id); require_draft(version, request.user)
        zone = DecorationZone(version=version, name=request.data.get("name", "").strip(), method=request.data.get("method", DecorationZone.Method.BOTH), placement=request.data.get("placement", {}), max_width_mm=request.data.get("max_width_mm"), max_height_mm=request.data.get("max_height_mm"), notes=request.data.get("notes", "")); zone.full_clean(); zone.save()
        return Response({"id":zone.id,"name":zone.name,"method":zone.method,"placement":zone.placement}, status=201)


class DesignAssetAPIView(APIView):
    def post(self, request, version_id):
        asset = add_asset(version=get_object_or_404(GarmentDesignVersion, pk=version_id), actor=request.user, media_asset=get_object_or_404(MediaAsset, pk=request.data.get("media_asset")), kind=request.data.get("kind"), label=request.data.get("label", ""), request=request)
        return Response({"id":asset.id,"kind":asset.kind,"media_asset":asset.media_asset_id}, status=201)


class TechnicalReviewAPIView(APIView):
    def post(self, request, version_id):
        version = review_version(version=get_object_or_404(GarmentDesignVersion, pk=version_id), reviewer=request.user, decision=request.data.get("decision"), notes=request.data.get("notes", ""), request=request)
        return Response(VersionSerializer(version).data)
