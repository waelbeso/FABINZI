from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.integrations.models import IntegrationConfig
from apps.storefront.models import ProductVariant, StoreProduct, StudioProject
from .models import CartItem, CheckoutSession, CustomerOrder, CustomerPurchase
from .services import (
    add_cart_item,
    create_cart_checkout,
    create_checkout,
    get_active_cart,
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


def _cart_context(cart):
    items = cart.items.select_related(
        "store_product",
        "store_product__storefront",
        "variant",
        "studio_project",
    ).prefetch_related("store_product__images__media_asset")
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
    configs = {
        cfg.provider: cfg
        for cfg in IntegrationConfig.objects.filter(
            provider__in=[
                IntegrationConfig.Provider.COD,
                IntegrationConfig.Provider.PAYMOB,
                IntegrationConfig.Provider.STRIPE,
            ],
            enabled=True,
        )
    }
    methods = []
    if IntegrationConfig.Provider.COD in configs:
        methods.append(("cod", "Cash on Delivery", "الدفع عند الاستلام"))
    # Browser online-payment widgets are intentionally not exposed until their
    # provider-specific redirect/client-secret UX is complete. The API remains intact.
    return methods


@login_required
@require_POST
def add_product_to_cart(request, product_id):
    product = get_object_or_404(
        StoreProduct.objects.select_related("storefront", "designed_product").prefetch_related("designed_product__placements"),
        pk=product_id,
        status=StoreProduct.Status.PUBLISHED,
        storefront__status=StoreProduct.Status.PUBLISHED,
    )
    variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant"), product=product, is_active=True)
    quantity = _positive_int(request.POST.get("quantity"))
    kind = CartItem.Kind.READY_DESIGNED if product.designed_product.placements.exists() else CartItem.Kind.PLAIN
    try:
        add_cart_item(
            customer=request.user,
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


@login_required
def cart(request):
    active_cart = get_active_cart(request.user)
    return render(request, "checkout/cart.html", _cart_context(active_cart))


@login_required
@require_POST
def cart_item_update(request, pk):
    item = get_object_or_404(CartItem.objects.select_related("cart", "store_product", "variant", "studio_project"), pk=pk)
    try:
        require_cart_owner(request.user, item.cart)
        update_cart_item(item=item, actor=request.user, quantity=_positive_int(request.POST.get("quantity")), request=request)
        messages.success(request, _localized(request, "Cart updated.", "تم تحديث السلة."))
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("cart")


@login_required
@require_POST
def cart_item_remove(request, pk):
    item = get_object_or_404(CartItem.objects.select_related("cart"), pk=pk)
    try:
        remove_cart_item(item=item, actor=request.user, request=request)
        messages.success(request, _localized(request, "Item removed from Cart.", "تم حذف المنتج من السلة."))
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("cart")


@login_required
def cart_checkout_start(request):
    active_cart = get_active_cart(request.user)
    try:
        session = create_cart_checkout(cart=active_cart, actor=request.user, request=request)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
        return redirect("cart")
    return redirect("checkout-detail", pk=session.pk)


@login_required
def checkout_start(request, project_id):
    project = get_object_or_404(StudioProject, pk=project_id)
    try:
        session = create_checkout(project=project, actor=request.user, request=request)
    except (ValidationError, PermissionDenied) as exc:
        return render(request, "checkout/error.html", {"error": str(exc)}, status=400)
    return redirect("checkout-detail", pk=session.pk)


@login_required
def checkout_detail(request, pk):
    session = get_object_or_404(
        CheckoutSession.objects.select_related(
            "cart",
            "studio_project__product",
            "studio_project__variant",
        ),
        pk=pk,
    )
    try:
        require_checkout_owner(request.user, session)
    except PermissionDenied:
        return render(
            request,
            "checkout/error.html",
            {"error": _localized(request, "Checkout access denied.", "غير مسموح بالوصول إلى صفحة الدفع.")},
            status=403,
        )

    if request.method == "POST":
        try:
            update_checkout_shipping(
                session=session,
                actor=request.user,
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
                method = request.POST.get("payment_method", "cod")
                allowed = {value for value, _, _ in _payment_methods()}
                if method not in allowed:
                    raise ValidationError(_localized(request, "Selected payment method is not currently available.", "طريقة الدفع المختارة غير متاحة حاليًا."))
                if session.cart_id:
                    purchase, _ = place_cart_purchase(
                        session=session,
                        actor=request.user,
                        payment_method=method,
                        request=request,
                    )
                    return redirect("purchase-confirmation", pk=purchase.pk)
                order, _ = place_order(
                    session=session,
                    actor=request.user,
                    payment_method=method,
                    request=request,
                )
                return redirect("order-detail", pk=order.pk)
            messages.success(request, _localized(request, "Delivery details saved.", "تم حفظ بيانات التوصيل."))
        except (ValidationError, PermissionDenied) as exc:
            return render(
                request,
                "checkout/detail.html",
                {
                    "checkout": session,
                    "lines": _checkout_lines(session),
                    "payment_methods": _payment_methods(),
                    "error": str(exc),
                },
                status=400,
            )
    return render(
        request,
        "checkout/detail.html",
        {"checkout": session, "lines": _checkout_lines(session), "payment_methods": _payment_methods()},
    )


@login_required
def purchases(request):
    customer_purchases = CustomerPurchase.objects.filter(customer=request.user).prefetch_related("child_orders__item")
    return render(request, "checkout/purchases.html", {"purchases": customer_purchases})


@login_required
def purchase_confirmation(request, pk):
    purchase = get_object_or_404(
        CustomerPurchase.objects.prefetch_related("child_orders__item__store_product", "child_orders__item__variant"),
        pk=pk,
    )
    try:
        require_purchase_owner(request.user, purchase)
    except PermissionDenied:
        return render(request, "checkout/error.html", {"error": _localized(request, "Order access denied.", "غير مسموح بالوصول إلى هذا الطلب.")}, status=403)
    return render(request, "checkout/purchase_confirmation.html", {"purchase": purchase})


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        CustomerPurchase.objects.select_related("checkout").prefetch_related(
            "child_orders__item__store_product__storefront",
            "child_orders__item__variant",
            "child_orders__fulfillment",
        ),
        pk=pk,
    )
    try:
        require_purchase_owner(request.user, purchase)
    except PermissionDenied:
        return render(request, "checkout/error.html", {"error": _localized(request, "Order access denied.", "غير مسموح بالوصول إلى هذا الطلب.")}, status=403)
    return render(request, "checkout/purchase_detail.html", {"purchase": purchase})


@login_required
def orders(request):
    # Customer-facing "Orders" now means the commercial parent purchase.
    return purchases(request)


@login_required
def order_detail(request, pk):
    order = get_object_or_404(CustomerOrder.objects.select_related("item", "purchase"), pk=pk)
    if order.customer_id != request.user.pk and not request.user.is_staff:
        return render(request, "checkout/error.html", {"error": _localized(request, "Order access denied.", "غير مسموح بالوصول إلى هذا الطلب.")}, status=403)
    return render(request, "checkout/order_detail.html", {"order": order})
