import hashlib
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, NotFound, PermissionDenied, Throttled, UnsupportedMediaType, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from config.release import APP_VERSION
from apps.artwork.models import Artwork, ArtworkVersion
from apps.artwork.public import decorate_public_artwork, public_artwork_queryset, public_media_path
from apps.checkout.models import Cart, CartItem, CheckoutSession, CustomerOrder, CustomerPurchase, PaymentAttempt
from apps.checkout.services import add_cart_item, create_cart_checkout, create_checkout, get_active_cart, initiate_online_payment, place_cart_purchase, place_order, remove_cart_item, update_cart_item, update_checkout_shipping
from apps.design.models import DecorationZone
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.media.services import ProductionStorageUnavailable, STUDIO_IMAGE_FORMATS, STUDIO_IMAGE_MAX_BYTES, create_private_studio_image, private_media_response
from apps.notifications.models import Notification, NotificationPreference
from apps.storefront.models import CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject
from apps.storefront.services import add_customization_element, create_studio_project, delete_customization_element, element_source_url, enable_customization, mark_project_ready, update_customization_element, update_studio_project, validate_studio_project

User = get_user_model()
CUSTOMER_API_ID = "FABINZI Customer API v1"
CUSTOMER_PAGE_SIZE = 20
CUSTOMER_MAX_PAGE_SIZE = 50
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")


def request_language(request):
    return "ar" if str(request.headers.get("Accept-Language", "en") or "en").lower().startswith("ar") else "en"


def localized(request, en, ar=""):
    return ar if request_language(request) == "ar" and str(ar or "").strip() else en


def money(amount, currency):
    value = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"amount": format(value, ".2f"), "currency": str(currency or "").upper() or None}


def _request_id():
    return uuid.uuid4().hex


def api_error(request, code, message, *, http_status=400, fields=None, headers=None):
    request_id = _request_id()
    response = Response({"error": {"code": code, "message": message, "fields": fields or {}, "request_id": request_id}}, status=http_status)
    response["X-Request-ID"] = request_id
    for key, value in (headers or {}).items():
        response[key] = value
    return response


def _validation_fields(detail):
    if not isinstance(detail, dict):
        return {}
    result = {}
    for key, value in detail.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        result[str(key)] = [str(item) for item in values]
    return result


def _error_message(request, code):
    messages = {
        "authentication_required": ("Authentication is required.", "يلزم تسجيل الدخول."),
        "invalid_credentials": ("Invalid credentials.", "بيانات الدخول غير صحيحة."),
        "token_expired": ("The authentication token has expired.", "انتهت صلاحية رمز الدخول."),
        "invalid_token": ("The authentication token is invalid.", "رمز الدخول غير صالح."),
        "invalid_refresh_token": ("The refresh token is invalid or expired.", "رمز تحديث الدخول غير صالح أو منتهي."),
        "permission_denied": ("You do not have permission to access this resource.", "ليس لديك صلاحية للوصول إلى هذا المورد."),
        "not_found": ("The requested resource was not found.", "المورد المطلوب غير موجود."),
        "validation_error": ("The request contains invalid data.", "تحتوي البيانات المرسلة على قيم غير صالحة."),
        "conflict": ("The request conflicts with the current resource state.", "يتعارض الطلب مع الحالة الحالية للمورد."),
        "rate_limited": ("Too many requests. Try again later.", "عدد الطلبات كبير. حاول مرة أخرى لاحقاً."),
        "invalid_state": ("The resource is not in a valid state for this operation.", "المورد ليس في حالة تسمح بهذه العملية."),
        "payment_error": ("The payment operation could not be completed.", "تعذر إكمال عملية الدفع."),
        "upload_error": ("The upload could not be accepted.", "تعذر قبول الملف المرفوع."),
        "service_unavailable": ("The required service is temporarily unavailable.", "الخدمة المطلوبة غير متاحة مؤقتاً."),
        "unsupported_media_type": ("The request media type is not supported.", "نوع محتوى الطلب غير مدعوم."),
    }
    en, ar = messages.get(code, messages["validation_error"])
    return localized(request, en, ar)


class CustomerPageNumberPagination(PageNumberPagination):
    page_size = CUSTOMER_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = CUSTOMER_MAX_PAGE_SIZE


class CustomerAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if response.status_code < 400 or (isinstance(response.data, dict) and "error" in response.data):
            return response
        code, fields = "validation_error", {}
        if isinstance(exc, NotAuthenticated):
            code = "authentication_required"
        elif isinstance(exc, AuthenticationFailed):
            code = "token_expired" if "expired" in str(response.data).lower() else "invalid_token"
        elif isinstance(exc, PermissionDenied):
            code = "permission_denied"
        elif isinstance(exc, NotFound):
            code = "not_found"
        elif isinstance(exc, Throttled):
            code = "rate_limited"
        elif isinstance(exc, UnsupportedMediaType):
            code = "unsupported_media_type"
        elif isinstance(exc, ValidationError):
            fields = _validation_fields(response.data)
        return api_error(self.request, code, _error_message(self.request, code), http_status=response.status_code, fields=fields, headers=getattr(response, "headers", None))


class CustomerPublicAPIView(CustomerAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]


class CustomerScopedAPIView(CustomerAPIView):
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]


def _domain_error(request, exc, *, code="validation_error", http_status=400):
    if isinstance(exc, DjangoPermissionDenied):
        return api_error(request, "permission_denied", _error_message(request, "permission_denied"), http_status=403)
    fields = {}
    if isinstance(exc, DjangoValidationError) and hasattr(exc, "message_dict"):
        fields = {str(key): [str(v) for v in values] for key, values in exc.message_dict.items()}
    return api_error(request, code, _error_message(request, code), http_status=http_status, fields=fields)


class CustomerBootstrapAPIView(CustomerPublicAPIView):
    def get(self, request):
        return Response({
            "contract": CUSTOMER_API_ID,
            "api_version": "v1",
            "backend_version": APP_VERSION,
            "locales": ["en", "ar"],
            "default_locale": "en",
            "localization_header": "Accept-Language",
            "authentication": {"scheme": "Bearer", "access_token_seconds": 900, "refresh_token_seconds": 2592000, "refresh_rotation": True, "refresh_reuse_revoked": True},
            "account_capabilities": {"signup": False, "email_verification": False, "account_activation": False, "password_reset": False, "social_login": False},
            "pagination": {"strategy": "page_number", "default_page_size": CUSTOMER_PAGE_SIZE, "max_page_size": CUSTOMER_MAX_PAGE_SIZE},
            "uploads": {"max_bytes": STUDIO_IMAGE_MAX_BYTES, "mime_types": sorted({mime for mime, _extension in STUDIO_IMAGE_FORMATS.values()}), "private_by_default": True},
            "checkout": {"currency_policy": "single_currency_per_cart", "server_price_authoritative": True},
        })


class CustomerLoginAPIView(CustomerPublicAPIView):
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "customer_login"

    def post(self, request):
        username = str(request.data.get("username", "") or "").strip()
        password = str(request.data.get("password", "") or "")
        user = authenticate(request=request, username=username, password=password) if username and password else None
        if user is None or not user.is_active:
            return api_error(request, "invalid_credentials", _error_message(request, "invalid_credentials"), http_status=401)
        refresh = RefreshToken.for_user(user)
        return Response({"token_type": "Bearer", "access": str(refresh.access_token), "refresh": str(refresh), "access_expires_in": 900, "refresh_expires_in": 2592000})


class CustomerRefreshAPIView(CustomerPublicAPIView):
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "customer_refresh"

    def post(self, request):
        raw = str(request.data.get("refresh", "") or "").strip()
        if not raw:
            return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        try:
            token = RefreshToken(raw)
            user = User.objects.filter(pk=token.get("user_id"), is_active=True).only("pk").first()
            if user is None:
                raise TokenError("inactive")
            serializer = TokenRefreshSerializer(data={"refresh": raw})
            serializer.is_valid(raise_exception=True)
        except Exception:
            return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        data = serializer.validated_data
        return Response({"token_type": "Bearer", "access": data["access"], "refresh": data.get("refresh"), "access_expires_in": 900, "refresh_expires_in": 2592000})


class CustomerLogoutAPIView(CustomerAPIView):
    def post(self, request):
        raw = str(request.data.get("refresh", "") or "").strip()
        if not raw:
            return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        try:
            RefreshToken(raw).blacklist()
        except TokenError as exc:
            if "blacklisted" not in str(exc).lower():
                return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        return Response(status=204)


class CustomerMeAPIView(CustomerAPIView):
    def _serialize(self, request):
        user = request.user
        return {"id": user.pk, "username": user.username, "display_name": user.get_full_name() or user.username, "first_name": user.first_name, "last_name": user.last_name, "email": user.email, "language": user.language_preference, "theme": user.theme_preference, "account_state": "active"}

    def get(self, request):
        return Response(self._serialize(request))

    def patch(self, request):
        unexpected = set(request.data) - {"language", "theme"}
        if unexpected:
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={key: ["This field is not writable."] for key in sorted(unexpected)})
        if "language" in request.data:
            value = request.data.get("language")
            if value not in request.user.Language.values:
                return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"language": ["Use en or ar."]})
            request.user.language_preference = value
        if "theme" in request.data:
            value = request.data.get("theme")
            if value not in request.user.Theme.values:
                return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"theme": ["Use system, light or dark."]})
            request.user.theme_preference = value
        request.user.save(update_fields=["language_preference", "theme_preference"])
        return Response(self._serialize(request))


def _public_image(media, request=None, *, alt_en="", alt_ar=""):
    if media is None:
        return None
    url = public_media_path(media)
    if not url:
        return None
    metadata = media.metadata or {}
    data = {"url": url, "width": metadata.get("width"), "height": metadata.get("height")}
    if request is not None:
        data["alt"] = localized(request, alt_en, alt_ar)
    return data


def _product_queryset():
    return StoreProduct.objects.filter(status=StoreProduct.Status.PUBLISHED, storefront__status=Storefront.Status.PUBLISHED).select_related("storefront", "storefront__logo", "designed_product__garment_version__design").prefetch_related("variants", "images__media_asset", "designed_product__placements", "designed_product__garment_version__decoration_zones").order_by("-featured", "-published_at", "-updated_at", "-id")


def _product_kind(product):
    return CartItem.Kind.READY_DESIGNED if product.designed_product.placements.exists() else CartItem.Kind.PLAIN


def _variant_data(variant, product):
    available = variant.is_active and not (product.fulfillment_mode == StoreProduct.FulfillmentMode.STOCK and variant.stock_quantity is not None and variant.stock_quantity < 1)
    return {"sku": variant.sku, "size": variant.size, "color_name": variant.color_name, "color_hex": variant.color_hex, "price": money(variant.price, product.currency), "available": bool(available)}


def _zone_data(zone):
    return {"name": zone.name, "method": zone.method, "placement": zone.placement, "max_width_mm": str(zone.max_width_mm) if zone.max_width_mm is not None else None, "max_height_mm": str(zone.max_height_mm) if zone.max_height_mm is not None else None}


def _product_data(product, request, *, detail=False):
    images = []
    for row in product.images.all():
        image = _public_image(row.media_asset, request, alt_en=row.alt_en, alt_ar=row.alt_ar)
        if image:
            images.append(image)
    data = {
        "store": {"slug": product.storefront.slug, "name": localized(request, product.storefront.name_en, product.storefront.name_ar)},
        "slug": product.slug,
        "title": localized(request, product.title_en, product.title_ar),
        "description": localized(request, product.description_en, product.description_ar),
        "kind": _product_kind(product),
        "customization_enabled": bool(product.customization_enabled),
        "featured": bool(product.featured),
        "fulfillment_mode": product.fulfillment_mode,
        "lead_time_days": product.lead_time_days,
        "base_price": money(product.base_price, product.currency),
        "variants": [_variant_data(v, product) for v in product.variants.all() if v.is_active],
        "images": images,
        "published_at": product.published_at,
    }
    if detail:
        data["decoration_zones"] = [_zone_data(zone) for zone in product.designed_product.garment_version.decoration_zones.all()] if product.customization_enabled else []
    return data


class CustomerStoreListAPIView(CustomerPublicAPIView):
    def get(self, request):
        qs = Storefront.objects.filter(status=Storefront.Status.PUBLISHED).select_related("logo").order_by("name_en", "id")
        q = str(request.query_params.get("q", "") or "").strip()
        if q:
            qs = qs.filter(Q(name_en__icontains=q) | Q(name_ar__icontains=q))
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        rows = [{"slug": row.slug, "name": localized(request, row.name_en, row.name_ar), "about": localized(request, row.about_en, row.about_ar), "logo": _public_image(row.logo), "published_at": row.published_at} for row in page]
        return paginator.get_paginated_response(rows)


class CustomerStoreDetailAPIView(CustomerPublicAPIView):
    def get(self, request, store_slug):
        row = get_object_or_404(Storefront.objects.select_related("logo"), slug=store_slug, status=Storefront.Status.PUBLISHED)
        return Response({"slug": row.slug, "name": localized(request, row.name_en, row.name_ar), "about": localized(request, row.about_en, row.about_ar), "logo": _public_image(row.logo), "published_at": row.published_at})


class CustomerProductListAPIView(CustomerPublicAPIView):
    def get(self, request):
        qs = _product_queryset()
        q = str(request.query_params.get("q", "") or "").strip()
        store = str(request.query_params.get("store", "") or "").strip()
        customizable = str(request.query_params.get("customizable", "") or "").strip().lower()
        if q:
            qs = qs.filter(Q(title_en__icontains=q) | Q(title_ar__icontains=q) | Q(description_en__icontains=q) | Q(description_ar__icontains=q))
        if store:
            qs = qs.filter(storefront__slug=store)
        if customizable in {"true", "1"}:
            qs = qs.filter(customization_enabled=True)
        elif customizable in {"false", "0"}:
            qs = qs.filter(customization_enabled=False)
        elif customizable:
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"customizable": ["Use true or false."]})
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_product_data(row, request) for row in page])


class CustomerProductDetailAPIView(CustomerPublicAPIView):
    def get(self, request, store_slug, product_slug):
        row = get_object_or_404(_product_queryset(), storefront__slug=store_slug, slug=product_slug)
        return Response(_product_data(row, request, detail=True))


def _artwork_data(artwork):
    decorate_public_artwork(artwork)
    preview = None
    if artwork.public_preview:
        media = artwork.public_preview.media_asset
        preview = _public_image(media)
    return {"id": artwork.pk, "title": artwork.title, "description": artwork.description, "tags": artwork.tags, "creator": {"name": artwork.organization.display_name}, "approved_version_id": artwork.public_version.pk if artwork.public_version else None, "preview": preview, "production_methods": artwork.public_methods, "suitability": artwork.public_suitability, "product_types": artwork.public_product_types, "updated_at": artwork.updated_at}


class CustomerArtworkListAPIView(CustomerPublicAPIView):
    def get(self, request):
        qs = public_artwork_queryset().filter(versions__status=ArtworkVersion.Status.APPROVED).distinct()
        q = str(request.query_params.get("q", "") or "").strip()
        method = str(request.query_params.get("method", "") or "").strip().lower()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(organization__display_name__icontains=q))
        if method:
            if method not in {"print", "embroidery"}:
                return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"method": ["Use print or embroidery."]})
            key = f"versions__metadata__suitable_for_{method}"
            qs = qs.filter(Q(**{key: True}) | Q(versions__metadata__public_production_methods__contains=[method])).filter(versions__status=ArtworkVersion.Status.APPROVED).distinct()
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs.order_by("-updated_at", "-id"), request, view=self)
        return paginator.get_paginated_response([_artwork_data(row) for row in page])


class CustomerArtworkDetailAPIView(CustomerPublicAPIView):
    def get(self, request, artwork_id):
        row = get_object_or_404(public_artwork_queryset(), pk=artwork_id, status=Artwork.Status.APPROVED)
        decorate_public_artwork(row)
        if not row.public_version:
            raise Http404
        return Response(_artwork_data(row))


def _resolve_product(store_slug, product_slug):
    return get_object_or_404(_product_queryset(), storefront__slug=store_slug, slug=product_slug)


def _resolve_variant(product, sku, *, required=False):
    if not sku and not required:
        return None
    return get_object_or_404(ProductVariant, product=product, sku=sku, is_active=True)


def _project_queryset(user):
    return StudioProject.objects.filter(customer=user).select_related("product__storefront", "product__designed_product__garment_version", "variant__product").prefetch_related("product__designed_product__garment_version__decoration_zones", "customization__elements__decoration_zone", "customization__elements__media_asset", "customization__elements__artwork_version__artwork__organization")


def _element_data(element):
    source_url = f"/api/v1/customer/media/{element.media_asset_id}/" if element.kind == CustomizationElement.Kind.IMAGE and element.media_asset_id else element_source_url(element)
    return {"id": element.pk, "kind": element.kind, "decoration_zone": _zone_data(element.decoration_zone), "text": element.text, "media_asset_id": element.media_asset_id, "artwork_version_id": element.artwork_version_id, "production_method": element.production_method, "transform": element.transform, "style": element.style, "source_url": source_url or None}


def _project_data(project, request):
    elements = []
    if hasattr(project, "customization"):
        elements = [_element_data(row) for row in project.customization.elements.select_related("decoration_zone", "media_asset", "artwork_version__artwork__organization")]
    unit = project.variant.price if project.variant_id else project.product.base_price
    return {"id": project.pk, "status": project.status, "product": {"store_slug": project.product.storefront.slug, "product_slug": project.product.slug, "title": localized(request, project.product.title_en, project.product.title_ar), "customization_enabled": bool(project.product.customization_enabled)}, "variant": _variant_data(project.variant, project.product) if project.variant_id else None, "quantity": project.quantity, "customer_notes": project.customer_notes, "unit_price": money(unit, project.product.currency), "decoration_zones": [_zone_data(zone) for zone in project.product.designed_product.garment_version.decoration_zones.all()], "elements": elements, "created_at": project.created_at, "updated_at": project.updated_at, "ready_at": project.ready_at}


class CustomerStudioProjectsAPIView(CustomerAPIView):
    def get(self, request):
        qs = _project_queryset(request.user).exclude(status=StudioProject.Status.ARCHIVED).order_by("-updated_at", "-id")
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_project_data(row, request) for row in page])

    def post(self, request):
        try:
            product = _resolve_product(str(request.data.get("store_slug", "")), str(request.data.get("product_slug", "")))
            variant = _resolve_variant(product, str(request.data.get("variant_sku", "") or ""))
            row = create_studio_project(customer=request.user, product=product, variant=variant, quantity=int(request.data.get("quantity", 1)), customer_notes=str(request.data.get("customer_notes", "") or ""), request=request)
            return Response(_project_data(_project_queryset(request.user).get(pk=row.pk), request), status=201)
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)


class CustomerStudioProjectDetailAPIView(CustomerAPIView):
    def get(self, request, project_id):
        return Response(_project_data(get_object_or_404(_project_queryset(request.user), pk=project_id), request))

    def patch(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        if row.status != StudioProject.Status.DRAFT:
            return api_error(request, "invalid_state", _error_message(request, "invalid_state"), http_status=409)
        try:
            variant = row.variant
            if "variant_sku" in request.data:
                variant = _resolve_variant(row.product, str(request.data.get("variant_sku", "") or ""))
            row = update_studio_project(project=row, actor=request.user, variant=variant, quantity=int(request.data["quantity"]) if "quantity" in request.data else None, customer_notes=request.data.get("customer_notes") if "customer_notes" in request.data else None, request=request)
            return Response(_project_data(_project_queryset(request.user).get(pk=row.pk), request))
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)


class CustomerStudioCustomizationAPIView(CustomerAPIView):
    def post(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        try:
            customization = enable_customization(project=row, actor=request.user, request=request)
            return Response({"id": customization.pk, "enabled": bool(customization.enabled)}, status=201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


class CustomerStudioUploadAPIView(CustomerScopedAPIView):
    throttle_scope = "customer_upload"

    def post(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        if row.status != StudioProject.Status.DRAFT:
            return api_error(request, "invalid_state", _error_message(request, "invalid_state"), http_status=409)
        try:
            asset = create_private_studio_image(upload=request.FILES.get("file"), owner=request.user)
            metadata = asset.metadata or {}
            return Response({"id": asset.pk, "mime_type": asset.mime_type, "size_bytes": asset.size_bytes, "width": metadata.get("width"), "height": metadata.get("height"), "access_url": f"/api/v1/customer/media/{asset.pk}/"}, status=201)
        except ProductionStorageUnavailable:
            return api_error(request, "service_unavailable", _error_message(request, "service_unavailable"), http_status=503)
        except DjangoValidationError as exc:
            return _domain_error(request, exc, code="upload_error")


class CustomerStudioElementAPIView(CustomerAPIView):
    def post(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        transform = request.data.get("transform", {})
        style = request.data.get("style", {})
        rights_confirmed = request.data.get("rights_confirmed", False)
        if not isinstance(transform, dict) or not isinstance(style, dict) or not isinstance(rights_confirmed, bool):
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"payload": ["transform/style must be objects and rights_confirmed must be a JSON boolean."]})
        try:
            customization = enable_customization(project=row, actor=request.user, request=request)
            zone = get_object_or_404(DecorationZone, version=row.product.designed_product.garment_version, name=request.data.get("decoration_zone"))
            media = get_object_or_404(MediaAsset, pk=request.data.get("media_asset_id"), access=MediaAsset.Access.PRIVATE, uploaded_by=request.user, metadata__studio_private_upload=True) if request.data.get("media_asset_id") else None
            artwork_version = get_object_or_404(ArtworkVersion, pk=request.data.get("artwork_version_id"), status=ArtworkVersion.Status.APPROVED, artwork__status=Artwork.Status.APPROVED) if request.data.get("artwork_version_id") else None
            element = add_customization_element(customization=customization, actor=request.user, decoration_zone=zone, kind=request.data.get("kind"), text=str(request.data.get("text", "") or ""), media_asset=media, artwork_version=artwork_version, production_method=str(request.data.get("production_method", "") or ""), rights_confirmed=rights_confirmed, transform=transform, style=style, sort_order=int(request.data.get("sort_order", 0)), request=request)
            return Response(_element_data(element), status=201)
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)


class CustomerStudioElementDetailAPIView(CustomerAPIView):
    def _row(self, request, project_id, element_id):
        project = get_object_or_404(StudioProject, pk=project_id, customer=request.user)
        return get_object_or_404(CustomizationElement.objects.select_related("customization__project", "decoration_zone", "media_asset", "artwork_version__artwork"), pk=element_id, customization__project=project)

    def patch(self, request, project_id, element_id):
        row = self._row(request, project_id, element_id)
        if "transform" in request.data and not isinstance(request.data.get("transform"), dict):
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"transform": ["Use a JSON object."]})
        try:
            row = update_customization_element(element=row, actor=request.user, transform=request.data.get("transform") if "transform" in request.data else None, production_method=request.data.get("production_method") if "production_method" in request.data else None, text=request.data.get("text") if "text" in request.data else None, request=request)
            return Response(_element_data(row))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)

    def delete(self, request, project_id, element_id):
        row = self._row(request, project_id, element_id)
        try:
            delete_customization_element(element=row, actor=request.user, request=request)
            return Response(status=204)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


class CustomerStudioValidationAPIView(CustomerAPIView):
    def get(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        try:
            result = validate_studio_project(row)
            return Response({"valid": True, "errors": [], "unit_price": money(result["unit_price"], row.product.currency)})
        except DjangoValidationError as exc:
            return Response({"valid": False, "errors": [str(item) for item in exc.messages], "unit_price": money(row.variant.price if row.variant_id else row.product.base_price, row.product.currency)})


class CustomerStudioReadyAPIView(CustomerAPIView):
    def post(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        try:
            row = mark_project_ready(project=row, actor=request.user, request=request)
            return Response(_project_data(_project_queryset(request.user).get(pk=row.pk), request))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, code="invalid_state", http_status=409)


class CustomerStudioCheckoutAPIView(CustomerAPIView):
    def post(self, request, project_id):
        row = get_object_or_404(_project_queryset(request.user), pk=project_id)
        existed = CheckoutSession.objects.filter(studio_project=row).exists()
        try:
            session = create_checkout(project=row, actor=request.user, request=request)
            return Response(_checkout_data(session), status=200 if existed else 201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, code="invalid_state", http_status=409)


class CustomerPrivateMediaAPIView(CustomerAPIView):
    def get(self, request, asset_id):
        asset = get_object_or_404(MediaAsset, pk=asset_id, access=MediaAsset.Access.PRIVATE, uploaded_by=request.user, metadata__studio_private_upload=True)
        try:
            payload = private_media_response(asset)
        except ProductionStorageUnavailable:
            return api_error(request, "service_unavailable", _error_message(request, "service_unavailable"), http_status=503)
        if isinstance(payload, str):
            response = HttpResponseRedirect(payload)
            response["Cache-Control"] = "private, no-store"
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            response["Referrer-Policy"] = "no-referrer"
            return response
        response = FileResponse(payload, content_type=asset.mime_type)
        response["Content-Disposition"] = f'inline; filename="{asset.original_filename.replace(chr(34), "")}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        return response


def _cart_item_data(row, request):
    return {"id": row.pk, "kind": row.kind, "product": {"store_slug": row.store_product.storefront.slug, "product_slug": row.store_product.slug, "title": localized(request, row.store_product.title_en, row.store_product.title_ar)}, "variant": _variant_data(row.variant, row.store_product), "studio_project_id": row.studio_project_id, "quantity": row.quantity, "unit_price": money(row.variant.price, row.store_product.currency), "line_total": money(row.variant.price * row.quantity, row.store_product.currency)}


def _cart_data(cart, request):
    rows = list(cart.items.select_related("store_product__storefront", "store_product__designed_product", "variant", "studio_project").prefetch_related("store_product__designed_product__placements"))
    if not rows:
        return {"id": cart.pk, "status": cart.status, "items": [], "item_count": 0, "subtotal": money(0, None), "shipping_amount": money(0, None), "discount_amount": money(0, None), "total": money(0, None)}
    from apps.checkout.services import _cart_pricing
    _lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    return {"id": cart.pk, "status": cart.status, "items": [_cart_item_data(row, request) for row in rows], "item_count": len(rows), "subtotal": money(subtotal, currency), "shipping_amount": money(shipping, currency), "discount_amount": money(discount, currency), "total": money(total, currency)}


class CustomerCartAPIView(CustomerAPIView):
    def get(self, request):
        try:
            return Response(_cart_data(get_active_cart(request.user), request))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


class CustomerCartItemCreateAPIView(CustomerAPIView):
    def post(self, request):
        try:
            kind = str(request.data.get("kind", "") or "")
            if kind not in CartItem.Kind.values:
                raise DjangoValidationError("Unsupported Cart item type.")
            quantity = int(request.data.get("quantity", 1))
            if kind == CartItem.Kind.STUDIO:
                project = get_object_or_404(_project_queryset(request.user), pk=request.data.get("studio_project_id"))
                if not project.variant_id:
                    raise DjangoValidationError("Studio project requires a selected variant.")
                if "quantity" not in request.data:
                    quantity = project.quantity
                item = add_cart_item(customer=request.user, product=project.product, variant=project.variant, quantity=quantity, kind=kind, studio_project=project, request=request)
            else:
                product = _resolve_product(str(request.data.get("store_slug", "")), str(request.data.get("product_slug", "")))
                variant = _resolve_variant(product, str(request.data.get("variant_sku", "") or ""), required=True)
                actual_kind = _product_kind(product)
                if kind != actual_kind:
                    raise DjangoValidationError(f"This product must be added as {actual_kind}.")
                item = add_cart_item(customer=request.user, product=product, variant=variant, quantity=quantity, kind=kind, request=request)
            return Response(_cart_data(item.cart, request), status=201)
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)


class CustomerCartItemDetailAPIView(CustomerAPIView):
    def patch(self, request, item_id):
        row = get_object_or_404(CartItem.objects.select_related("cart", "store_product__storefront", "variant", "studio_project"), pk=item_id, cart__customer=request.user, cart__status=Cart.Status.ACTIVE)
        try:
            update_cart_item(item=row, actor=request.user, quantity=request.data.get("quantity"), request=request)
            return Response(_cart_data(row.cart, request))
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)

    def delete(self, request, item_id):
        row = get_object_or_404(CartItem.objects.select_related("cart"), pk=item_id, cart__customer=request.user, cart__status=Cart.Status.ACTIVE)
        try:
            remove_cart_item(item=row, actor=request.user, request=request)
            return Response(status=204)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


def _checkout_data(row):
    return {"id": row.pk, "status": row.status, "source": "cart" if row.cart_id else "studio", "subtotal": money(row.subtotal, row.currency), "shipping_amount": money(row.shipping_amount, row.currency), "discount_amount": money(row.discount_amount, row.currency), "total": money(row.total, row.currency), "shipping": {"name": row.shipping_name, "phone": row.shipping_phone, "email": row.shipping_email, "address1": row.shipping_address1, "address2": row.shipping_address2, "city": row.shipping_city, "region": row.shipping_region, "country": row.shipping_country, "postal_code": row.postal_code}, "created_at": row.created_at, "updated_at": row.updated_at, "placed_at": row.placed_at}


class CustomerCartCheckoutAPIView(CustomerAPIView):
    def post(self, request):
        try:
            cart = get_active_cart(request.user)
            existed = CheckoutSession.objects.filter(cart=cart).exists()
            row = create_cart_checkout(cart=cart, actor=request.user, request=request)
            return Response(_checkout_data(row), status=200 if existed else 201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, code="invalid_state", http_status=409)


class CustomerCheckoutDetailAPIView(CustomerAPIView):
    def _row(self, request, checkout_id):
        return get_object_or_404(CheckoutSession, pk=checkout_id, customer=request.user)

    def get(self, request, checkout_id):
        row = self._row(request, checkout_id)
        if row.cart_id and row.status == CheckoutSession.Status.DRAFT:
            try:
                row = create_cart_checkout(cart=row.cart, actor=request.user, request=request)
            except (DjangoValidationError, DjangoPermissionDenied) as exc:
                return _domain_error(request, exc)
        return Response(_checkout_data(row))

    def patch(self, request, checkout_id):
        row = self._row(request, checkout_id)
        allowed = {"shipping_name", "shipping_phone", "shipping_email", "shipping_address1", "shipping_address2", "shipping_city", "shipping_region", "shipping_country", "postal_code"}
        unexpected = set(request.data) - allowed
        if unexpected:
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={key: ["This field is not writable."] for key in sorted(unexpected)})
        if row.status != CheckoutSession.Status.DRAFT:
            return api_error(request, "invalid_state", _error_message(request, "invalid_state"), http_status=409)
        try:
            row = update_checkout_shipping(session=row, actor=request.user, request=request, **request.data)
            return Response(_checkout_data(row))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


def _storage_idempotency_key(user_id, checkout_id, raw):
    return f"cv1-{user_id}-{checkout_id}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:40]}"[:80]


def _payment_data(attempt):
    secret = str((attempt.provider_payload or {}).get("client_secret", "") or "") if isinstance(attempt.provider_payload, dict) else ""
    return {"provider": attempt.provider, "status": attempt.status, "redirect_url": attempt.redirect_url or None, "client_secret": secret or None}


PURCHASE_STATUS_AR = {"pending_payment": "بانتظار الدفع", "confirmed": "تم التأكيد", "payment_failed": "فشل الدفع", "cancelled": "ملغي", "refunded": "مسترد"}
FULFILLMENT_STATUS_AR = {"processing": "قيد التجهيز", "waiting_production": "بانتظار الإنتاج", "ready_to_pack": "جاهز للتعبئة", "packed": "تمت التعبئة", "shipped": "تم الشحن", "partially_shipped": "تم شحن جزء من الطلب", "delivered": "تم التسليم", "partially_delivered": "تم تسليم جزء من الطلب", "failed": "تعذر التسليم", "returned": "مرتجع", "cancelled": "ملغي", "partially_cancelled": "تم إلغاء جزء من الطلب", "refunded": "مسترد"}


def _status_label(request, value, english):
    if request_language(request) == "ar":
        return PURCHASE_STATUS_AR.get(value) or FULFILLMENT_STATUS_AR.get(value) or english
    return english


def _fulfillment_data(row, request):
    if not row:
        return {"status": "processing", "label": _status_label(request, "processing", "Processing"), "carrier": None, "tracking_number": None, "tracking_url": None, "packed_at": None, "shipped_at": None, "delivered_at": None}
    return {"status": row.status, "label": _status_label(request, row.status, row.get_status_display()), "carrier": row.carrier or None, "tracking_number": row.tracking_number or None, "tracking_url": row.tracking_url or None, "packed_at": row.packed_at, "shipped_at": row.shipped_at, "delivered_at": row.delivered_at}


def _purchase_item_data(order, request):
    return {"reference": str(order.number), "title": localized(request, order.item.store_product.title_en, order.item.store_product.title_ar) or order.item.title, "sku": order.item.sku, "size": order.item.size, "color_name": order.item.color_name, "quantity": order.item.quantity, "unit_price": money(order.item.unit_price, order.currency), "line_total": money(order.item.line_total, order.currency), "status": order.status, "status_label": _status_label(request, order.status, order.get_status_display()), "customized": bool(order.item.studio_project_id), "studio_project_id": order.item.studio_project_id, "fulfillment": _fulfillment_data(getattr(order, "fulfillment", None), request)}


def _purchase_queryset(user):
    return CustomerPurchase.objects.filter(customer=user).prefetch_related("payment_attempts", "child_orders__item__store_product", "child_orders__fulfillment").order_by("-created_at", "-id")


def _purchase_data(row, request, *, detail=False):
    attempts = list(row.payment_attempts.all())
    attempt = attempts[0] if attempts else None
    data = {"reference": str(row.number), "status": row.status, "status_label": _status_label(request, row.status, row.get_status_display()), "fulfillment_status": row.fulfillment_status, "fulfillment_status_label": _status_label(request, row.fulfillment_status, row.fulfillment_status.replace("_", " ").title()), "payment": {"method": row.payment_method, "status": attempt.status if attempt else None}, "subtotal": money(row.subtotal, row.currency), "shipping_amount": money(row.shipping_amount, row.currency), "discount_amount": money(row.discount_amount, row.currency), "total": money(row.total, row.currency), "item_count": row.child_orders.count(), "created_at": row.created_at, "confirmed_at": row.confirmed_at}
    if detail:
        data["shipping"] = row.shipping_snapshot
        data["items"] = [_purchase_item_data(order, request) for order in row.child_orders.all()]
    return data


def _attempt_for_key(session, storage_key):
    return PaymentAttempt.objects.filter(idempotency_key=storage_key, purchase__checkout=session).select_related("purchase").first()


def _maybe_initiate(attempt):
    if attempt.provider != CustomerPurchase.PaymentMethod.COD and attempt.status in {PaymentAttempt.Status.PENDING, PaymentAttempt.Status.FAILED}:
        initiate_online_payment(attempt=attempt)
        attempt.refresh_from_db()


class CustomerPlaceCheckoutAPIView(CustomerScopedAPIView):
    throttle_scope = "customer_place"

    def post(self, request, checkout_id):
        raw = str(request.headers.get("Idempotency-Key", "") or "").strip()
        if not IDEMPOTENCY_PATTERN.match(raw):
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"Idempotency-Key": ["Use 8-80 characters: letters, digits, dot, underscore, colon or hyphen."]})
        payment_method = str(request.data.get("payment_method", "") or "").strip().lower()
        if payment_method not in CustomerPurchase.PaymentMethod.values:
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"payment_method": ["Unsupported payment method."]})
        storage_key = _storage_idempotency_key(request.user.pk, checkout_id, raw)
        try:
            with transaction.atomic():
                session = get_object_or_404(CheckoutSession.objects.select_for_update(), pk=checkout_id, customer=request.user)
                replay = _attempt_for_key(session, storage_key)
                if replay:
                    if replay.provider != payment_method:
                        return api_error(request, "conflict", _error_message(request, "conflict"), http_status=409)
                    purchase_id, replay_id = replay.purchase_id, replay.pk
                    created = False
                else:
                    if session.status != CheckoutSession.Status.DRAFT:
                        return api_error(request, "conflict", _error_message(request, "conflict"), http_status=409)
                    if session.cart_id:
                        purchase, attempt = place_cart_purchase(session=session, actor=request.user, payment_method=payment_method, request=request)
                    else:
                        order, attempt = place_order(session=session, actor=request.user, payment_method=payment_method, request=request)
                        purchase = order.purchase
                    attempt.idempotency_key = storage_key
                    attempt.save(update_fields=["idempotency_key", "updated_at"])
                    purchase_id, replay_id, created = purchase.pk, attempt.pk, True
            attempt = PaymentAttempt.objects.get(pk=replay_id)
            try:
                _maybe_initiate(attempt)
            except DjangoValidationError:
                if attempt.provider != CustomerPurchase.PaymentMethod.COD:
                    return api_error(request, "payment_error", _error_message(request, "payment_error"), http_status=503)
                raise
            purchase = _purchase_queryset(request.user).get(pk=purchase_id)
            return Response({"idempotent_replay": not created, "purchase": _purchase_data(purchase, request, detail=True), "payment": _payment_data(attempt)}, status=201 if created else 200)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, code="invalid_state", http_status=409)


class CustomerPaymentOptionsAPIView(CustomerAPIView):
    def get(self, request):
        labels = {"cod": ("Cash on Delivery", "الدفع عند الاستلام"), "paymob": ("Paymob", "Paymob"), "stripe": ("Stripe", "Stripe")}
        rows = []
        for provider in CustomerPurchase.PaymentMethod.values:
            cfg = IntegrationConfig.objects.filter(provider=provider).first()
            if cfg and cfg.enabled and (provider == CustomerPurchase.PaymentMethod.COD or cfg.last_test_status == IntegrationConfig.TestStatus.SUCCESS):
                en, ar = labels[provider]
                rows.append({"provider": provider, "label": localized(request, en, ar)})
        return Response({"results": rows})


class CustomerPurchaseListAPIView(CustomerAPIView):
    def get(self, request):
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(_purchase_queryset(request.user), request, view=self)
        return paginator.get_paginated_response([_purchase_data(row, request) for row in page])


class CustomerPurchaseDetailAPIView(CustomerAPIView):
    def get(self, request, purchase_reference):
        return Response(_purchase_data(get_object_or_404(_purchase_queryset(request.user), number=purchase_reference), request, detail=True))


def _notification_target(row):
    match = re.fullmatch(r"/purchases/(\d+)/", str(row.destination or ""))
    if match:
        purchase = CustomerPurchase.objects.filter(pk=int(match.group(1)), customer=row.recipient).only("number").first()
        if purchase:
            return {"resource": "purchase", "reference": str(purchase.number)}
    match = re.fullmatch(r"/orders/(\d+)/", str(row.destination or ""))
    if match:
        order = CustomerOrder.objects.filter(pk=int(match.group(1)), customer=row.recipient).select_related("purchase").first()
        if order and order.purchase_id:
            return {"resource": "purchase", "reference": str(order.purchase.number)}
    return None


def _notification_data(row, request):
    return {"id": row.pk, "type": row.type, "title": localized(request, row.title_en, row.title_ar), "body": localized(request, row.body_en, row.body_ar), "is_read": bool(row.is_read), "created_at": row.created_at, "read_at": row.read_at, "target": _notification_target(row)}


class CustomerNotificationListAPIView(CustomerAPIView):
    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user).order_by("-created_at", "-id")
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_notification_data(row, request) for row in page])


class CustomerNotificationReadAPIView(CustomerAPIView):
    def post(self, request, notification_id):
        row = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
        if not row.is_read:
            row.is_read, row.read_at = True, timezone.now()
            row.save(update_fields=["is_read", "read_at"])
        return Response(_notification_data(row, request))


class CustomerNotificationReadAllAPIView(CustomerAPIView):
    def post(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=timezone.now())
        return Response({"updated": count})


class NotificationPreferenceInputSerializer(serializers.Serializer):
    email_enabled = serializers.BooleanField(required=False)
    sms_enabled = serializers.BooleanField(required=False)
    phone_e164 = serializers.CharField(required=False, allow_blank=True, max_length=24)


class CustomerNotificationPreferenceAPIView(CustomerAPIView):
    def _serialize(self, row):
        return {"email_enabled": bool(row.email_enabled), "sms_enabled": bool(row.sms_enabled), "phone_e164": row.phone_e164}

    def get(self, request):
        row, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(self._serialize(row))

    def patch(self, request):
        serializer = NotificationPreferenceInputSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields=_validation_fields(serializer.errors))
        row, _ = NotificationPreference.objects.get_or_create(user=request.user)
        for key, value in serializer.validated_data.items():
            setattr(row, key, value)
        if row.sms_enabled and not row.phone_e164.startswith("+"):
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"phone_e164": ["SMS phone must use E.164 format."]})
        row.save()
        return Response(self._serialize(row))
