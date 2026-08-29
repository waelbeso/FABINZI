from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.artwork.models import ArtworkVersion, DesignedProduct
from apps.design.models import DecorationZone
from apps.media.models import MediaAsset
from apps.media.services import create_private_studio_image
from apps.organizations.models import Organization
from .models import CustomerCustomization, CustomizationElement, ProductVariant, StoreProduct, StoreProductImage, Storefront, StudioProject
from .services import (
    add_customization_element,
    add_product_image,
    add_variant,
    create_store_product,
    create_storefront,
    create_studio_project,
    delete_customization_element,
    element_source_url,
    enable_customization,
    mark_project_ready,
    publish_store_product,
    publish_storefront,
    require_project_draft,
    require_project_owner,
    update_customization_element,
    update_studio_project,
    validate_studio_project,
)


class VariantSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ProductVariant
        fields = ["id", "sku", "size", "color_name", "color_hex", "price_adjustment", "price", "stock_quantity", "is_active"]


class StoreProductSerializer(serializers.ModelSerializer):
    variants = VariantSerializer(many=True, read_only=True)

    class Meta:
        model = StoreProduct
        fields = ["id", "storefront", "designed_product", "slug", "status", "title_en", "title_ar", "description_en", "description_ar", "base_price", "currency", "fulfillment_mode", "lead_time_days", "customization_enabled", "featured", "variants", "published_at"]


class StorefrontSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = Storefront
        fields = ["id", "organization", "slug", "status", "name_en", "name_ar", "about_en", "about_ar", "logo", "products", "published_at"]

    def get_products(self, obj):
        return StoreProductSerializer(obj.products.filter(status=StoreProduct.Status.PUBLISHED), many=True).data


class PublicStorefrontListAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(StorefrontSerializer(Storefront.objects.filter(status=Storefront.Status.PUBLISHED), many=True).data)


class PublicStorefrontDetailAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, slug):
        return Response(StorefrontSerializer(get_object_or_404(Storefront, status=Storefront.Status.PUBLISHED, slug=slug)).data)


class PublicStoreProductAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, store_slug, product_slug):
        product = get_object_or_404(StoreProduct.objects.select_related("storefront", "designed_product"), storefront__slug=store_slug, storefront__status=Storefront.Status.PUBLISHED, slug=product_slug, status=StoreProduct.Status.PUBLISHED)
        return Response(StoreProductSerializer(product).data)


class StorefrontManageAPIView(APIView):
    def get(self, request, organization_id):
        store = get_object_or_404(Storefront, organization_id=organization_id)
        from .services import require_store_access
        require_store_access(request.user, store)
        return Response(StorefrontSerializer(store).data)

    def post(self, request, organization_id):
        org = get_object_or_404(Organization, pk=organization_id)
        store = create_storefront(organization=org, actor=request.user, slug=request.data.get("slug", ""), name_en=request.data.get("name_en", ""), name_ar=request.data.get("name_ar", ""), about_en=request.data.get("about_en", ""), about_ar=request.data.get("about_ar", ""), request=request)
        return Response(StorefrontSerializer(store).data, status=201)


class PublishStorefrontAPIView(APIView):
    def post(self, request, store_id):
        return Response(StorefrontSerializer(publish_storefront(storefront=get_object_or_404(Storefront, pk=store_id), actor=request.user, request=request)).data)


class StoreProductManageAPIView(APIView):
    def post(self, request, store_id):
        store = get_object_or_404(Storefront, pk=store_id)
        designed = get_object_or_404(DesignedProduct, pk=request.data.get("designed_product"))
        product = create_store_product(storefront=store, actor=request.user, designed_product=designed, slug=request.data.get("slug", ""), title_en=request.data.get("title_en", ""), title_ar=request.data.get("title_ar", ""), description_en=request.data.get("description_en", ""), description_ar=request.data.get("description_ar", ""), base_price=request.data.get("base_price"), currency=request.data.get("currency", "EGP"), customization_enabled=bool(request.data.get("customization_enabled", False)), fulfillment_mode=request.data.get("fulfillment_mode", StoreProduct.FulfillmentMode.MADE_TO_ORDER), lead_time_days=request.data.get("lead_time_days"), request=request)
        return Response(StoreProductSerializer(product).data, status=201)


class ProductVariantAPIView(APIView):
    def post(self, request, product_id):
        variant = add_variant(product=get_object_or_404(StoreProduct, pk=product_id), actor=request.user, sku=request.data.get("sku", ""), size=request.data.get("size", ""), color_name=request.data.get("color_name", ""), color_hex=request.data.get("color_hex", ""), price_adjustment=request.data.get("price_adjustment", 0), stock_quantity=request.data.get("stock_quantity"), request=request)
        return Response(VariantSerializer(variant).data, status=201)


class ProductImageAPIView(APIView):
    def post(self, request, product_id):
        image = add_product_image(product=get_object_or_404(StoreProduct, pk=product_id), actor=request.user, media_asset=get_object_or_404(MediaAsset, pk=request.data.get("media_asset")), alt_en=request.data.get("alt_en", ""), alt_ar=request.data.get("alt_ar", ""), sort_order=request.data.get("sort_order", 0), request=request)
        return Response({"id": image.pk, "media_asset": image.media_asset_id}, status=201)


class PublishStoreProductAPIView(APIView):
    def post(self, request, product_id):
        return Response(StoreProductSerializer(publish_store_product(product=get_object_or_404(StoreProduct, pk=product_id), actor=request.user, request=request)).data)


class StudioProjectSerializer(serializers.ModelSerializer):
    elements = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()

    class Meta:
        model = StudioProject
        fields = ["id", "product", "variant", "status", "quantity", "customer_notes", "preview", "unit_price", "elements", "created_at", "updated_at", "ready_at"]

    def get_unit_price(self, obj):
        return str(obj.variant.price if obj.variant_id else obj.product.base_price)

    def get_elements(self, obj):
        if not hasattr(obj, "customization"):
            return []
        return [
            {
                "id": element.pk,
                "kind": element.kind,
                "decoration_zone": element.decoration_zone_id,
                "text": element.text,
                "media_asset": element.media_asset_id,
                "artwork_version": element.artwork_version_id,
                "artwork_title": element.artwork_version.artwork.title if element.artwork_version_id else None,
                "designer": element.artwork_version.artwork.organization.display_name if element.artwork_version_id else None,
                "production_method": element.production_method,
                "transform": element.transform,
                "style": element.style,
                "source_url": element_source_url(element),
            }
            for element in obj.customization.elements.select_related("decoration_zone", "media_asset", "artwork_version__artwork__organization")
        ]


class StudioProjectsAPIView(APIView):
    def get(self, request):
        return Response(StudioProjectSerializer(StudioProject.objects.filter(customer=request.user), many=True).data)

    def post(self, request):
        product = get_object_or_404(StoreProduct, pk=request.data.get("product"))
        variant = get_object_or_404(ProductVariant, pk=request.data.get("variant"), product=product, is_active=True) if request.data.get("variant") else None
        project = create_studio_project(customer=request.user, product=product, variant=variant, quantity=int(request.data.get("quantity", 1)), customer_notes=request.data.get("customer_notes", ""), request=request)
        return Response(StudioProjectSerializer(project).data, status=201)


class StudioProjectDetailAPIView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        require_project_owner(request.user, project)
        return Response(StudioProjectSerializer(project).data)

    def patch(self, request, project_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        variant = get_object_or_404(ProductVariant, pk=request.data.get("variant"), product=project.product, is_active=True) if "variant" in request.data and request.data.get("variant") else None
        project = update_studio_project(project=project, actor=request.user, variant=variant if "variant" in request.data else project.variant, quantity=int(request.data["quantity"]) if "quantity" in request.data else None, customer_notes=request.data.get("customer_notes") if "customer_notes" in request.data else None, request=request)
        return Response(StudioProjectSerializer(project).data)


class StudioCustomizationAPIView(APIView):
    def post(self, request, project_id):
        customization = enable_customization(project=get_object_or_404(StudioProject, pk=project_id), actor=request.user, request=request)
        return Response({"id": customization.pk, "project": customization.project_id, "enabled": customization.enabled}, status=201)


class StudioUploadAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, project_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        require_project_draft(request.user, project)
        asset = create_private_studio_image(upload=request.FILES.get("file"), owner=request.user)
        return Response({"id": asset.pk, "mime_type": asset.mime_type, "size_bytes": asset.size_bytes, "preview_url": f"/media/private/{asset.pk}/"}, status=status.HTTP_201_CREATED)


class CustomizationElementAPIView(APIView):
    def post(self, request, project_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        customization = enable_customization(project=project, actor=request.user, request=request)
        media = get_object_or_404(MediaAsset, pk=request.data.get("media_asset")) if request.data.get("media_asset") else None
        artwork_version = get_object_or_404(ArtworkVersion, pk=request.data.get("artwork_version")) if request.data.get("artwork_version") else None
        element = add_customization_element(
            customization=customization,
            actor=request.user,
            decoration_zone=get_object_or_404(DecorationZone, pk=request.data.get("decoration_zone")),
            kind=request.data.get("kind"),
            text=request.data.get("text", ""),
            media_asset=media,
            artwork_version=artwork_version,
            production_method=request.data.get("production_method", ""),
            rights_confirmed=bool(request.data.get("rights_confirmed", False)),
            transform=request.data.get("transform", {}),
            style=request.data.get("style", {}),
            sort_order=request.data.get("sort_order", 0),
            request=request,
        )
        return Response(StudioProjectSerializer(project).data, status=201)


class CustomizationElementDetailAPIView(APIView):
    def patch(self, request, project_id, element_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        require_project_owner(request.user, project)
        element = get_object_or_404(CustomizationElement, pk=element_id, customization__project=project)
        try:
            element = update_customization_element(
                element=element,
                actor=request.user,
                transform=request.data.get("transform") if "transform" in request.data else None,
                production_method=request.data.get("production_method") if "production_method" in request.data else None,
                text=request.data.get("text") if "text" in request.data else None,
                request=request,
            )
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        return Response({"id": element.pk, "transform": element.transform, "production_method": element.production_method, "text": element.text})

    def delete(self, request, project_id, element_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        require_project_owner(request.user, project)
        element = get_object_or_404(CustomizationElement, pk=element_id, customization__project=project)
        delete_customization_element(element=element, actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudioValidationAPIView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(StudioProject, pk=project_id)
        require_project_owner(request.user, project)
        try:
            result = validate_studio_project(project)
            return Response(result)
        except ValidationError as exc:
            return Response({"valid": False, "errors": exc.messages, "unit_price": str(project.variant.price if project.variant_id else project.product.base_price), "currency": project.product.currency}, status=200)


class StudioReadyAPIView(APIView):
    def post(self, request, project_id):
        return Response(StudioProjectSerializer(mark_project_ready(project=get_object_or_404(StudioProject, pk=project_id), actor=request.user, request=request)).data)
