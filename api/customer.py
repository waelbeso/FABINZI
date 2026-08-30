import hashlib
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    UnsupportedMediaType,
    ValidationError,
)
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
from apps.artwork.api import PublicArtworkSerializer
from apps.artwork.models import Artwork, ArtworkVersion
from apps.artwork.public import decorate_public_artwork, public_artwork_queryset, public_media_path
from apps.checkout.models import CartItem, CheckoutSession, CustomerPurchase, PaymentAttempt
from apps.checkout.services import (
    add_cart_item,
    create_cart_checkout,
    create_checkout,
    get_active_cart,
    initiate_online_payment,
    place_cart_purchase,
    place_order,
    remove_cart_item,
    update_cart_item,
    update_checkout_shipping,
)
from apps.design.models import DecorationZone
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.media.services import (
    ProductionStorageUnavailable,
    STUDIO_IMAGE_FORMATS,
    STUDIO_IMAGE_MAX_BYTES,
    create_private_studio_image,
    private_media_response,
)
from apps.notifications.models import Notification, NotificationPreference
from apps.operations.models import FulfillmentRecord
from apps.storefront.models import CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject
from apps.storefront.services import (
    add_customization_element,
    delete_customization_element,
    enable_customization,
    mark_project_ready,
    update_customization_element,
    update_studio_project,
    validate_studio_project,
)


CUSTOMER_API_ID = "FABINZI Customer API v1"
CUSTOMER_PAGE_SIZE = 20
CUSTOMER_MAX_PAGE_SIZE = 50
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")


def request_language(request):
    raw = str(request.headers.get("Accept-Language", "en") or "en").lower()
    return "ar" if raw.startswith("ar") else "en"


def localized(request, en, ar=""):
    if request_language(request) == "ar" and str(ar or "").strip():
        return ar
    return en


def money(amount, currency):
    value = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"amount": format(value, ".2f"), "currency": str(currency or "").upper() or None}


def _safe_request_id():
    return uuid.uuid4().hex


def api_error(request, code, message, *, http_status=400, fields=None, headers=None):
    request_id = _safe_request_id()
    payload = {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or {},
            "request_id": request_id,
        }
    }
    response = Response(payload, status=http_status)
    response["X-Request-ID"] = request_id
    for key, value in (headers or {}).items():
        response[key] = value
    return response


def _validation_fields(detail):
    if isinstance(detail, dict):
        fields = {}
        for key, value in detail.items():
            if isinstance(value, (list, tuple)):
                fields[str(key)] = [str(item) for item in value]
            else:
                fields[str(key)] = [str(value)]
        return fields
    return {}


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

        code = "validation_error"
        fields = {}
        if isinstance(exc, NotAuthenticated):
            code = "authentication_required"
        elif isinstance(exc, AuthenticationFailed):
            text = str(response.data).lower()
            code = "token_expired" if "expired" in text else "invalid_token"
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
        wrapped = api_error(
            self.request,
            code,
            _error_message(self.request, code),
            http_status=response.status_code,
            fields=fields,
            headers=getattr(response, "headers", None),
        )
        return wrapped


class CustomerPublicAPIView(CustomerAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]


class CustomerScopedAPIView(CustomerAPIView):
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]


class CustomerBootstrapAPIView(CustomerPublicAPIView):
    def get(self, request):
        return Response(
            {
                "contract": CUSTOMER_API_ID,
                "api_version": "v1",
                "backend_version": APP_VERSION,
                "locales": ["en", "ar"],
                "default_locale": "en",
                "localization_header": "Accept-Language",
                "authentication": {
                    "scheme": "Bearer",
                    "access_token_seconds": 900,
                    "refresh_token_seconds": 2592000,
                    "refresh_rotation": True,
                    "refresh_reuse_revoked": True,
                },
                "account_capabilities": {
                    "signup": False,
                    "email_verification": False,
                    "account_activation": False,
                    "password_reset": False,
                    "social_login": False,
                },
                "pagination": {
                    "strategy": "page_number",
                    "default_page_size": CUSTOMER_PAGE_SIZE,
                    "max_page_size": CUSTOMER_MAX_PAGE_SIZE,
                },
                "uploads": {
                    "max_bytes": STUDIO_IMAGE_MAX_BYTES,
                    "mime_types": sorted({mime for mime, _ext in STUDIO_IMAGE_FORMATS.values()}),
                    "private_by_default": True,
                },
                "checkout": {"currency_policy": "single_currency_per_cart", "server_price_authoritative": True},
            }
        )


class CustomerLoginAPIView(CustomerPublicAPIView):
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "customer_login"

    def post(self, request):
        username = str(request.data.get("username", "") or "").strip()
        password = str(request.data.get("password", "") or "")
        if not username or not password:
            return api_error(request, "invalid_credentials", _error_message(request, "invalid_credentials"), http_status=401)
        user = authenticate(request=request, username=username, password=password)
        if user is None or not user.is_active:
            return api_error(request, "invalid_credentials", _error_message(request, "invalid_credentials"), http_status=401)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "token_type": "Bearer",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "access_expires_in": 900,
                "refresh_expires_in": 2592000,
            }
        )


class CustomerRefreshAPIView(CustomerPublicAPIView):
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "customer_refresh"

    def post(self, request):
        raw = str(request.data.get("refresh", "") or "").strip()
        if not raw:
            return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        serializer = TokenRefreshSerializer(data={"refresh": raw})
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        data = serializer.validated_data
        return Response(
            {
                "token_type": "Bearer",
                "access": data["access"],
                "refresh": data.get("refresh"),
                "access_expires_in": 900,
                "refresh_expires_in": 2592000,
            }
        )


class CustomerLogoutAPIView(CustomerAPIView):
    def post(self, request):
        raw = str(request.data.get("refresh", "") or "").strip()
        if not raw:
            return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        try:
            token = RefreshToken(raw)
            token.blacklist()
        except TokenError as exc:
            if "blacklisted" not in str(exc).lower():
                return api_error(request, "invalid_refresh_token", _error_message(request, "invalid_refresh_token"), http_status=401)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerMeAPIView(CustomerAPIView):
    def _data(self, request):
        user = request.user
        return {
            "id": user.pk,
            "username": user.username,
            "display_name": user.get_full_name() or user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "language": user.language_preference,
            "theme": user.theme_preference,
            "account_state": "active" if user.is_active else "inactive",
        }

    def get(self, request):
        return Response(self._data(request))

    def patch(self, request):
        allowed = {"language", "theme"}
        unexpected = set(request.data) - allowed
        if unexpected:
            return api_error(
                request,
                "validation_error",
                _error_message(request, "validation_error"),
                fields={key: ["This field is not writable."] for key in sorted(unexpected)},
            )
        if "language" in request.data:
            value = str(request.data.get("language") or "")
            if value not in request.user.Language.values:
                return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"language": ["Use en or ar."]})
            request.user.language_preference = value
        if "theme" in request.data:
            value = str(request.data.get("theme") or "")
            if value not in request.user.Theme.values:
                return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"theme": ["Use system, light or dark."]})
            request.user.theme_preference = value
        request.user.save(update_fields=["language_preference", "theme_preference"])
        return Response(self._data(request))


def _public_image(media, request=None, *, alt_en="", alt_ar=""):
    url = public_media_path(media)
    if not url:
        return None
    metadata = media.metadata or {}
    result = {"url": url, "width": metadata.get("width"), "height": metadata.get("height")}
    if request is not None:
        result["alt"] = localized(request, alt_en, alt_ar)
    return result


def _product_queryset():
    return (
        StoreProduct.objects.filter(status=StoreProduct.Status.PUBLISHED, storefront__status=Storefront.Status.PUBLISHED)
        .select_related("storefront", "storefront__logo", "designed_product__garment_version__design")
        .prefetch_related(
            "variants",
            "images__media_asset",
            "designed_product__placements",
            "designed_product__garment_version__decoration_zones",
        )
        .order_by("-featured", "-published_at", "-updated_at")
    )


def _product_kind(product):
    return CartItem.Kind.READY_DESIGNED if product.designed_product.placements.exists() else CartItem.Kind.PLAIN


def _variant_data(variant, currency):
    available = variant.is_active
    if variant.product.fulfillment_mode == StoreProduct.FulfillmentMode.STOCK and variant.stock_quantity is not None:
        available = available and variant.stock_quantity > 0
    return {
        "sku": variant.sku,
        "size": variant.size,
        "color_name": variant.color_name,
        "color_hex": variant.color_hex,
        "price": money(variant.price, currency),
        "available": bool(available),
    }


def _zone_data(zone):
    return {
        "name": zone.name,
        "method": zone.method,
        "placement": zone.placement,
        "max_width_mm": str(zone.max_width_mm) if zone.max_width_mm is not None else None,
        "max_height_mm": str(zone.max_height_mm) if zone.max_height_mm is not None else None,
    }


def _product_data(product, request, *, detail=False):
    images = []
    for image in product.images.all():
        rendered = _public_image(image.media_asset, request, alt_en=image.alt_en, alt_ar=image.alt_ar)
        if rendered:
            images.append(rendered)
    data = {
        "store": {"slug": product.storefront.slug, "name": localized(request, product.storefront.name_en, product.storefront.name_ar)},
        "slug": product.slug,
        "title": localized(request, product.title_en, product.title_ar),
        "description": localized(request, product.description_en, product.description_ar),
        "kind": _product_kind(product),
        "customization_enabled": product.customization_enabled,
        "featured": product.featured,
        "fulfillment_mode": product.fulfillment_mode,
        "lead_time_days": product.lead_time_days,
        "base_price": money(product.base_price, product.currency),
        "variants": [_variant_data(v, product.currency) for v in product.variants.all() if v.is_active],
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
            qs = qs.filter(models.Q(name_en__icontains=q) | models.Q(name_ar__icontains=q))
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        rows = []
        for store in page:
            rows.append(
                {
                    "slug": store.slug,
                    "name": localized(request, store.name_en, store.name_ar),
                    "about": localized(request, store.about_en, store.about_ar),
                    "logo": _public_image(store.logo) if store.logo_id else None,
                    "published_at": store.published_at,
                }
            )
        return paginator.get_paginated_response(rows)


class CustomerStoreDetailAPIView(CustomerPublicAPIView):
    def get(self, request, store_slug):
        store = get_object_or_404(Storefront.objects.select_related("logo"), slug=store_slug, status=Storefront.Status.PUBLISHED)
        return Response(
            {
                "slug": store.slug,
                "name": localized(request, store.name_en, store.name_ar),
                "about": localized(request, store.about_en, store.about_ar),
                "logo": _public_image(store.logo) if store.logo_id else None,
                "published_at": store.published_at,
            }
        )


class CustomerProductListAPIView(CustomerPublicAPIView):
    def get(self, request):
        from django.db.models import Q

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
        return paginator.get_paginated_response([_product_data(product, request) for product in page])


class CustomerProductDetailAPIView(CustomerPublicAPIView):
    def get(self, request, store_slug, product_slug):
        product = get_object_or_404(_product_queryset(), storefront__slug=store_slug, slug=product_slug)
        return Response(_product_data(product, request, detail=True))


class CustomerArtworkListAPIView(CustomerPublicAPIView):
    def get(self, request):
        from django.db.models import Q

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
        return paginator.get_paginated_response(PublicArtworkSerializer(page, many=True).data)


class CustomerArtworkDetailAPIView(CustomerPublicAPIView):
    def get(self, request, artwork_id):
        artwork = get_object_or_404(public_artwork_queryset(), pk=artwork_id, status=Artwork.Status.APPROVED)
        decorate_public_artwork(artwork)
        if not artwork.public_version:
            raise Http404
        return Response(PublicArtworkSerializer(artwork).data)


def _resolve_public_product(store_slug, product_slug):
    return get_object_or_404(_product_queryset(), storefront__slug=store_slug, slug=product_slug)


def _resolve_variant(product, sku, *, required=False):
    if not sku and not required:
        return None
    return get_object_or_404(ProductVariant, product=product, sku=sku, is_active=True)


def _studio_element_data(element):
    if element.kind == CustomizationElement.Kind.IMAGE and element.media_asset_id:
        source_url = f"/api/v1/customer/media/{element.media_asset_id}/"
    else:
        from apps.storefront.services import element_source_url
        source_url = element_source_url(element)
    return {
        "id": element.pk,
        "kind": element.kind,
        "decoration_zone": _zone_data(element.decoration_zone),
        "text": element.text,
        "media_asset_id": element.media_asset_id,
        "artwork_version_id": element.artwork_version_id,
        "production_method": element.production_method,
        "transform": element.transform,
        "style": element.style,
        "source_url": source_url or None,
    }


def _studio_data(project, request):
    elements = []
    if hasattr(project, "customization"):
        elements = [
            _studio_element_data(element)
            for element in project.customization.elements.select_related("decoration_zone", "media_asset", "artwork_version__artwork__organization").all()
        ]
    unit = project.variant.price if project.variant_id else project.product.base_price
    return {
        "id": project.pk,
        "status": project.status,
        "product": {
            "store_slug": project.product.storefront.slug,
            "product_slug": project.product.slug,
            "title": localized(request, project.product.title_en, project.product.title_ar),
            "customization_enabled": project.product.customization_enabled,
        },
        "variant": _variant_data(project.variant, project.product.currency) if project.variant_id else None,
        "quantity": project.quantity,
        "customer_notes": project.customer_notes,
        "unit_price": money(unit, project.product.currency),
        "decoration_zones": [_zone_data(zone) for zone in project.product.designed_product.garment_version.decoration_zones.all()],
        "elements": elements,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "ready_at": project.ready_at,
    }


def _customer_project_queryset(user):
    return (
        StudioProject.objects.filter(customer=user)
        .select_related("product__storefront", "product__designed_product__garment_version", "variant__product")
        .prefetch_related("product__designed_product__garment_version__decoration_zones", "customization__elements__decoration_zone", "customization__elements__media_asset", "customization__elements__artwork_version__artwork__organization")
    )


def _domain_error(request, exc, *, default_code="validation_error", http_status=400):
    if isinstance(exc, DjangoPermissionDenied):
        return api_error(request, "permission_denied", _error_message(request, "permission_denied"), http_status=403)
    fields = {}
    if isinstance(exc, DjangoValidationError) and hasattr(exc, "message_dict"):
        fields = {key: [str(v) for v in values] for key, values in exc.message_dict.items()}
    return api_error(request, default_code, _error_message(request, default_code), http_status=http_status, fields=fields)


class CustomerStudioProjectsAPIView(CustomerAPIView):
    def get(self, request):
        qs = _customer_project_queryset(request.user).exclude(status=StudioProject.Status.ARCHIVED).order_by("-updated_at", "-id")
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_studio_data(project, request) for project in page])

    def post(self, request):
        try:
            product = _resolve_public_product(str(request.data.get("store_slug", "")), str(request.data.get("product_slug", "")))
            variant = _resolve_variant(product, str(request.data.get("variant_sku", "") or ""), required=False)
            quantity = int(request.data.get("quantity", 1))
            from apps.storefront.services import create_studio_project
            project = create_studio_project(customer=request.user, product=product, variant=variant, quantity=quantity, customer_notes=str(request.data.get("customer_notes", "") or ""), request=request)
            project = _customer_project_queryset(request.user).get(pk=project.pk)
            return Response(_studio_data(project, request), status=201)
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)


class CustomerStudioProjectDetailAPIView(CustomerAPIView):
    def get(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        return Response(_studio_data(project, request))

    def patch(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        try:
            variant = project.variant
            if "variant_sku" in request.data:
                variant = _resolve_variant(project.product, str(request.data.get("variant_sku", "") or ""), required=False)
            quantity = int(request.data["quantity"]) if "quantity" in request.data else None
            project = update_studio_project(project=project, actor=request.user, variant=variant, quantity=quantity, customer_notes=request.data.get("customer_notes") if "customer_notes" in request.data else None, request=request)
            project = _customer_project_queryset(request.user).get(pk=project.pk)
            return Response(_studio_data(project, request))
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc, default_code="invalid_state" if project.status != StudioProject.Status.DRAFT else "validation_error", http_status=409 if project.status != StudioProject.Status.DRAFT else 400)


class CustomerStudioCustomizationAPIView(CustomerAPIView):
    def post(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        try:
            customization = enable_customization(project=project, actor=request.user, request=request)
            return Response({"id": customization.pk, "enabled": customization.enabled}, status=201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


class CustomerStudioUploadAPIView(CustomerScopedAPIView):
    throttle_scope = "customer_upload"

    def post(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        if project.status != StudioProject.Status.DRAFT:
            return api_error(request, "invalid_state", _error_message(request, "invalid_state"), http_status=409)
        try:
            asset = create_private_studio_image(upload=request.FILES.get("file"), owner=request.user)
            return Response(
                {
                    "id": asset.pk,
                    "mime_type": asset.mime_type,
                    "size_bytes": asset.size_bytes,
                    "width": (asset.metadata or {}).get("width"),
                    "height": (asset.metadata or {}).get("height"),
                    "access_url": f"/api/v1/customer/media/{asset.pk}/",
                },
                status=201,
            )
        except ProductionStorageUnavailable:
            return api_error(request, "service_unavailable", _error_message(request, "service_unavailable"), http_status=503)
        except DjangoValidationError as exc:
            return _domain_error(request, exc, default_code="upload_error", http_status=400)


class CustomerStudioElementAPIView(CustomerAPIView):
    def post(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        try:
            customization = enable_customization(project=project, actor=request.user, request=request)
            zone = get_object_or_404(DecorationZone, version=project.product.designed_product.garment_version, name=request.data.get("decoration_zone"))
            media = None
            if request.data.get("media_asset_id"):
                media = get_object_or_404(MediaAsset, pk=request.data.get("media_asset_id"), access=MediaAsset.Access.PRIVATE, uploaded_by=request.user, metadata__studio_private_upload=True)
            artwork_version = None
            if request.data.get("artwork_version_id"):
                artwork_version = get_object_or_404(ArtworkVersion, pk=request.data.get("artwork_version_id"), status=ArtworkVersion.Status.APPROVED, artwork__status=Artwork.Status.APPROVED)
            element = add_customization_element(
                customization=customization,
                actor=request.user,
                decoration_zone=zone,
                kind=request.data.get("kind"),
                text=str(request.data.get("text", "") or ""),
                media_asset=media,
                artwork_version=artwork_version,
                production_method=str(request.data.get("production_method", "") or ""),
                rights_confirmed=bool(request.data.get("rights_confirmed", False)),
                transform=request.data.get("transform", {}),
                style=request.data.get("style", {}),
                sort_order=int(request.data.get("sort_order", 0)),
                request=request,
            )
            return Response(_studio_element_data(element), status=201)
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)


class CustomerStudioElementDetailAPIView(CustomerAPIView):
    def _element(self, request, project_id, element_id):
        project = get_object_or_404(StudioProject, pk=project_id, customer=request.user)
        return get_object_or_404(CustomizationElement.objects.select_related("customization__project", "decoration_zone", "media_asset", "artwork_version__artwork"), pk=element_id, customization__project=project)

    def patch(self, request, project_id, element_id):
        element = self._element(request, project_id, element_id)
        try:
            element = update_customization_element(element=element, actor=request.user, transform=request.data.get("transform") if "transform" in request.data else None, production_method=request.data.get("production_method") if "production_method" in request.data else None, text=request.data.get("text") if "text" in request.data else None, request=request)
            return Response(_studio_element_data(element))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)

    def delete(self, request, project_id, element_id):
        element = self._element(request, project_id, element_id)
        try:
            delete_customization_element(element=element, actor=request.user, request=request)
            return Response(status=204)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


class CustomerStudioValidationAPIView(CustomerAPIView):
    def get(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        try:
            result = validate_studio_project(project)
            return Response({"valid": True, "errors": [], "unit_price": money(result["unit_price"], project.product.currency)})
        except DjangoValidationError as exc:
            return Response({"valid": False, "errors": [str(item) for item in exc.messages], "unit_price": money(project.variant.price if project.variant_id else project.product.base_price, project.product.currency)})


class CustomerStudioReadyAPIView(CustomerAPIView):
    def post(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        try:
            project = mark_project_ready(project=project, actor=request.user, request=request)
            project = _customer_project_queryset(request.user).get(pk=project.pk)
            return Response(_studio_data(project, request))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, default_code="invalid_state", http_status=409)


class CustomerStudioCheckoutAPIView(CustomerAPIView):
    def post(self, request, project_id):
        project = get_object_or_404(_customer_project_queryset(request.user), pk=project_id)
        existed = CheckoutSession.objects.filter(studio_project=project).exists()
        try:
            session = create_checkout(project=project, actor=request.user, request=request)
            return Response(_checkout_data(session), status=200 if existed else 201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, default_code="invalid_state", http_status=409)


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


def _cart_item_data(item, request):
    return {
        "id": item.pk,
        "kind": item.kind,
        "product": {
            "store_slug": item.store_product.storefront.slug,
            "product_slug": item.store_product.slug,
            "title": localized(request, item.store_product.title_en, item.store_product.title_ar),
        },
        "variant": _variant_data(item.variant, item.store_product.currency),
        "studio_project_id": item.studio_project_id,
        "quantity": item.quantity,
        "unit_price": money(item.variant.price, item.store_product.currency),
        "line_total": money(item.variant.price * item.quantity, item.store_product.currency),
    }


def _cart_data(cart, request):
    items = list(cart.items.select_related("store_product__storefront", "store_product__designed_product", "variant", "studio_project").prefetch_related("store_product__designed_product__placements"))
    if not items:
        return {
            "id": cart.pk,
            "status": cart.status,
            "items": [],
            "item_count": 0,
            "subtotal": money(0, None),
            "shipping": money(0, None),
            "discount": money(0, None),
            "total": money(0, None),
        }
    from apps.checkout.services import _cart_pricing
    _lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    return {
        "id": cart.pk,
        "status": cart.status,
        "items": [_cart_item_data(item, request) for item in items],
        "item_count": len(items),
        "subtotal": money(subtotal, currency),
        "shipping": money(shipping, currency),
        "discount": money(discount, currency),
        "total": money(total, currency),
    }


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
                project = get_object_or_404(_customer_project_queryset(request.user), pk=request.data.get("studio_project_id"))
                if not project.variant_id:
                    raise DjangoValidationError("Studio project requires a selected variant.")
                product, variant = project.product, project.variant
                if "quantity" not in request.data:
                    quantity = project.quantity
                item = add_cart_item(customer=request.user, product=product, variant=variant, quantity=quantity, kind=kind, studio_project=project, request=request)
            else:
                product = _resolve_public_product(str(request.data.get("store_slug", "")), str(request.data.get("product_slug", "")))
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
        item = get_object_or_404(CartItem.objects.select_related("cart", "store_product__storefront", "variant", "studio_project"), pk=item_id, cart__customer=request.user, cart__status=CartItem._meta.get_field("cart").remote_field.model.Status.ACTIVE)
        try:
            update_cart_item(item=item, actor=request.user, quantity=request.data.get("quantity"), request=request)
            return Response(_cart_data(item.cart, request))
        except (DjangoValidationError, DjangoPermissionDenied, TypeError, ValueError) as exc:
            return _domain_error(request, exc)

    def delete(self, request, item_id):
        item = get_object_or_404(CartItem.objects.select_related("cart"), pk=item_id, cart__customer=request.user, cart__status="active")
        try:
            remove_cart_item(item=item, actor=request.user, request=request)
            return Response(status=204)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc)


def _checkout_data(session):
    return {
        "id": session.pk,
        "status": session.status,
        "source": "cart" if session.cart_id else "studio",
        "subtotal": money(session.subtotal, session.currency),
        "shipping_amount": money(session.shipping_amount, session.currency),
        "discount_amount": money(session.discount_amount, session.currency),
        "total": money(session.total, session.currency),
        "shipping": {
            "name": session.shipping_name,
            "phone": session.shipping_phone,
            "email": session.shipping_email,
            "address1": session.shipping_address1,
            "address2": session.shipping_address2,
            "city": session.shipping_city,
            "region": session.shipping_region,
            "country": session.shipping_country,
            "postal_code": session.postal_code,
        },
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "placed_at": session.placed_at,
    }


class CustomerCartCheckoutAPIView(CustomerAPIView):
    def post(self, request):
        try:
            cart = get_active_cart(request.user)
            existed = CheckoutSession.objects.filter(cart=cart).exists()
            session = create_cart_checkout(cart=cart, actor=request.user, request=request)
            return Response(_checkout_data(session), status=200 if existed else 201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, default_code="invalid_state", http_status=409)


class CustomerCheckoutDetailAPIView(CustomerAPIView):
    def _session(self, request, checkout_id):
        return get_object_or_404(CheckoutSession, pk=checkout_id, customer=request.user)

    def get(self, request, checkout_id):
        session = self._session(request, checkout_id)
        if session.cart_id and session.status == CheckoutSession.Status.DRAFT:
            try:
                session = create_cart_checkout(cart=session.cart, actor=request.user, request=request)
            except (DjangoValidationError, DjangoPermissionDenied) as exc:
                return _domain_error(request, exc)
        return Response(_checkout_data(session))

    def patch(self, request, checkout_id):
        session = self._session(request, checkout_id)
        allowed = {"shipping_name", "shipping_phone", "shipping_email", "shipping_address1", "shipping_address2", "shipping_city", "shipping_region", "shipping_country", "postal_code"}
        unexpected = set(request.data) - allowed
        if unexpected:
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={key: ["This field is not writable."] for key in sorted(unexpected)})
        try:
            session = update_checkout_shipping(session=session, actor=request.user, request=request, **request.data)
            return Response(_checkout_data(session))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _domain_error(request, exc, default_code="invalid_state" if session.status != CheckoutSession.Status.DRAFT else "validation_error", http_status=409 if session.status != CheckoutSession.Status.DRAFT else 400)


def _idempotency_storage_key(user_id, checkout_id, raw_key):
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:40]
    return f"cv1-{user_id}-{checkout_id}-{digest}"[:80]


def _payment_data(attempt):
    client_secret = ""
    if isinstance(attempt.provider_payload, dict):
        client_secret = str(attempt.provider_payload.get("client_secret", "") or "")
    return {
        "provider": attempt.provider,
        "status": attempt.status,
        "redirect_url": attempt.redirect_url or None,
        "client_secret": client_secret or None,
    }


PURCHASE_STATUS_AR = {
    "pending_payment": "بانتظار الدفع",
    "confirmed": "تم التأكيد",
    "payment_failed": "فشل الدفع",
    "cancelled": "ملغي",
    "refunded": "مسترد",
}
FULFILLMENT_STATUS_AR = {
    "processing": "قيد التجهيز",
    "waiting_production": "بانتظار الإنتاج",
    "ready_to_pack": "جاهز للتعبئة",
    "packed": "تمت التعبئة",
    "shipped": "تم الشحن",
    "partially_shipped": "تم شحن جزء من الطلب",
    "delivered": "تم التسليم",
    "partially_delivered": "تم تسليم جزء من الطلب",
    "failed": "تعذر التسليم",
    "returned": "مرتجع",
    "cancelled": "ملغي",
    "partially_cancelled": "تم إلغاء جزء من الطلب",
    "refunded": "مسترد",
}


def _status_label(request, value, english):
    if request_language(request) == "ar":
        return PURCHASE_STATUS_AR.get(value) or FULFILLMENT_STATUS_AR.get(value) or english
    return english


def _fulfillment_data(fulfillment, request):
    if not fulfillment:
        return {"status": "processing", "label": _status_label(request, "processing", "Processing"), "carrier": None, "tracking_number": None, "tracking_url": None, "packed_at": None, "shipped_at": None, "delivered_at": None}
    return {
        "status": fulfillment.status,
        "label": _status_label(request, fulfillment.status, fulfillment.get_status_display()),
        "carrier": fulfillment.carrier or None,
        "tracking_number": fulfillment.tracking_number or None,
        "tracking_url": fulfillment.tracking_url or None,
        "packed_at": fulfillment.packed_at,
        "shipped_at": fulfillment.shipped_at,
        "delivered_at": fulfillment.delivered_at,
    }


def _purchase_item_data(order, request):
    current_title = localized(request, order.item.store_product.title_en, order.item.store_product.title_ar)
    return {
        "reference": str(order.number),
        "title": current_title or order.item.title,
        "sku": order.item.sku,
        "size": order.item.size,
        "color_name": order.item.color_name,
        "quantity": order.item.quantity,
        "unit_price": money(order.item.unit_price, order.currency),
        "line_total": money(order.item.line_total, order.currency),
        "status": order.status,
        "status_label": _status_label(request, order.status, order.get_status_display()),
        "customized": bool(order.item.studio_project_id),
        "studio_project_id": order.item.studio_project_id,
        "fulfillment": _fulfillment_data(getattr(order, "fulfillment", None), request),
    }


def _purchase_queryset(user):
    return (
        CustomerPurchase.objects.filter(customer=user)
        .prefetch_related(
            "payment_attempts",
            "child_orders__item__store_product",
            "child_orders__fulfillment",
        )
        .order_by("-created_at", "-id")
    )


def _purchase_data(purchase, request, *, detail=False):
    attempts = list(purchase.payment_attempts.all())
    attempt = attempts[0] if attempts else None
    data = {
        "reference": str(purchase.number),
        "status": purchase.status,
        "status_label": _status_label(request, purchase.status, purchase.get_status_display()),
        "fulfillment_status": purchase.fulfillment_status,
        "fulfillment_status_label": _status_label(request, purchase.fulfillment_status, purchase.fulfillment_status.replace("_", " ").title()),
        "payment": {"method": purchase.payment_method, "status": attempt.status if attempt else None},
        "subtotal": money(purchase.subtotal, purchase.currency),
        "shipping_amount": money(purchase.shipping_amount, purchase.currency),
        "discount_amount": money(purchase.discount_amount, purchase.currency),
        "total": money(purchase.total, purchase.currency),
        "item_count": purchase.child_orders.count(),
        "created_at": purchase.created_at,
        "confirmed_at": purchase.confirmed_at,
    }
    if detail:
        data["shipping"] = purchase.shipping_snapshot
        data["items"] = [_purchase_item_data(order, request) for order in purchase.child_orders.all()]
    return data


class CustomerPlaceCheckoutAPIView(CustomerScopedAPIView):
    throttle_scope = "customer_place"

    def post(self, request, checkout_id):
        session = get_object_or_404(CheckoutSession, pk=checkout_id, customer=request.user)
        raw_key = str(request.headers.get("Idempotency-Key", "") or "").strip()
        if not IDEMPOTENCY_PATTERN.match(raw_key):
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"Idempotency-Key": ["Use 8-80 characters: letters, digits, dot, underscore, colon or hyphen."]})
        payment_method = str(request.data.get("payment_method", "") or "").strip().lower()
        if payment_method not in CustomerPurchase.PaymentMethod.values:
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"payment_method": ["Unsupported payment method."]})
        storage_key = _idempotency_storage_key(request.user.pk, session.pk, raw_key)

        replay = PaymentAttempt.objects.filter(idempotency_key=storage_key, purchase__checkout=session).select_related("purchase").first()
        if replay:
            if replay.provider != payment_method:
                return api_error(request, "conflict", _error_message(request, "conflict"), http_status=409)
            purchase = _purchase_queryset(request.user).get(pk=replay.purchase_id)
            return Response({"idempotent_replay": True, "purchase": _purchase_data(purchase, request, detail=True), "payment": _payment_data(replay)}, status=200)
        if session.status != CheckoutSession.Status.DRAFT:
            return api_error(request, "conflict", _error_message(request, "conflict"), http_status=409)

        try:
            if session.cart_id:
                purchase, attempt = place_cart_purchase(session=session, actor=request.user, payment_method=payment_method, request=request, payment_attempt_idempotency_key=storage_key)
            else:
                order, attempt = place_order(session=session, actor=request.user, payment_method=payment_method, request=request, payment_attempt_idempotency_key=storage_key)
                purchase = order.purchase
            if attempt.provider != CustomerPurchase.PaymentMethod.COD and attempt.status in {PaymentAttempt.Status.PENDING, PaymentAttempt.Status.FAILED}:
                initiate_online_payment(attempt=attempt)
            purchase = _purchase_queryset(request.user).get(pk=purchase.pk)
            attempt.refresh_from_db()
            return Response({"idempotent_replay": False, "purchase": _purchase_data(purchase, request, detail=True), "payment": _payment_data(attempt)}, status=201)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            replay = PaymentAttempt.objects.filter(idempotency_key=storage_key, purchase__checkout=session).select_related("purchase").first()
            if replay and replay.provider == payment_method:
                purchase = _purchase_queryset(request.user).get(pk=replay.purchase_id)
                return Response({"idempotent_replay": True, "purchase": _purchase_data(purchase, request, detail=True), "payment": _payment_data(replay)}, status=200)
            message = " ".join(getattr(exc, "messages", [str(exc)])).lower()
            code = "payment_error" if "payment" in message or "provider" in message else "invalid_state"
            http_status = 503 if "provider" in message and "failed" in message else 409
            return _domain_error(request, exc, default_code=code, http_status=http_status)


class CustomerPaymentOptionsAPIView(CustomerAPIView):
    def get(self, request):
        rows = []
        labels = {
            "cod": ("Cash on Delivery", "الدفع عند الاستلام"),
            "paymob": ("Paymob", "Paymob"),
            "stripe": ("Stripe", "Stripe"),
        }
        for provider in CustomerPurchase.PaymentMethod.values:
            try:
                cfg = IntegrationConfig.objects.get(provider=provider)
            except IntegrationConfig.DoesNotExist:
                continue
            available = cfg.enabled and (provider == CustomerPurchase.PaymentMethod.COD or cfg.last_test_status == IntegrationConfig.TestStatus.SUCCESS)
            if available:
                en, ar = labels[provider]
                rows.append({"provider": provider, "label": localized(request, en, ar)})
        return Response({"results": rows})


class CustomerPurchaseListAPIView(CustomerAPIView):
    def get(self, request):
        qs = _purchase_queryset(request.user)
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_purchase_data(purchase, request) for purchase in page])


class CustomerPurchaseDetailAPIView(CustomerAPIView):
    def get(self, request, purchase_reference):
        purchase = get_object_or_404(_purchase_queryset(request.user), number=purchase_reference)
        return Response(_purchase_data(purchase, request, detail=True))


def _notification_target(notification):
    match = re.fullmatch(r"/purchases/(\d+)/", str(notification.destination or ""))
    if match:
        purchase = CustomerPurchase.objects.filter(pk=int(match.group(1)), customer=notification.recipient).only("number").first()
        if purchase:
            return {"resource": "purchase", "reference": str(purchase.number)}
    match = re.fullmatch(r"/orders/(\d+)/", str(notification.destination or ""))
    if match:
        from apps.checkout.models import CustomerOrder
        order = CustomerOrder.objects.filter(pk=int(match.group(1)), customer=notification.recipient).select_related("purchase").first()
        if order and order.purchase_id:
            return {"resource": "purchase", "reference": str(order.purchase.number)}
    return None


def _notification_data(notification, request):
    return {
        "id": notification.pk,
        "type": notification.type,
        "title": localized(request, notification.title_en, notification.title_ar),
        "body": localized(request, notification.body_en, notification.body_ar),
        "is_read": notification.is_read,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
        "target": _notification_target(notification),
    }


class CustomerNotificationListAPIView(CustomerAPIView):
    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user).order_by("-created_at", "-id")
        paginator = CustomerPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_notification_data(item, request) for item in page])


class CustomerNotificationReadAPIView(CustomerAPIView):
    def post(self, request, notification_id):
        notification = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return Response(_notification_data(notification, request))


class CustomerNotificationReadAllAPIView(CustomerAPIView):
    def post(self, request):
        now = timezone.now()
        updated = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=now)
        return Response({"updated": updated})


class NotificationPreferenceInputSerializer(serializers.Serializer):
    email_enabled = serializers.BooleanField(required=False)
    sms_enabled = serializers.BooleanField(required=False)
    phone_e164 = serializers.CharField(required=False, allow_blank=True, max_length=24)


class CustomerNotificationPreferenceAPIView(CustomerAPIView):
    def _data(self, preference):
        return {"email_enabled": preference.email_enabled, "sms_enabled": preference.sms_enabled, "phone_e164": preference.phone_e164}

    def get(self, request):
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(self._data(preference))

    def patch(self, request):
        serializer = NotificationPreferenceInputSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields=_validation_fields(serializer.errors))
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        for key, value in serializer.validated_data.items():
            setattr(preference, key, value)
        if preference.sms_enabled and not preference.phone_e164.startswith("+"):
            return api_error(request, "validation_error", _error_message(request, "validation_error"), fields={"phone_e164": ["SMS phone must use E.164 format."]})
        preference.save()
        return Response(self._data(preference))
