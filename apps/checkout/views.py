import re
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.guest_identity import GUEST_SESSION_KEY, ensure_guest_identity
from apps.integrations.models import IntegrationConfig
from apps.storefront.models import ProductVariant, StoreProduct, Storefront, StudioProject
from apps.storefront.services import validate_studio_project
from .models import Cart, CartItem, CheckoutSession, CustomerOrder, CustomerPurchase
from .signals import PENDING_GUEST_CART_MERGE_KEY
from .services import (
    GuestCartMergeConflict,
    add_cart_item,
    create_cart_checkout,
    create_checkout,
    get_active_cart,
    get_guest_purchase_from_token,
    guest_key_hash,
    make_guest_purchase_token,
    merge_guest_cart_into_customer,
    place_cart_purchase,
    place_order,
    remove_cart_item,
    require_cart_owner,
    require_checkout_owner,
    require_purchase_owner,
    update_cart_item,
    update_checkout_shipping,
)


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _positive_int(value, default=1):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _guest_identity(request):
    return ensure_guest_identity(request)


def _private_context(**values):
    return {
        "private_surface": True,
        "seo_canonical": f"{settings.FABINZI_PUBLIC_BASE_URL.rstrip('/')}/",
        "seo_hreflang": None,
        "seo_base_json_ld": "",
        "page_seo": None,
        **values,
    }


def _rate_parts(rate):
    match = re.fullmatch(r"(\d+)/(second|minute|hour|day)", str(rate or ""))
    if not match:
        return None
    count = int(match.group(1))
    seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[match.group(2)]
    return count, seconds


def _enforce_web_rate(request, scope):
    rates = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
    rate = rates.get("customer_place" if scope == "place" else "anon")
    parts = _rate_parts(rate)
    if not parts:
        return
    limit, window = parts
    if request.user.is_authenticated:
        subject = f"user:{request.user.pk}"
    else:
        subject = f"guest:{guest_key_hash(_guest_identity(request))}"
    key = f"v2-6-web-rate:{scope}:{subject}"
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, timeout=window)
        return
    if int(current) >= limit:
        raise PermissionDenied("Too many requests. Please try again later.")
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, int(current) + 1, timeout=window)


def _cart_context(cart):
    items = cart.items.select_related("store_product", "store_product__storefront", "variant", "studio_project").prefetch_related("store_product__images__media_asset")
    lines = []
    subtotal = Decimal("0.00")
    currency = None
    for item in items:
        unit_price = item.variant.price
        line_total = unit_price * item.quantity
        subtotal += line_total
        currency = currency or item.store_product.currency
        lines.append({"item": item, "unit_price": unit_price, "line_total": line_total})
    return {"cart": cart, "lines": lines, "subtotal": subtotal, "total": subtotal, "currency": currency or "EGP"}


def _checkout_lines(session):
    if session.cart_id:
        return _cart_context(session.cart)["lines"]
    project = session.studio_project
    if not project:
        return []
    return [{"item": None, "project": project, "unit_price": project.variant.price, "line_total": project.variant.price * project.quantity}]


def _payment_methods():
    configs = {cfg.provider: cfg for cfg in IntegrationConfig.objects.filter(provider__in=[IntegrationConfig.Provider.COD], enabled=True)}
    methods = []
    if IntegrationConfig.Provider.COD in configs:
        methods.append(("cod", "Cash on Delivery", "الدفع عند الاستلام"))
    return methods


def _first_studio_needing_attention(*, cart=None, session=None):
    if session is not None:
        if session.cart_id:
            cart = session.cart
        elif session.studio_project_id:
            project = session.studio_project
            if project.status != StudioProject.Status.READY:
                return project
            try:
                validate_studio_project(project)
            except ValidationError:
                return project
            return None
    if cart is None:
        return None
    items = cart.items.filter(kind=CartItem.Kind.STUDIO).select_related("studio_project")
    for item in items:
        project = item.studio_project
        if not project or project.status != StudioProject.Status.READY:
            return project
        try:
            validate_studio_project(project)
        except ValidationError:
            return project
    return None


def _studio_attention_message(request):
    return _localized(
        request,
        "A saved customization needs attention before checkout. Open its Studio project from Cart, correct it, mark it Ready again, then retry checkout.",
        "يوجد تخصيص محفوظ يحتاج إلى مراجعة قبل الدفع. افتح مشروع Studio من السلة، صحّحه، واجعله جاهزاً مرة أخرى ثم أعد محاولة الدفع.",
    )


@require_POST
def add_product_to_cart(request, product_id):
    product = get_object_or_404(
        StoreProduct.objects.select_related("storefront", "designed_product").prefetch_related("designed_product__placements"),
        pk=product_id,
        status=StoreProduct.Status.PUBLISHED,
        storefront__status=Storefront.Status.PUBLISHED,
    )
    variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant"), product=product, is_active=True)
    quantity = _positive_int(request.POST.get("quantity"))
    kind = CartItem.Kind.READY_DESIGNED if product.designed_product.placements.exists() else CartItem.Kind.PLAIN
    guest_identity = None if request.user.is_authenticated else _guest_identity(request)
    try:
        add_cart_item(
            customer=request.user if request.user.is_authenticated else None,
            guest_identity=guest_identity,
            product=product,
            variant=variant,
            quantity=quantity,
            kind=kind,
            request=request,
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
        return redirect("public-store-product", store_slug=product.storefront.slug, product_slug=product.slug)
    messages.success(request, _localized(request, "Added to Cart.", "تمت الإضافة إلى السلة."))
    return redirect("cart")


def cart(request):
    guest_identity = None if request.user.is_authenticated else _guest_identity(request)
    active_cart = get_active_cart(request.user if request.user.is_authenticated else None, guest_identity=guest_identity)
    context = _cart_context(active_cart)
    pending = None
    if request.user.is_authenticated and request.session.get(PENDING_GUEST_CART_MERGE_KEY):
        retained_identity = request.session.get(GUEST_SESSION_KEY)
        if retained_identity:
            pending = Cart.objects.filter(
                customer__isnull=True,
                guest_key_hash=guest_key_hash(retained_identity),
                status=Cart.Status.ACTIVE,
            ).first()
    context["pending_guest_merge"] = request.session.get(PENDING_GUEST_CART_MERGE_KEY)
    context["pending_guest_cart"] = pending
    context["pending_guest_lines"] = _cart_context(pending)["lines"] if pending else []
    return render(request, "checkout/cart.html", _private_context(**context))


@require_POST
def cart_item_update(request, pk):
    item = get_object_or_404(CartItem.objects.select_related("cart", "store_product", "variant", "studio_project"), pk=pk)
    guest_identity = request.session.get(GUEST_SESSION_KEY)
    try:
        require_cart_owner(request.user, item.cart, guest_identity=guest_identity)
        update_cart_item(item=item, actor=request.user, guest_identity=guest_identity, quantity=_positive_int(request.POST.get("quantity")), request=request)
        messages.success(request, _localized(request, "Cart updated.", "تم تحديث السلة."))
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("cart")


@require_POST
def cart_item_remove(request, pk):
    item = get_object_or_404(CartItem.objects.select_related("cart"), pk=pk)
    guest_identity = request.session.get(GUEST_SESSION_KEY)
    try:
        remove_cart_item(item=item, actor=request.user, guest_identity=guest_identity, request=request)
        messages.success(request, _localized(request, "Item removed from Cart.", "تم حذف المنتج من السلة."))
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("cart")


@login_required
@require_POST
def retry_guest_cart_merge(request):
    guest_identity = request.session.get(GUEST_SESSION_KEY)
    if not guest_identity:
        request.session.pop(PENDING_GUEST_CART_MERGE_KEY, None)
        return redirect("cart")
    try:
        merge_guest_cart_into_customer(guest_identity=guest_identity, customer=request.user, request=request)
    except GuestCartMergeConflict as exc:
        request.session[PENDING_GUEST_CART_MERGE_KEY] = {"message": " ".join(exc.messages)}
        messages.error(request, _localized(request, "The carts still cannot be merged safely. Review both carts and try again.", "لا يزال دمج السلّتين غير ممكن بأمان. راجع السلّتين ثم حاول مرة أخرى."))
        return redirect("cart")
    request.session.pop(PENDING_GUEST_CART_MERGE_KEY, None)
    request.session.pop(GUEST_SESSION_KEY, None)
    messages.success(request, _localized(request, "Guest Cart merged into your account Cart.", "تم دمج سلة الضيف في سلة حسابك."))
    return redirect("cart")


def cart_checkout_start(request):
    if request.user.is_authenticated and request.session.get(PENDING_GUEST_CART_MERGE_KEY):
        messages.error(request, _localized(request, "Resolve the retained Guest Cart before checkout.", "يرجى حل سلة الضيف المحفوظة قبل إتمام الشراء."))
        return redirect("cart")
    guest_identity = None if request.user.is_authenticated else _guest_identity(request)
    active_cart = get_active_cart(request.user if request.user.is_authenticated else None, guest_identity=guest_identity)
    try:
        session = create_cart_checkout(cart=active_cart, actor=request.user, guest_identity=guest_identity, request=request)
    except (ValidationError, PermissionDenied) as exc:
        if _first_studio_needing_attention(cart=active_cart):
            messages.error(request, _studio_attention_message(request))
        else:
            messages.error(request, str(exc))
        return redirect("cart")
    return redirect("checkout-detail", pk=session.pk)


@login_required
def checkout_start(request, project_id):
    project = get_object_or_404(StudioProject, pk=project_id)
    try:
        session = create_checkout(project=project, actor=request.user, request=request)
    except (ValidationError, PermissionDenied) as exc:
        return render(request, "checkout/error.html", _private_context(error=str(exc), studio_attention_project=project), status=400)
    return redirect("checkout-detail", pk=session.pk)


def checkout_detail(request, pk):
    session = get_object_or_404(CheckoutSession.objects.select_related("cart", "studio_project__product", "studio_project__variant"), pk=pk)
    guest_identity = request.session.get(GUEST_SESSION_KEY) if session.customer_id is None else None
    try:
        require_checkout_owner(request.user, session, guest_identity=guest_identity)
    except PermissionDenied:
        return render(request, "checkout/error.html", _private_context(error=_localized(request, "Checkout access denied.", "غير مسموح بالوصول إلى صفحة الدفع.")), status=403)

    if request.method == "POST":
        try:
            update_checkout_shipping(
                session=session,
                actor=request.user,
                guest_identity=guest_identity,
                request=request,
                shipping_name=request.POST.get("shipping_name", ""),
                shipping_phone=request.POST.get("shipping_phone", ""),
                shipping_email=request.POST.get("shipping_email", ""),
                shipping_address1=request.POST.get("shipping_address1", ""),
                shipping_address2=request.POST.get("shipping_address2", ""),
                shipping_city=request.POST.get("shipping_city", ""),
                shipping_region=request.POST.get("shipping_region", ""),
                shipping_country=request.POST.get("shipping_country", "EG").upper(),
                postal_code=request.POST.get("postal_code", ""),
            )
            session.refresh_from_db()
            if request.POST.get("action") == "place":
                _enforce_web_rate(request, "place")
                method = request.POST.get("payment_method", "cod")
                allowed = {value for value, _, _ in _payment_methods()}
                if method not in allowed:
                    raise ValidationError(_localized(request, "Selected payment method is not currently available for Web checkout.", "طريقة الدفع المختارة غير متاحة حاليًا للدفع عبر الويب."))
                if session.cart_id:
                    purchase, _ = place_cart_purchase(
                        session=session,
                        actor=request.user,
                        guest_identity=guest_identity,
                        payment_method=method,
                        request=request,
                    )
                    if purchase.customer_id is None:
                        token = make_guest_purchase_token(purchase)
                        return redirect("guest-purchase-confirmation", token=token)
                    return redirect("purchase-confirmation", pk=purchase.pk)
                order, _ = place_order(session=session, actor=request.user, payment_method=method, request=request)
                return redirect("order-detail", pk=order.pk)
            messages.success(request, _localized(request, "Delivery details saved.", "تم حفظ بيانات التوصيل."))
        except (ValidationError, PermissionDenied) as exc:
            session.refresh_from_db()
            attention = _first_studio_needing_attention(session=session)
            return render(
                request,
                "checkout/detail.html",
                _private_context(
                    checkout=session,
                    lines=_checkout_lines(session),
                    payment_methods=_payment_methods(),
                    error=_studio_attention_message(request) if attention else str(exc),
                    studio_attention_project=attention,
                    is_guest=session.customer_id is None,
                ),
                status=400,
            )
    return render(request, "checkout/detail.html", _private_context(checkout=session, lines=_checkout_lines(session), payment_methods=_payment_methods(), is_guest=session.customer_id is None))


@login_required
def purchases(request):
    customer_purchases = CustomerPurchase.objects.filter(customer=request.user).prefetch_related("child_orders__item")
    return render(request, "checkout/purchases.html", _private_context(purchases=customer_purchases))


@login_required
def purchase_confirmation(request, pk):
    purchase = get_object_or_404(CustomerPurchase.objects.prefetch_related("child_orders__item__store_product", "child_orders__item__variant"), pk=pk)
    try:
        require_purchase_owner(request.user, purchase)
    except PermissionDenied:
        return render(request, "checkout/error.html", _private_context(error=_localized(request, "Order access denied.", "غير مسموح بالوصول إلى هذا الطلب.")), status=403)
    return render(request, "checkout/purchase_confirmation.html", _private_context(purchase=purchase, guest_access=False))


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(CustomerPurchase.objects.select_related("checkout").prefetch_related("child_orders__item__store_product__storefront", "child_orders__item__variant", "child_orders__fulfillment"), pk=pk)
    try:
        require_purchase_owner(request.user, purchase)
    except PermissionDenied:
        return render(request, "checkout/error.html", _private_context(error=_localized(request, "Order access denied.", "غير مسموح بالوصول إلى هذا الطلب.")), status=403)
    return render(request, "checkout/purchase_detail.html", _private_context(purchase=purchase, guest_access=False))


def _guest_purchase_or_404(request, token):
    if request.user.is_authenticated:
        raise Http404("Purchase not found")
    try:
        _enforce_web_rate(request, "guest_access")
        return get_guest_purchase_from_token(token)
    except PermissionDenied as exc:
        raise Http404("Purchase not found") from exc


def guest_purchase_confirmation(request, token):
    purchase = _guest_purchase_or_404(request, token)
    purchase = CustomerPurchase.objects.prefetch_related("child_orders__item__store_product", "child_orders__item__variant").get(pk=purchase.pk)
    return render(request, "checkout/purchase_confirmation.html", _private_context(purchase=purchase, guest_access=True, guest_purchase_token=token))


def guest_purchase_detail(request, token):
    purchase = _guest_purchase_or_404(request, token)
    purchase = CustomerPurchase.objects.select_related("checkout").prefetch_related("child_orders__item__store_product__storefront", "child_orders__item__variant", "child_orders__fulfillment").get(pk=purchase.pk)
    return render(request, "checkout/purchase_detail.html", _private_context(purchase=purchase, guest_access=True, guest_purchase_token=token))


@login_required
def orders(request):
    return purchases(request)


@login_required
def order_detail(request, pk):
    order = get_object_or_404(CustomerOrder.objects.select_related("item", "purchase"), pk=pk)
    if order.customer_id != request.user.pk and not request.user.is_staff:
        return render(request, "checkout/error.html", _private_context(error=_localized(request, "Order access denied.", "غير مسموح بالوصول إلى هذا الطلب.")), status=403)
    return render(request, "checkout/order_detail.html", _private_context(order=order))
