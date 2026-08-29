import hashlib
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integrations.models import IntegrationConfig
from apps.platform_ops.public_urls import absolute_public_url
from apps.storefront.models import ProductVariant, StoreProduct, StudioProject
from .gateways import get_payment_config, parse_webhook, verify_paymob_signature, verify_stripe_signature
from .models import CartItem, CheckoutSession, CustomerOrder, CustomerPurchase
from .services import _cart_pricing, add_cart_item, create_cart_checkout, create_checkout, get_active_cart, initiate_online_payment, place_cart_purchase, place_order, process_webhook, remove_cart_item, require_cart_owner, require_checkout_owner, require_purchase_owner, update_cart_item, update_checkout_shipping


def _err(exc):
    return Response({"detail": str(exc)}, status=403 if isinstance(exc, PermissionDenied) else 400)


def _checkout_data(session):
    return {"id": session.pk, "status": session.status, "cart": session.cart_id, "studio_project": session.studio_project_id, "subtotal": session.subtotal, "shipping_amount": session.shipping_amount, "discount_amount": session.discount_amount, "total": session.total, "currency": session.currency, "shipping": {"name": session.shipping_name, "phone": session.shipping_phone, "email": session.shipping_email, "address1": session.shipping_address1, "address2": session.shipping_address2, "city": session.shipping_city, "region": session.shipping_region, "country": session.shipping_country, "postal_code": session.postal_code}}


def _order_data(order):
    return {"id": order.pk, "number": str(order.number), "status": order.status, "payment_method": order.payment_method, "total": order.total, "currency": order.currency, "created_at": order.created_at, "purchase_id": order.purchase_id}


def _cart_item_data(item):
    return {"id": item.pk, "kind": item.kind, "product": {"id": item.store_product_id, "slug": item.store_product.slug, "title_en": item.store_product.title_en, "title_ar": item.store_product.title_ar}, "variant": {"id": item.variant_id, "sku": item.variant.sku, "size": item.variant.size, "color_name": item.variant.color_name}, "studio_project": item.studio_project_id, "quantity": item.quantity, "unit_price": item.variant.price, "line_total": item.variant.price * item.quantity, "currency": item.store_product.currency}


def _cart_data(cart):
    items = list(cart.items.select_related("store_product", "variant", "studio_project"))
    if not items:
        return {"id": cart.pk, "status": cart.status, "items": [], "item_count": 0, "subtotal": Decimal("0.00"), "shipping_amount": Decimal("0.00"), "discount_amount": Decimal("0.00"), "total": Decimal("0.00"), "currency": None}
    lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    return {"id": cart.pk, "status": cart.status, "items": [_cart_item_data(line["item"]) for line in lines], "item_count": len(lines), "subtotal": subtotal, "shipping_amount": shipping, "discount_amount": discount, "total": total, "currency": currency}


def _purchase_item_data(order):
    fulfillment = getattr(order, "fulfillment", None)
    return {"title": order.item.title, "sku": order.item.sku, "size": order.item.size, "color_name": order.item.color_name, "quantity": order.item.quantity, "unit_price": order.item.unit_price, "line_total": order.item.line_total, "currency": order.currency, "status": order.status, "fulfillment_status": getattr(fulfillment, "status", "processing"), "customized": bool(order.item.studio_project_id)}


def _purchase_data(purchase, include_items=False):
    data = {"id": purchase.pk, "number": str(purchase.number), "status": purchase.status, "fulfillment_status": purchase.fulfillment_status, "payment_method": purchase.payment_method, "subtotal": purchase.subtotal, "shipping_amount": purchase.shipping_amount, "discount_amount": purchase.discount_amount, "total": purchase.total, "currency": purchase.currency, "created_at": purchase.created_at, "confirmed_at": purchase.confirmed_at}
    if include_items:
        data["shipping"] = purchase.shipping_snapshot
        data["items"] = [_purchase_item_data(order) for order in purchase.child_orders.select_related("item", "fulfillment")]
    return data


class CartAPIView(APIView):
    def get(self, request):
        try:
            return Response(_cart_data(get_active_cart(request.user)))
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)


class CartItemCreateAPIView(APIView):
    def post(self, request):
        try:
            kind = request.data.get("kind", CartItem.Kind.PLAIN)
            quantity = int(request.data.get("quantity", 1))
            studio_project = None
            if kind == CartItem.Kind.STUDIO:
                studio_project = get_object_or_404(StudioProject.objects.select_related("product", "variant"), pk=request.data.get("studio_project_id"))
                if studio_project.customer_id != request.user.pk:
                    raise PermissionDenied("Studio project does not belong to this customer.")
                product, variant = studio_project.product, studio_project.variant
                if not variant:
                    raise ValidationError("Studio project requires a selected variant.")
                if "quantity" not in request.data:
                    quantity = studio_project.quantity
            else:
                product = get_object_or_404(StoreProduct, pk=request.data.get("product_id"))
                variant = get_object_or_404(ProductVariant, pk=request.data.get("variant_id"))
            item = add_cart_item(customer=request.user, product=product, variant=variant, quantity=quantity, kind=kind, studio_project=studio_project, request=request)
            return Response(_cart_data(item.cart), status=201)
        except (ValidationError, PermissionDenied, TypeError, ValueError) as exc:
            return _err(exc)


class CartItemDetailAPIView(APIView):
    def patch(self, request, item_id):
        item = get_object_or_404(CartItem.objects.select_related("cart", "store_product", "variant", "studio_project"), pk=item_id)
        try:
            require_cart_owner(request.user, item.cart)
            update_cart_item(item=item, actor=request.user, quantity=request.data.get("quantity"), request=request)
            return Response(_cart_data(item.cart))
        except (ValidationError, PermissionDenied, TypeError, ValueError) as exc:
            return _err(exc)

    def delete(self, request, item_id):
        item = get_object_or_404(CartItem.objects.select_related("cart"), pk=item_id)
        try:
            cart = item.cart
            remove_cart_item(item=item, actor=request.user, request=request)
            return Response(_cart_data(cart))
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)


class CartCheckoutAPIView(APIView):
    def post(self, request):
        try:
            cart = get_active_cart(request.user)
            return Response(_checkout_data(create_cart_checkout(cart=cart, actor=request.user, request=request)), status=201)
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)


class CheckoutCreateAPIView(APIView):
    def post(self, request, project_id):
        try:
            return Response(_checkout_data(create_checkout(project=get_object_or_404(StudioProject, pk=project_id), actor=request.user, request=request)), status=201)
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)


class CheckoutDetailAPIView(APIView):
    def get(self, request, checkout_id):
        session = get_object_or_404(CheckoutSession, pk=checkout_id)
        try:
            require_checkout_owner(request.user, session)
            if session.cart_id and session.status == CheckoutSession.Status.DRAFT:
                session = create_cart_checkout(cart=session.cart, actor=request.user, request=request)
            return Response(_checkout_data(session))
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)

    def patch(self, request, checkout_id):
        session = get_object_or_404(CheckoutSession, pk=checkout_id)
        try:
            return Response(_checkout_data(update_checkout_shipping(session=session, actor=request.user, request=request, **request.data)))
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)


class PlaceOrderAPIView(APIView):
    def post(self, request, checkout_id):
        session = get_object_or_404(CheckoutSession, pk=checkout_id)
        try:
            payment_method = request.data.get("payment_method", CustomerPurchase.PaymentMethod.COD)
            if session.cart_id:
                purchase, attempt = place_cart_purchase(session=session, actor=request.user, payment_method=payment_method, request=request)
                if attempt.provider != CustomerPurchase.PaymentMethod.COD and request.data.get("initiate", True):
                    return_url = request.data.get("return_url") or absolute_public_url(f"/purchases/{purchase.pk}/")
                    initiate_online_payment(attempt=attempt, return_url=return_url)
                return Response({"purchase": _purchase_data(purchase, include_items=True), "payment": {"id": attempt.pk, "status": attempt.status, "provider": attempt.provider, "redirect_url": attempt.redirect_url, "client_secret": attempt.provider_payload.get("client_secret", "")}}, status=201)
            order, attempt = place_order(session=session, actor=request.user, payment_method=payment_method, request=request)
            if attempt.provider != CustomerPurchase.PaymentMethod.COD and request.data.get("initiate", True):
                return_url = request.data.get("return_url") or absolute_public_url(f"/orders/{order.pk}/")
                initiate_online_payment(attempt=attempt, return_url=return_url)
            return Response({"order": _order_data(order), "purchase": _purchase_data(order.purchase, include_items=True) if order.purchase_id else None, "payment": {"id": attempt.pk, "status": attempt.status, "provider": attempt.provider, "redirect_url": attempt.redirect_url, "client_secret": attempt.provider_payload.get("client_secret", "")}}, status=201)
        except (ValidationError, PermissionDenied) as exc:
            return _err(exc)


class PurchaseListAPIView(APIView):
    def get(self, request):
        purchases = CustomerPurchase.objects.filter(customer=request.user).prefetch_related("child_orders__fulfillment")
        return Response([_purchase_data(purchase) for purchase in purchases])


class PurchaseDetailAPIView(APIView):
    def get(self, request, purchase_id):
        purchase = get_object_or_404(CustomerPurchase.objects.prefetch_related("child_orders__item", "child_orders__fulfillment"), pk=purchase_id)
        try:
            require_purchase_owner(request.user, purchase)
        except PermissionDenied as exc:
            return _err(exc)
        return Response(_purchase_data(purchase, include_items=True))


class OrderListAPIView(APIView):
    def get(self, request):
        return Response([_order_data(order) for order in CustomerOrder.objects.filter(customer=request.user)])


class OrderDetailAPIView(APIView):
    def get(self, request, order_id):
        order = get_object_or_404(CustomerOrder, pk=order_id)
        if order.customer_id != request.user.pk and not request.user.is_staff:
            return Response({"detail": "Order access denied."}, status=403)
        return Response(_order_data(order) | {"shipping": order.shipping_snapshot, "item": {"sku": order.item.sku, "title": order.item.title, "quantity": order.item.quantity, "unit_price": order.item.unit_price, "line_total": order.item.line_total}})


class PaymentOptionsAPIView(APIView):
    def get(self, request):
        rows = []
        for provider, label in CustomerPurchase.PaymentMethod.choices:
            try:
                cfg = IntegrationConfig.objects.get(provider=provider)
                available = cfg.enabled and (provider == CustomerPurchase.PaymentMethod.COD or cfg.last_test_status == IntegrationConfig.TestStatus.SUCCESS)
            except IntegrationConfig.DoesNotExist:
                available = False
            rows.append({"provider": provider, "label": label, "available": available})
        return Response(rows)


class PaymentWebhookAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, provider):
        if provider not in {"stripe", "paymob"}:
            return Response({"detail": "Unsupported provider."}, status=404)
        try:
            cfg = get_payment_config(provider)
            secrets = cfg.get_secrets()
            raw = request.body
            if provider == "stripe":
                valid = verify_stripe_signature(raw, request.headers.get("Stripe-Signature", ""), secrets.get("webhook_secret", ""))
            else:
                valid = verify_paymob_signature(raw, request.headers.get("X-FABINZI-Signature", "") or request.query_params.get("hmac", ""), secrets.get("webhook_hmac_secret", "") or secrets.get("hmac_secret", ""))
            if not valid:
                return Response({"detail": "Invalid webhook signature."}, status=400)
            payload, event_id, reference, success, failed = parse_webhook(provider, raw)
            event = process_webhook(provider=provider, event_id=event_id, payload_hash=hashlib.sha256(raw).hexdigest(), reference=reference, success=success, failed=failed, payload=payload)
            return Response({"received": True, "processed": event.processed})
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
