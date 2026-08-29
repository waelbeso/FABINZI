from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.notifications.models import Notification
from apps.storefront.models import ProductVariant, StoreProduct, StudioProject
from apps.storefront.services import _validate_available_product, require_project_owner, validate_studio_project
from .gateways import create_remote_payment, get_payment_config
from .models import Cart, CartItem, CheckoutSession, CustomerOrder, CustomerPurchase, OrderItem, PaymentAttempt, PaymentWebhookEvent


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _shipping_snapshot(session):
    return {"name": session.shipping_name, "phone": session.shipping_phone, "email": session.shipping_email, "address1": session.shipping_address1, "address2": session.shipping_address2, "city": session.shipping_city, "region": session.shipping_region, "country": session.shipping_country, "postal_code": session.postal_code}


def _customization_snapshot(project):
    if not project or not hasattr(project, "customization") or not project.customization.enabled:
        return {}
    elements = []
    for element in project.customization.elements.select_related("decoration_zone", "media_asset", "artwork_version__artwork"):
        elements.append({
            "kind": element.kind,
            "zone_id": element.decoration_zone_id,
            "text": element.text,
            "media_asset_id": element.media_asset_id,
            "artwork_version_id": element.artwork_version_id,
            "artwork_id": element.artwork_version.artwork_id if element.artwork_version_id else None,
            "production_method": element.production_method,
            "transform": element.transform,
            "style": element.style,
        })
    return {"enabled": True, "studio_project_id": project.pk, "elements": elements}


def _pricing(project):
    if project.status != StudioProject.Status.READY:
        raise ValidationError("Studio project must be Ready for checkout.")
    if not project.variant_id:
        raise ValidationError("A product variant is required for checkout.")
    validation = validate_studio_project(project)
    unit = _money(validation["unit_price"])
    subtotal = _money(unit * project.quantity)
    return unit, subtotal, Decimal("0.00"), Decimal("0.00"), subtotal


def _validate_cart_item(item):
    if item.quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    if not item.variant_id:
        raise ValidationError("A product variant is required.")
    _validate_available_product(item.store_product, item.variant, item.quantity)
    if item.kind == CartItem.Kind.STUDIO:
        project = item.studio_project
        if not project:
            raise ValidationError("Studio cart item requires a Studio project.")
        if project.customer_id != item.cart.customer_id:
            raise PermissionDenied("Studio project does not belong to this customer.")
        if project.status != StudioProject.Status.READY:
            raise ValidationError("This customization needs attention in Studio before checkout.")
        if project.product_id != item.store_product_id or project.variant_id != item.variant_id:
            raise ValidationError("Studio project product and variant must match the Cart item.")
        if project.quantity != item.quantity:
            raise ValidationError("Studio Cart quantity must match the saved customization project.")
        try:
            validate_studio_project(project)
        except ValidationError as exc:
            raise ValidationError(["This customization needs attention before checkout.", *exc.messages]) from exc
    elif item.studio_project_id:
        raise ValidationError("Only Studio cart items may reference a Studio project.")


def _cart_pricing(cart):
    items = list(cart.items.select_related("store_product__storefront__organization", "store_product__designed_product", "variant", "studio_project"))
    if not items:
        raise ValidationError("Cart is empty.")
    currencies = set()
    lines = []
    for item in items:
        _validate_cart_item(item)
        currency = item.store_product.currency.upper()
        currencies.add(currency)
        unit = _money(item.variant.price)
        subtotal = _money(unit * item.quantity)
        lines.append({"item": item, "unit": unit, "subtotal": subtotal})
    if len(currencies) != 1:
        raise ValidationError("All Cart items must use the same currency.")
    subtotal = _money(sum((line["subtotal"] for line in lines), Decimal("0.00")))
    shipping = Decimal("0.00")
    discount = Decimal("0.00")
    total = _money(subtotal + shipping - discount)
    return lines, subtotal, shipping, discount, total, currencies.pop()


def _allocate(total, amounts):
    total = _money(total)
    if not amounts:
        return []
    base = sum(amounts, Decimal("0.00"))
    if total == 0 or base == 0:
        values = [Decimal("0.00") for _ in amounts]
        values[-1] = total
        return values
    values, allocated = [], Decimal("0.00")
    for amount in amounts[:-1]:
        share = _money(total * amount / base)
        values.append(share)
        allocated += share
    values.append(_money(total - allocated))
    return values


def require_cart_owner(actor, cart):
    if not getattr(actor, "is_authenticated", False) or (cart.customer_id != actor.pk and not actor.is_staff):
        raise PermissionDenied("Cart access denied.")
    return True


def require_purchase_owner(actor, purchase):
    if not getattr(actor, "is_authenticated", False) or (purchase.customer_id != actor.pk and not actor.is_staff):
        raise PermissionDenied("Purchase access denied.")
    return True


def get_active_cart(customer):
    if not getattr(customer, "is_authenticated", False):
        raise PermissionDenied("Authentication required.")
    cart = Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).first()
    if cart:
        return cart
    try:
        return Cart.objects.create(customer=customer)
    except IntegrityError:
        return Cart.objects.get(customer=customer, status=Cart.Status.ACTIVE)


@transaction.atomic
def add_cart_item(*, customer, product, variant, quantity=1, kind=CartItem.Kind.PLAIN, studio_project=None, request=None):
    if kind not in CartItem.Kind.values:
        raise ValidationError("Unsupported Cart item type.")
    quantity = int(quantity)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    cart = get_active_cart(customer)
    _validate_available_product(product, variant, quantity)
    if variant.product_id != product.pk:
        raise ValidationError("Selected variant does not belong to this product.")
    if cart.items.exists():
        cart_currency = cart.items.select_related("store_product").first().store_product.currency.upper()
        if cart_currency != product.currency.upper():
            raise ValidationError("All Cart items must use the same currency.")
    if kind == CartItem.Kind.STUDIO:
        if not studio_project:
            raise ValidationError("Studio project is required.")
        require_project_owner(customer, studio_project)
        if studio_project.status != StudioProject.Status.READY:
            raise ValidationError("Studio project must be Ready before adding it to Cart.")
        if studio_project.product_id != product.pk or studio_project.variant_id != variant.pk:
            raise ValidationError("Studio project product and variant must match the Cart item.")
        if studio_project.quantity != quantity:
            raise ValidationError("Studio Cart quantity must match the saved customization project.")
        validate_studio_project(studio_project)
        existing = cart.items.filter(kind=kind, studio_project=studio_project).first()
    else:
        if studio_project is not None:
            raise ValidationError("Plain and Ready Designed items cannot reference Studio.")
        existing = cart.items.filter(kind=kind, store_product=product, variant=variant, studio_project__isnull=True).first()
    if existing:
        existing.quantity = quantity if kind == CartItem.Kind.STUDIO else existing.quantity + quantity
        existing.full_clean()
        existing.save(update_fields=["quantity", "updated_at"])
        item = existing
    else:
        item = CartItem(cart=cart, kind=kind, store_product=product, variant=variant, studio_project=studio_project, quantity=quantity)
        item.full_clean()
        item.save()
    record_audit_event(actor=customer, action="cart.item.added", instance=item, metadata={"product_id": product.pk, "kind": kind, "quantity": item.quantity}, request=request)
    return item


@transaction.atomic
def update_cart_item(*, item, actor, quantity, request=None):
    require_cart_owner(actor, item.cart)
    if item.cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Only an active Cart can be changed.")
    quantity = int(quantity)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    if item.kind == CartItem.Kind.STUDIO and item.studio_project_id and quantity != item.studio_project.quantity:
        raise ValidationError("Change customized quantity in Studio so the saved project and Cart remain consistent.")
    item.quantity = quantity
    _validate_cart_item(item)
    item.full_clean()
    item.save(update_fields=["quantity", "updated_at"])
    record_audit_event(actor=actor, action="cart.item.updated", instance=item, metadata={"quantity": quantity}, request=request)
    return item


@transaction.atomic
def remove_cart_item(*, item, actor, request=None):
    require_cart_owner(actor, item.cart)
    if item.cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Only an active Cart can be changed.")
    item_id, cart = item.pk, item.cart
    item.delete()
    record_audit_event(actor=actor, action="cart.item.removed", instance=cart, metadata={"cart_item_id": item_id}, request=request)


@transaction.atomic
def create_cart_checkout(*, cart, actor, request=None):
    require_cart_owner(actor, cart)
    if cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Only an active Cart can be checked out.")
    # Boundary 1: authoritative validation and repricing immediately before
    # checkout is created or refreshed.
    lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    session, created = CheckoutSession.objects.get_or_create(cart=cart, defaults={"customer": cart.customer, "subtotal": subtotal, "shipping_amount": shipping, "discount_amount": discount, "total": total, "currency": currency})
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("This Cart already has a finalized checkout.")
    session.subtotal, session.shipping_amount, session.discount_amount, session.total, session.currency = subtotal, shipping, discount, total, currency
    session.full_clean()
    session.save()
    record_audit_event(actor=actor, action="checkout.created" if created else "checkout.refreshed", instance=session, metadata={"cart_id": cart.pk, "item_count": len(lines)}, request=request)
    return session


@transaction.atomic
def create_checkout(*, project, actor, request=None):
    require_project_owner(actor, project)
    if project.status != StudioProject.Status.READY:
        raise ValidationError("Studio project must be Ready for checkout.")
    unit, subtotal, shipping, discount, total = _pricing(project)
    session, created = CheckoutSession.objects.get_or_create(studio_project=project, defaults={"customer": project.customer, "subtotal": subtotal, "shipping_amount": shipping, "discount_amount": discount, "total": total, "currency": project.product.currency})
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("This Studio project already has a finalized checkout.")
    session.subtotal, session.shipping_amount, session.discount_amount, session.total, session.currency = subtotal, shipping, discount, total, project.product.currency
    session.full_clean()
    session.save()
    record_audit_event(actor=actor, action="checkout.created" if created else "checkout.refreshed", instance=session, metadata={"project_id": project.pk, "legacy_studio_checkout": True}, request=request)
    return session


def require_checkout_owner(actor, session):
    if not getattr(actor, "is_authenticated", False) or (session.customer_id != actor.pk and not actor.is_staff):
        raise PermissionDenied("Checkout access denied.")
    return True


def validate_shipping(session):
    if any(not str(value).strip() for value in [session.shipping_name, session.shipping_phone, session.shipping_address1, session.shipping_city, session.shipping_country]):
        raise ValidationError("Name, phone, address, city and country are required.")


@transaction.atomic
def update_checkout_shipping(*, session, actor, request=None, **fields):
    require_checkout_owner(actor, session)
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("Finalized checkout sessions are immutable.")
    allowed = {"shipping_name", "shipping_phone", "shipping_email", "shipping_address1", "shipping_address2", "shipping_city", "shipping_region", "shipping_country", "postal_code"}
    for key, value in fields.items():
        if key in allowed:
            setattr(session, key, value)
    session.full_clean()
    session.save()
    record_audit_event(actor=actor, action="checkout.shipping.updated", instance=session, request=request)
    return session


def _notify_order(order):
    Notification.objects.create(recipient=order.customer, type="order_status", title_en="Order confirmed", title_ar="تم تأكيد الطلب", body_en=f"Order {order.number} is confirmed.", body_ar=f"تم تأكيد الطلب {order.number}.", destination=f"/orders/{order.pk}/")


def _notify_purchase(purchase):
    Notification.objects.create(recipient=purchase.customer, type="order_status", title_en="Order confirmed", title_ar="تم تأكيد الطلب", body_en=f"Order {purchase.number} is confirmed.", body_ar=f"تم تأكيد الطلب {purchase.number}.", destination=f"/purchases/{purchase.pk}/")


def _reserve_stock(order):
    item, product = order.item, order.item.store_product
    if product.fulfillment_mode != StoreProduct.FulfillmentMode.STOCK:
        return
    variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id)
    if variant.stock_quantity is not None:
        if variant.stock_quantity < item.quantity:
            raise ValidationError("Insufficient stock at payment confirmation.")
        variant.stock_quantity -= item.quantity
        variant.save(update_fields=["stock_quantity"])


@transaction.atomic
def confirm_order(*, order, actor=None, request=None, notify_customer=True):
    order = CustomerOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == CustomerOrder.Status.CONFIRMED:
        return order
    if order.status not in {CustomerOrder.Status.PENDING_PAYMENT, CustomerOrder.Status.PAYMENT_FAILED}:
        raise ValidationError("Order cannot be confirmed from its current state.")
    _reserve_stock(order)
    order.status, order.confirmed_at = CustomerOrder.Status.CONFIRMED, timezone.now()
    order.save(update_fields=["status", "confirmed_at", "updated_at"])
    from apps.operations.services import start_order_operations
    start_order_operations(order=order, actor=actor, request=request)
    if notify_customer:
        _notify_order(order)
    record_audit_event(actor=actor, action="order.confirmed", instance=order, metadata={"payment_method": order.payment_method}, request=request)
    return order


@transaction.atomic
def confirm_purchase(*, purchase, actor=None, request=None):
    purchase = CustomerPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status == CustomerPurchase.Status.CONFIRMED:
        return purchase
    if purchase.status not in {CustomerPurchase.Status.PENDING_PAYMENT, CustomerPurchase.Status.PAYMENT_FAILED}:
        raise ValidationError("Purchase cannot be confirmed from its current state.")
    children = list(purchase.child_orders.select_related("item__store_product", "item__variant"))
    if not children:
        raise ValidationError("Purchase has no operational orders.")
    for child in children:
        confirm_order(order=child, actor=actor, request=request, notify_customer=False)
    purchase.status, purchase.confirmed_at = CustomerPurchase.Status.CONFIRMED, timezone.now()
    purchase.save(update_fields=["status", "confirmed_at", "updated_at"])
    _notify_purchase(purchase)
    record_audit_event(actor=actor, action="purchase.confirmed", instance=purchase, metadata={"child_order_count": len(children), "payment_method": purchase.payment_method}, request=request)
    return purchase


def _create_purchase(*, session, payment_method, subtotal, shipping, discount, total, currency):
    return CustomerPurchase.objects.create(checkout=session, customer=session.customer, status=CustomerPurchase.Status.PENDING_PAYMENT, payment_method=payment_method, subtotal=subtotal, shipping_amount=shipping, discount_amount=discount, total=total, currency=currency, shipping_snapshot=_shipping_snapshot(session))


def _create_child_order(*, purchase, product, variant, quantity, unit, subtotal, shipping, discount, studio_project=None):
    total = _money(subtotal + shipping - discount)
    order = CustomerOrder.objects.create(purchase=purchase, customer=purchase.customer, designer_organization=product.storefront.organization, status=CustomerOrder.Status.PENDING_PAYMENT, payment_method=purchase.payment_method, subtotal=subtotal, shipping_amount=shipping, discount_amount=discount, total=total, currency=purchase.currency, shipping_snapshot=purchase.shipping_snapshot)
    OrderItem.objects.create(order=order, store_product=product, variant=variant, studio_project=studio_project, sku=variant.sku, title=product.title_en, size=variant.size, color_name=variant.color_name, unit_price=unit, quantity=quantity, line_total=subtotal, customization_snapshot=_customization_snapshot(studio_project))
    return order


@transaction.atomic
def place_cart_purchase(*, session, actor, payment_method, request=None):
    require_checkout_owner(actor, session)
    session = CheckoutSession.objects.select_for_update().get(pk=session.pk)
    if not session.cart_id:
        raise ValidationError("Checkout is not Cart-based.")
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("Checkout has already been placed.")
    validate_shipping(session)
    cart = Cart.objects.select_for_update().get(pk=session.cart_id)
    if cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Cart is no longer active.")
    # Boundary 2: re-run all product/variant/Studio/source/method/transform
    # validation and server pricing immediately before any purchase is created.
    lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    if payment_method not in CustomerPurchase.PaymentMethod.values:
        raise ValidationError("Unsupported payment method.")
    get_payment_config(payment_method)
    purchase = _create_purchase(session=session, payment_method=payment_method, subtotal=subtotal, shipping=shipping, discount=discount, total=total, currency=currency)
    line_amounts = [line["subtotal"] for line in lines]
    shipping_allocations, discount_allocations = _allocate(shipping, line_amounts), _allocate(discount, line_amounts)
    children = []
    for line, shipping_share, discount_share in zip(lines, shipping_allocations, discount_allocations):
        item = line["item"]
        children.append(_create_child_order(purchase=purchase, product=item.store_product, variant=item.variant, quantity=item.quantity, unit=line["unit"], subtotal=line["subtotal"], shipping=shipping_share, discount=discount_share, studio_project=item.studio_project if item.kind == CartItem.Kind.STUDIO else None))
    session.status, session.placed_at = CheckoutSession.Status.PLACED, timezone.now()
    session.subtotal, session.shipping_amount, session.discount_amount, session.total, session.currency = subtotal, shipping, discount, total, currency
    session.save(update_fields=["status", "placed_at", "subtotal", "shipping_amount", "discount_amount", "total", "currency", "updated_at"])
    cart.status = Cart.Status.CONVERTED
    cart.save(update_fields=["status", "updated_at"])
    attempt = PaymentAttempt.objects.create(purchase=purchase, provider=payment_method, amount=total, currency=currency, idempotency_key=f"{payment_method}-purchase-{purchase.number}")
    if payment_method == CustomerPurchase.PaymentMethod.COD:
        attempt.status, attempt.completed_at, attempt.provider_reference = PaymentAttempt.Status.SUCCEEDED, timezone.now(), f"COD-{purchase.number}"
        attempt.save(update_fields=["status", "completed_at", "provider_reference", "updated_at"])
        purchase = confirm_purchase(purchase=purchase, actor=actor, request=request)
    record_audit_event(actor=actor, action="purchase.placed", instance=purchase, metadata={"payment_method": payment_method, "child_order_count": len(children), "cart_id": cart.pk}, request=request)
    return purchase, attempt


@transaction.atomic
def place_order(*, session, actor, payment_method, request=None):
    """Legacy Studio checkout entry point converged onto CustomerPurchase with one child order."""
    require_checkout_owner(actor, session)
    session = CheckoutSession.objects.select_for_update().get(pk=session.pk)
    if session.cart_id:
        purchase, attempt = place_cart_purchase(session=session, actor=actor, payment_method=payment_method, request=request)
        return purchase.child_orders.get(), attempt
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("Checkout has already been placed.")
    project = StudioProject.objects.select_related("product__storefront__organization", "variant").get(pk=session.studio_project_id)
    validate_shipping(session)
    unit, subtotal, shipping, discount, total = _pricing(project)
    if payment_method not in CustomerPurchase.PaymentMethod.values:
        raise ValidationError("Unsupported payment method.")
    get_payment_config(payment_method)
    purchase = _create_purchase(session=session, payment_method=payment_method, subtotal=subtotal, shipping=shipping, discount=discount, total=total, currency=project.product.currency)
    order = _create_child_order(purchase=purchase, product=project.product, variant=project.variant, quantity=project.quantity, unit=unit, subtotal=subtotal, shipping=shipping, discount=discount, studio_project=project)
    order.checkout = session
    order.save(update_fields=["checkout", "updated_at"])
    session.status, session.placed_at = CheckoutSession.Status.PLACED, timezone.now()
    session.subtotal, session.shipping_amount, session.discount_amount, session.total, session.currency = subtotal, shipping, discount, total, project.product.currency
    session.save(update_fields=["status", "placed_at", "subtotal", "shipping_amount", "discount_amount", "total", "currency", "updated_at"])
    attempt = PaymentAttempt.objects.create(order=order, purchase=purchase, provider=payment_method, amount=total, currency=order.currency, idempotency_key=f"{payment_method}-purchase-{purchase.number}")
    if payment_method == CustomerPurchase.PaymentMethod.COD:
        attempt.status, attempt.completed_at, attempt.provider_reference = PaymentAttempt.Status.SUCCEEDED, timezone.now(), f"COD-{purchase.number}"
        attempt.save(update_fields=["status", "completed_at", "provider_reference", "updated_at"])
        confirm_purchase(purchase=purchase, actor=actor, request=request)
        order.refresh_from_db()
    record_audit_event(actor=actor, action="order.placed", instance=order, metadata={"payment_method": payment_method, "project_id": project.pk, "purchase_id": purchase.pk}, request=request)
    return order, attempt


def initiate_online_payment(*, attempt, return_url=""):
    if attempt.provider == CustomerPurchase.PaymentMethod.COD:
        raise ValidationError("COD does not require online initiation.")
    if attempt.status not in {PaymentAttempt.Status.PENDING, PaymentAttempt.Status.FAILED}:
        raise ValidationError("Payment attempt cannot be initiated.")
    try:
        data = create_remote_payment(attempt, return_url=return_url)
    except Exception as exc:
        attempt.status, attempt.failure_code, attempt.failure_message = PaymentAttempt.Status.FAILED, exc.__class__.__name__, "Payment provider initiation failed."
        attempt.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        raise ValidationError("Payment provider initiation failed.") from exc
    attempt.provider_reference, attempt.redirect_url = data.get("reference", ""), data.get("redirect_url", "")
    attempt.provider_payload, attempt.status, attempt.failure_code, attempt.failure_message = {"client_secret": data.get("client_secret", "")}, PaymentAttempt.Status.REQUIRES_ACTION, "", ""
    attempt.save(update_fields=["provider_reference", "redirect_url", "provider_payload", "status", "failure_code", "failure_message", "updated_at"])
    return attempt


@transaction.atomic
def process_webhook(*, provider, event_id, payload_hash, reference, success, failed, payload):
    event, created = PaymentWebhookEvent.objects.get_or_create(provider=provider, event_id=event_id, defaults={"payload_hash": payload_hash})
    if not created:
        if event.payload_hash != payload_hash:
            raise ValidationError("Webhook event ID collision detected.")
        return event
    try:
        attempt = PaymentAttempt.objects.select_for_update().get(provider=provider, provider_reference=reference)
        if success:
            attempt.status, attempt.completed_at, attempt.failure_code, attempt.failure_message = PaymentAttempt.Status.SUCCEEDED, timezone.now(), "", ""
            attempt.save(update_fields=["status", "completed_at", "failure_code", "failure_message", "updated_at"])
            if attempt.purchase_id:
                confirm_purchase(purchase=attempt.purchase)
            elif attempt.order_id:
                confirm_order(order=attempt.order)
        elif failed:
            attempt.status, attempt.failure_message, attempt.completed_at = PaymentAttempt.Status.FAILED, "Provider reported payment failure.", timezone.now()
            attempt.save(update_fields=["status", "failure_message", "completed_at", "updated_at"])
            if attempt.purchase_id:
                purchase = CustomerPurchase.objects.select_for_update().get(pk=attempt.purchase_id)
                purchase.status = CustomerPurchase.Status.PAYMENT_FAILED
                purchase.save(update_fields=["status", "updated_at"])
                purchase.child_orders.filter(status=CustomerOrder.Status.PENDING_PAYMENT).update(status=CustomerOrder.Status.PAYMENT_FAILED)
            elif attempt.order_id:
                order = attempt.order
                order.status = CustomerOrder.Status.PAYMENT_FAILED
                order.save(update_fields=["status", "updated_at"])
        event.processed, event.processed_at = True, timezone.now()
        event.save(update_fields=["processed", "processed_at"])
    except Exception as exc:
        event.processing_error = exc.__class__.__name__
        event.save(update_fields=["processing_error"])
        raise
    return event
