import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.audit.services import record_audit_event
from apps.notifications.models import Notification
from apps.notifications.services import deliver_guest_purchase_confirmation
from apps.storefront.models import ProductVariant, StoreProduct, StudioProject
from apps.storefront.services import _validate_available_product, require_project_owner, validate_studio_project
from .gateways import create_remote_payment, get_payment_config
from .models import Cart, CartItem, CheckoutSession, CustomerOrder, CustomerPurchase, OrderItem, PaymentAttempt, PaymentWebhookEvent

PRICING_POLICY_CODE = "catalog_variant"
PRICING_POLICY_VERSION = "1"
GUEST_PURCHASE_SIGNING_SALT = "fabinzi.checkout.guest-purchase.v2-6"


class GuestCartMergeConflict(ValidationError):
    pass


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def guest_key_hash(identity):
    if not identity:
        raise PermissionDenied("Guest session identity is required.")
    return salted_hmac("fabinzi.checkout.guest-cart", str(identity), secret=settings.SECRET_KEY, algorithm="sha256").hexdigest()


def _shipping_snapshot(session):
    return {
        "name": session.shipping_name,
        "phone": session.shipping_phone,
        "email": session.shipping_email,
        "address1": session.shipping_address1,
        "address2": session.shipping_address2,
        "city": session.shipping_city,
        "region": session.shipping_region,
        "country": session.shipping_country,
        "postal_code": session.postal_code,
    }


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


def _production_snapshot(*, product, variant, kind, quantity, studio_project=None):
    designed = product.designed_product
    snapshot = {
        "product_type": kind,
        "store_product_id": product.pk,
        "designed_product_id": designed.pk,
        "garment_design_id": designed.garment_version.design_id,
        "garment_version_id": designed.garment_version_id,
        "variant_id": variant.pk,
        "sku": variant.sku,
        "size": variant.size,
        "color_name": variant.color_name,
        "quantity": int(quantity),
    }
    if kind == CartItem.Kind.READY_DESIGNED:
        snapshot.update({
            "artwork_id": designed.artwork_version.artwork_id,
            "artwork_version_id": designed.artwork_version_id,
            "garment_creator_organization_id": designed.garment_creator_organization_id or designed.garment_version.design.organization_id,
            "artwork_creator_organization_id": designed.artwork_creator_organization_id or designed.artwork_version.artwork.organization_id,
            "placements": [
                {
                    "decoration_zone_id": placement.decoration_zone_id,
                    "production_method": placement.production_method,
                    "transform": placement.transform,
                }
                for placement in designed.placements.select_related("decoration_zone").order_by("id")
            ],
        })
    elif kind == CartItem.Kind.STUDIO and studio_project is not None:
        snapshot["studio_project_id"] = studio_project.pk
        snapshot["customization"] = _customization_snapshot(studio_project)
    return snapshot


def _canonical_nonstudio_kind(product):
    return CartItem.Kind.READY_DESIGNED if product.designed_product.placements.exists() else CartItem.Kind.PLAIN


def _validate_commercial_product(product):
    if product.designed_product.reference_only:
        raise ValidationError("Reference-only products are not commercially purchasable.")
    return True


def _line_snapshot(*, product, variant, kind, quantity, unit, line_total):
    return {
        "pricing_policy": {"code": PRICING_POLICY_CODE, "version": PRICING_POLICY_VERSION},
        "product_type": kind,
        "store_product_id": product.pk,
        "variant_id": variant.pk,
        "sku": variant.sku,
        "currency": product.currency.upper(),
        "quantity": int(quantity),
        "catalog_base_price": str(_money(product.base_price)),
        "variant_price_adjustment": str(_money(variant.price_adjustment)),
        "unit_customer_price": str(_money(unit)),
        "line_subtotal": str(_money(line_total)),
    }


def _aggregate_pricing_snapshot(*, lines, subtotal, shipping, discount, total, currency):
    return {
        "pricing_policy": {"code": PRICING_POLICY_CODE, "version": PRICING_POLICY_VERSION},
        "currency": currency,
        "lines": [line["pricing_snapshot"] for line in lines],
        "subtotal": str(_money(subtotal)),
        "shipping_amount": str(_money(shipping)),
        "discount_amount": str(_money(discount)),
        "total": str(_money(total)),
        "authoritative_inputs": ["StoreProduct.base_price", "ProductVariant.price_adjustment"],
        "not_configured_components": [
            "manufacturing_cost",
            "garment_designer_royalty",
            "artwork_royalty",
            "decoration_cost",
            "fabinzi_margin_or_service_fee",
            "tax",
            "shipping_pricing_policy",
            "discount_policy",
            "currency_conversion_policy",
        ],
    }


def _pricing(project):
    if project.status != StudioProject.Status.READY:
        raise ValidationError("Studio project must be Ready for checkout.")
    if not project.variant_id:
        raise ValidationError("A product variant is required for checkout.")
    _validate_commercial_product(project.product)
    validation = validate_studio_project(project)
    unit = _money(validation["unit_price"])
    subtotal = _money(unit * project.quantity)
    shipping = Decimal("0.00")
    discount = Decimal("0.00")
    line = {
        "item": None,
        "unit": unit,
        "subtotal": subtotal,
        "pricing_snapshot": _line_snapshot(
            product=project.product,
            variant=project.variant,
            kind=CartItem.Kind.STUDIO,
            quantity=project.quantity,
            unit=unit,
            line_total=subtotal,
        ),
    }
    snapshot = _aggregate_pricing_snapshot(
        lines=[line], subtotal=subtotal, shipping=shipping, discount=discount, total=subtotal, currency=project.product.currency.upper()
    )
    return unit, subtotal, shipping, discount, subtotal, snapshot


def _validate_cart_item(item, *, quantity=None):
    quantity = item.quantity if quantity is None else int(quantity)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    if not item.variant_id:
        raise ValidationError("A product variant is required.")
    _validate_available_product(item.store_product, item.variant, quantity)
    _validate_commercial_product(item.store_product)
    if item.kind == CartItem.Kind.STUDIO:
        if item.cart.customer_id is None:
            raise PermissionDenied("Guest carts cannot contain Studio customization.")
        project = item.studio_project
        if not project:
            raise ValidationError("Studio cart item requires a Studio project.")
        if project.customer_id != item.cart.customer_id:
            raise PermissionDenied("Studio project does not belong to this customer.")
        if project.status != StudioProject.Status.READY:
            raise ValidationError("This customization needs attention in Studio before checkout.")
        if project.product_id != item.store_product_id or project.variant_id != item.variant_id:
            raise ValidationError("Studio project product and variant must match the Cart item.")
        if project.quantity != quantity:
            raise ValidationError("Studio Cart quantity must match the saved customization project.")
        try:
            validate_studio_project(project)
        except ValidationError as exc:
            raise ValidationError(["This customization needs attention before checkout.", *exc.messages]) from exc
    else:
        if item.studio_project_id:
            raise ValidationError("Only Studio cart items may reference a Studio project.")
        expected = _canonical_nonstudio_kind(item.store_product)
        if item.kind != expected:
            raise ValidationError("Cart product type no longer matches the current commercial product state.")
    return True


def _cart_pricing(cart):
    items = list(
        cart.items.select_related(
            "store_product__storefront__organization",
            "store_product__designed_product",
            "variant",
            "studio_project",
        ).prefetch_related("store_product__designed_product__placements")
    )
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
        lines.append({
            "item": item,
            "unit": unit,
            "subtotal": subtotal,
            "pricing_snapshot": _line_snapshot(
                product=item.store_product,
                variant=item.variant,
                kind=item.kind,
                quantity=item.quantity,
                unit=unit,
                line_total=subtotal,
            ),
        })
    if len(currencies) != 1:
        raise ValidationError("All Cart items must use the same currency.")
    subtotal = _money(sum((line["subtotal"] for line in lines), Decimal("0.00")))
    shipping = Decimal("0.00")
    discount = Decimal("0.00")
    total = _money(subtotal + shipping - discount)
    currency = currencies.pop()
    return lines, subtotal, shipping, discount, total, currency


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


def require_cart_owner(actor, cart, *, guest_identity=None):
    if cart.customer_id is not None:
        if not getattr(actor, "is_authenticated", False) or (cart.customer_id != actor.pk and not actor.is_staff):
            raise PermissionDenied("Cart access denied.")
        return True
    if not guest_identity or cart.guest_key_hash != guest_key_hash(guest_identity):
        raise PermissionDenied("Guest Cart access denied.")
    return True


def require_purchase_owner(actor, purchase):
    if purchase.customer_id is None:
        raise PermissionDenied("Guest purchases require a secure purchase credential.")
    if not getattr(actor, "is_authenticated", False) or (purchase.customer_id != actor.pk and not actor.is_staff):
        raise PermissionDenied("Purchase access denied.")
    return True


def get_active_cart(customer=None, *, guest_identity=None):
    if getattr(customer, "is_authenticated", False):
        cart = Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).first()
        if cart:
            return cart
        try:
            return Cart.objects.create(customer=customer, guest_key_hash="")
        except IntegrityError:
            return Cart.objects.get(customer=customer, status=Cart.Status.ACTIVE)
    key_hash = guest_key_hash(guest_identity)
    cart = Cart.objects.filter(customer__isnull=True, guest_key_hash=key_hash, status=Cart.Status.ACTIVE).first()
    if cart:
        return cart
    try:
        return Cart.objects.create(customer=None, guest_key_hash=key_hash)
    except IntegrityError:
        return Cart.objects.get(customer__isnull=True, guest_key_hash=key_hash, status=Cart.Status.ACTIVE)


def _draft_checkout_for_cart(cart):
    try:
        checkout = cart.checkout_session
    except CheckoutSession.DoesNotExist:
        return None
    return checkout if checkout.status == CheckoutSession.Status.DRAFT else None


@transaction.atomic
def merge_guest_cart_into_customer(*, guest_identity, customer, request=None):
    if not getattr(customer, "is_authenticated", False):
        raise PermissionDenied("Authentication is required to merge a Guest Cart.")
    key_hash = guest_key_hash(guest_identity)
    guest_cart = (
        Cart.objects.select_for_update()
        .filter(customer__isnull=True, guest_key_hash=key_hash, status=Cart.Status.ACTIVE)
        .first()
    )
    if not guest_cart:
        return Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).first()

    guest_items = list(
        guest_cart.items.select_for_update().select_related("store_product__designed_product", "variant", "studio_project").prefetch_related("store_product__designed_product__placements")
    )
    for item in guest_items:
        if item.kind == CartItem.Kind.STUDIO or item.studio_project_id:
            raise GuestCartMergeConflict("Guest Cart contains an invalid Studio customization line.")
        try:
            _validate_cart_item(item)
        except (ValidationError, PermissionDenied) as exc:
            raise GuestCartMergeConflict(exc.messages if isinstance(exc, ValidationError) else str(exc)) from exc

    customer_cart = Cart.objects.select_for_update().filter(customer=customer, status=Cart.Status.ACTIVE).first()
    if customer_cart is None:
        guest_checkout = _draft_checkout_for_cart(guest_cart)
        guest_cart.customer = customer
        guest_cart.guest_key_hash = ""
        guest_cart.full_clean()
        try:
            guest_cart.save(update_fields=["customer", "guest_key_hash", "updated_at"])
        except IntegrityError as exc:
            raise GuestCartMergeConflict("The account Cart changed while the Guest Cart was being adopted. Retry safely.") from exc
        if guest_checkout is not None:
            guest_checkout.customer = customer
            guest_checkout.full_clean()
            guest_checkout.save(update_fields=["customer", "updated_at"])
        record_audit_event(
            actor=customer,
            action="cart.guest.adopted",
            instance=guest_cart,
            metadata={"item_count": len(guest_items), "checkout_adopted": guest_checkout is not None},
            request=request,
        )
        return guest_cart

    customer_items = list(
        customer_cart.items.select_for_update().select_related("store_product__designed_product", "variant", "studio_project").prefetch_related("store_product__designed_product__placements")
    )
    try:
        for item in customer_items:
            _validate_cart_item(item)
    except (ValidationError, PermissionDenied) as exc:
        raise GuestCartMergeConflict(exc.messages if isinstance(exc, ValidationError) else str(exc)) from exc

    currencies = {item.store_product.currency.upper() for item in customer_items + guest_items}
    if len(currencies) > 1:
        raise GuestCartMergeConflict("Guest Cart and account Cart use incompatible currencies.")

    existing = {
        (item.kind, item.store_product_id, item.variant_id): item
        for item in customer_items
        if item.kind != CartItem.Kind.STUDIO and item.studio_project_id is None
    }
    plan = []
    for guest_item in guest_items:
        key = (guest_item.kind, guest_item.store_product_id, guest_item.variant_id)
        target = existing.get(key)
        resulting_quantity = guest_item.quantity + (target.quantity if target else 0)
        try:
            _validate_available_product(guest_item.store_product, guest_item.variant, resulting_quantity)
            _validate_commercial_product(guest_item.store_product)
        except ValidationError as exc:
            raise GuestCartMergeConflict(exc.messages) from exc
        plan.append((guest_item, target, resulting_quantity))

    for guest_item, target, resulting_quantity in plan:
        if target:
            target.quantity = resulting_quantity
            target.full_clean()
            target.save(update_fields=["quantity", "updated_at"])
        else:
            copy = CartItem(
                cart=customer_cart,
                kind=guest_item.kind,
                store_product=guest_item.store_product,
                variant=guest_item.variant,
                quantity=guest_item.quantity,
            )
            copy.full_clean()
            copy.save()

    _cart_pricing(customer_cart)
    guest_checkout = _draft_checkout_for_cart(guest_cart)
    if guest_checkout is not None:
        guest_checkout.status = CheckoutSession.Status.CANCELLED
        guest_checkout.save(update_fields=["status", "updated_at"])
    guest_cart.status = Cart.Status.CONVERTED
    guest_cart.merged_into = customer_cart
    guest_cart.save(update_fields=["status", "merged_into", "updated_at"])
    record_audit_event(
        actor=customer,
        action="cart.guest.merged",
        instance=customer_cart,
        metadata={"source_cart_id": guest_cart.pk, "source_item_count": len(guest_items), "source_checkout_cancelled": guest_checkout is not None},
        request=request,
    )
    return customer_cart


@transaction.atomic
def add_cart_item(*, customer=None, product, variant, quantity=1, kind=CartItem.Kind.PLAIN, studio_project=None, guest_identity=None, request=None):
    if kind not in CartItem.Kind.values:
        raise ValidationError("Unsupported Cart item type.")
    quantity = int(quantity)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    authenticated = bool(getattr(customer, "is_authenticated", False))
    if not authenticated and kind == CartItem.Kind.STUDIO:
        raise PermissionDenied("Sign in or create an account to use Studio customization.")
    cart = get_active_cart(customer if authenticated else None, guest_identity=guest_identity)
    _validate_available_product(product, variant, quantity)
    _validate_commercial_product(product)
    if variant.product_id != product.pk:
        raise ValidationError("Selected variant does not belong to this product.")
    if kind != CartItem.Kind.STUDIO and kind != _canonical_nonstudio_kind(product):
        raise ValidationError("Product type does not match the current product configuration.")
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
    resulting_quantity = quantity if kind == CartItem.Kind.STUDIO else quantity + (existing.quantity if existing else 0)
    _validate_available_product(product, variant, resulting_quantity)
    _validate_commercial_product(product)
    if existing:
        existing.quantity = resulting_quantity
        existing.full_clean()
        existing.save(update_fields=["quantity", "updated_at"])
        item = existing
    else:
        item = CartItem(cart=cart, kind=kind, store_product=product, variant=variant, studio_project=studio_project, quantity=quantity)
        item.full_clean()
        item.save()
    record_audit_event(
        actor=customer,
        action="cart.item.added",
        instance=item,
        metadata={"product_id": product.pk, "kind": kind, "quantity": item.quantity, "guest": cart.customer_id is None},
        request=request,
    )
    return item


@transaction.atomic
def update_cart_item(*, item, actor, quantity, guest_identity=None, request=None):
    require_cart_owner(actor, item.cart, guest_identity=guest_identity)
    if item.cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Only an active Cart can be changed.")
    quantity = int(quantity)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    if item.kind == CartItem.Kind.STUDIO and item.studio_project_id and quantity != item.studio_project.quantity:
        raise ValidationError("Change customized quantity in Studio so the saved project and Cart remain consistent.")
    _validate_cart_item(item, quantity=quantity)
    item.quantity = quantity
    item.full_clean()
    item.save(update_fields=["quantity", "updated_at"])
    record_audit_event(actor=actor, action="cart.item.updated", instance=item, metadata={"quantity": quantity}, request=request)
    return item


@transaction.atomic
def remove_cart_item(*, item, actor, guest_identity=None, request=None):
    require_cart_owner(actor, item.cart, guest_identity=guest_identity)
    if item.cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Only an active Cart can be changed.")
    item_id, cart = item.pk, item.cart
    item.delete()
    record_audit_event(actor=actor, action="cart.item.removed", instance=cart, metadata={"cart_item_id": item_id}, request=request)


@transaction.atomic
def create_cart_checkout(*, cart, actor, guest_identity=None, request=None):
    require_cart_owner(actor, cart, guest_identity=guest_identity)
    if cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Only an active Cart can be checked out.")
    lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    snapshot = _aggregate_pricing_snapshot(lines=lines, subtotal=subtotal, shipping=shipping, discount=discount, total=total, currency=currency)
    session, created = CheckoutSession.objects.get_or_create(
        cart=cart,
        defaults={
            "customer": cart.customer,
            "subtotal": subtotal,
            "shipping_amount": shipping,
            "discount_amount": discount,
            "total": total,
            "currency": currency,
            "pricing_snapshot": snapshot,
        },
    )
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("This Cart already has a finalized checkout.")
    session.customer = cart.customer
    session.subtotal, session.shipping_amount, session.discount_amount = subtotal, shipping, discount
    session.total, session.currency, session.pricing_snapshot = total, currency, snapshot
    session.full_clean()
    session.save()
    record_audit_event(
        actor=actor,
        action="checkout.created" if created else "checkout.refreshed",
        instance=session,
        metadata={"cart_id": cart.pk, "item_count": len(lines), "guest": cart.customer_id is None},
        request=request,
    )
    return session


@transaction.atomic
def create_checkout(*, project, actor, request=None):
    require_project_owner(actor, project)
    if project.status != StudioProject.Status.READY:
        raise ValidationError("Studio project must be Ready for checkout.")
    unit, subtotal, shipping, discount, total, snapshot = _pricing(project)
    session, created = CheckoutSession.objects.get_or_create(
        studio_project=project,
        defaults={
            "customer": project.customer,
            "subtotal": subtotal,
            "shipping_amount": shipping,
            "discount_amount": discount,
            "total": total,
            "currency": project.product.currency.upper(),
            "pricing_snapshot": snapshot,
        },
    )
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("This Studio project already has a finalized checkout.")
    session.subtotal, session.shipping_amount, session.discount_amount = subtotal, shipping, discount
    session.total, session.currency, session.pricing_snapshot = total, project.product.currency.upper(), snapshot
    session.full_clean()
    session.save()
    record_audit_event(actor=actor, action="checkout.created" if created else "checkout.refreshed", instance=session, metadata={"project_id": project.pk, "legacy_studio_checkout": True}, request=request)
    return session


def require_checkout_owner(actor, session, *, guest_identity=None):
    if session.customer_id is not None:
        if not getattr(actor, "is_authenticated", False) or (session.customer_id != actor.pk and not actor.is_staff):
            raise PermissionDenied("Checkout access denied.")
        return True
    if not session.cart_id:
        raise PermissionDenied("Checkout access denied.")
    return require_cart_owner(actor, session.cart, guest_identity=guest_identity)


def validate_shipping(session):
    required = [session.shipping_name, session.shipping_phone, session.shipping_address1, session.shipping_city, session.shipping_country]
    if session.customer_id is None:
        required.append(session.shipping_email)
    if any(not str(value).strip() for value in required):
        if session.customer_id is None:
            raise ValidationError("Name, email, phone, address, city and country are required for Guest checkout.")
        raise ValidationError("Name, phone, address, city and country are required.")


@transaction.atomic
def update_checkout_shipping(*, session, actor, guest_identity=None, request=None, **fields):
    require_checkout_owner(actor, session, guest_identity=guest_identity)
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("Finalized checkout sessions are immutable.")
    allowed = {"shipping_name", "shipping_phone", "shipping_email", "shipping_address1", "shipping_address2", "shipping_city", "shipping_region", "shipping_country", "postal_code"}
    for key, value in fields.items():
        if key in allowed:
            setattr(session, key, value)
    session.full_clean()
    session.save()
    record_audit_event(actor=actor, action="checkout.shipping.updated", instance=session, metadata={"guest": session.customer_id is None}, request=request)
    return session


def _notify_order(order):
    if not order.customer_id:
        return None
    return Notification.objects.create(
        recipient=order.customer,
        type="order_status",
        title_en="Order confirmed",
        title_ar="تم تأكيد الطلب",
        body_en=f"Order {order.number} is confirmed.",
        body_ar=f"تم تأكيد الطلب {order.number}.",
        destination=f"/orders/{order.pk}/",
    )


def make_guest_purchase_token(purchase):
    if purchase.customer_id is not None:
        raise ValidationError("Secure Guest credentials are only issued for Guest purchases.")
    return signing.dumps({"purchase": str(purchase.number)}, key=settings.SECRET_KEY, salt=GUEST_PURCHASE_SIGNING_SALT, compress=True)


def get_guest_purchase_from_token(token):
    try:
        payload = signing.loads(token, key=settings.SECRET_KEY, salt=GUEST_PURCHASE_SIGNING_SALT)
    except signing.BadSignature as exc:
        raise PermissionDenied("Guest purchase access denied.") from exc
    number = payload.get("purchase") if isinstance(payload, dict) else None
    if not number:
        raise PermissionDenied("Guest purchase access denied.")
    try:
        purchase = CustomerPurchase.objects.get(number=number, customer__isnull=True)
    except (CustomerPurchase.DoesNotExist, ValueError) as exc:
        raise PermissionDenied("Guest purchase access denied.") from exc
    return purchase


def _notify_purchase(purchase):
    if purchase.customer_id:
        return Notification.objects.create(
            recipient=purchase.customer,
            type="order_status",
            title_en="Order confirmed",
            title_ar="تم تأكيد الطلب",
            body_en=f"Order {purchase.number} is confirmed.",
            body_ar=f"تم تأكيد الطلب {purchase.number}.",
            destination=f"/purchases/{purchase.pk}/",
        )
    purchase.guest_confirmation_email_status = CustomerPurchase.GuestEmailStatus.QUEUED
    purchase.guest_confirmation_email_updated_at = timezone.now()
    purchase.save(update_fields=["guest_confirmation_email_status", "guest_confirmation_email_updated_at", "updated_at"])
    status = deliver_guest_purchase_confirmation(
        email=purchase.shipping_snapshot.get("email", ""),
        purchase_number=str(purchase.number),
        access_token=make_guest_purchase_token(purchase),
    )
    purchase.guest_confirmation_email_status = status
    purchase.guest_confirmation_email_updated_at = timezone.now()
    purchase.save(update_fields=["guest_confirmation_email_status", "guest_confirmation_email_updated_at", "updated_at"])
    return status


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
    record_audit_event(actor=actor, action="purchase.confirmed", instance=purchase, metadata={"child_order_count": len(children), "payment_method": purchase.payment_method, "guest": purchase.customer_id is None}, request=request)
    return purchase


def _create_purchase(*, session, payment_method, subtotal, shipping, discount, total, currency, pricing_snapshot):
    return CustomerPurchase.objects.create(
        checkout=session,
        customer=session.customer,
        status=CustomerPurchase.Status.PENDING_PAYMENT,
        payment_method=payment_method,
        subtotal=subtotal,
        shipping_amount=shipping,
        discount_amount=discount,
        total=total,
        currency=currency,
        shipping_snapshot=_shipping_snapshot(session),
        pricing_snapshot=pricing_snapshot,
        guest_confirmation_email_status=CustomerPurchase.GuestEmailStatus.NOT_REQUIRED,
    )


def _create_child_order(*, purchase, product, variant, quantity, unit, subtotal, shipping, discount, kind, pricing_snapshot, studio_project=None):
    total = _money(subtotal + shipping - discount)
    order = CustomerOrder.objects.create(
        purchase=purchase,
        customer=purchase.customer,
        designer_organization=product.storefront.organization,
        status=CustomerOrder.Status.PENDING_PAYMENT,
        payment_method=purchase.payment_method,
        subtotal=subtotal,
        shipping_amount=shipping,
        discount_amount=discount,
        total=total,
        currency=purchase.currency,
        shipping_snapshot=purchase.shipping_snapshot,
    )
    item = OrderItem(
        order=order,
        store_product=product,
        variant=variant,
        studio_project=studio_project,
        purchase_kind=kind,
        sku=variant.sku,
        title=product.title_en,
        size=variant.size,
        color_name=variant.color_name,
        unit_price=unit,
        quantity=quantity,
        line_total=subtotal,
        pricing_snapshot=pricing_snapshot,
        production_snapshot=_production_snapshot(
            product=product, variant=variant, kind=kind, quantity=quantity, studio_project=studio_project
        ),
        customization_snapshot=_customization_snapshot(studio_project),
    )
    item.full_clean()
    item.save()
    return order


def _payment_fingerprint(*, purchase, payment_method):
    payload = {
        "purchase": str(purchase.number),
        "provider": payment_method,
        "amount": str(_money(purchase.total)),
        "currency": purchase.currency,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _payment_attempt_for_purchase(*, purchase, payment_method, order=None):
    key = f"place-{purchase.checkout.placement_key}"
    fingerprint = _payment_fingerprint(purchase=purchase, payment_method=payment_method)
    attempt = PaymentAttempt.objects.filter(idempotency_key=key).first()
    if attempt:
        if attempt.purchase_id != purchase.pk or attempt.provider != payment_method or attempt.request_fingerprint != fingerprint:
            raise ValidationError("Idempotency key was already used with conflicting payment data.")
        return attempt
    return PaymentAttempt.objects.create(
        order=order,
        purchase=purchase,
        provider=payment_method,
        amount=purchase.total,
        currency=purchase.currency,
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )


@transaction.atomic
def place_cart_purchase(*, session, actor, payment_method, guest_identity=None, request=None):
    require_checkout_owner(actor, session, guest_identity=guest_identity)
    session = CheckoutSession.objects.select_for_update().select_related("cart").get(pk=session.pk)
    require_checkout_owner(actor, session, guest_identity=guest_identity)
    if not session.cart_id:
        raise ValidationError("Checkout is not Cart-based.")
    if session.status == CheckoutSession.Status.PLACED:
        purchase = CustomerPurchase.objects.get(checkout=session)
        if purchase.payment_method != payment_method:
            raise ValidationError("Checkout was already placed using a different payment method.")
        attempt = _payment_attempt_for_purchase(purchase=purchase, payment_method=payment_method)
        return purchase, attempt
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("Checkout has already been finalized.")
    validate_shipping(session)
    cart = Cart.objects.select_for_update().get(pk=session.cart_id)
    require_cart_owner(actor, cart, guest_identity=guest_identity)
    if cart.status != Cart.Status.ACTIVE:
        raise ValidationError("Cart is no longer active.")
    lines, subtotal, shipping, discount, total, currency = _cart_pricing(cart)
    snapshot = _aggregate_pricing_snapshot(lines=lines, subtotal=subtotal, shipping=shipping, discount=discount, total=total, currency=currency)
    if payment_method not in CustomerPurchase.PaymentMethod.values:
        raise ValidationError("Unsupported payment method.")
    get_payment_config(payment_method)
    purchase = _create_purchase(
        session=session,
        payment_method=payment_method,
        subtotal=subtotal,
        shipping=shipping,
        discount=discount,
        total=total,
        currency=currency,
        pricing_snapshot=snapshot,
    )
    line_amounts = [line["subtotal"] for line in lines]
    shipping_allocations, discount_allocations = _allocate(shipping, line_amounts), _allocate(discount, line_amounts)
    children = []
    for line, shipping_share, discount_share in zip(lines, shipping_allocations, discount_allocations):
        item = line["item"]
        children.append(
            _create_child_order(
                purchase=purchase,
                product=item.store_product,
                variant=item.variant,
                quantity=item.quantity,
                unit=line["unit"],
                subtotal=line["subtotal"],
                shipping=shipping_share,
                discount=discount_share,
                kind=item.kind,
                pricing_snapshot=line["pricing_snapshot"],
                studio_project=item.studio_project if item.kind == CartItem.Kind.STUDIO else None,
            )
        )
    session.status, session.placed_at = CheckoutSession.Status.PLACED, timezone.now()
    session.subtotal, session.shipping_amount, session.discount_amount = subtotal, shipping, discount
    session.total, session.currency, session.pricing_snapshot = total, currency, snapshot
    session.save(update_fields=["status", "placed_at", "subtotal", "shipping_amount", "discount_amount", "total", "currency", "pricing_snapshot", "updated_at"])
    cart.status = Cart.Status.CONVERTED
    cart.save(update_fields=["status", "updated_at"])
    attempt = _payment_attempt_for_purchase(purchase=purchase, payment_method=payment_method)
    if payment_method == CustomerPurchase.PaymentMethod.COD:
        attempt.status, attempt.completed_at, attempt.provider_reference = PaymentAttempt.Status.SUCCEEDED, timezone.now(), f"COD-{purchase.number}"
        attempt.save(update_fields=["status", "completed_at", "provider_reference", "updated_at"])
        purchase = confirm_purchase(purchase=purchase, actor=actor, request=request)
    record_audit_event(actor=actor, action="purchase.placed", instance=purchase, metadata={"payment_method": payment_method, "child_order_count": len(children), "cart_id": cart.pk, "guest": purchase.customer_id is None}, request=request)
    return purchase, attempt


@transaction.atomic
def place_order(*, session, actor, payment_method, request=None):
    """Legacy authenticated Studio checkout converged onto CustomerPurchase."""
    require_checkout_owner(actor, session)
    session = CheckoutSession.objects.select_for_update().get(pk=session.pk)
    if session.cart_id:
        purchase, attempt = place_cart_purchase(session=session, actor=actor, payment_method=payment_method, request=request)
        return purchase.child_orders.get(), attempt
    if session.status == CheckoutSession.Status.PLACED:
        purchase = CustomerPurchase.objects.get(checkout=session)
        if purchase.payment_method != payment_method:
            raise ValidationError("Checkout was already placed using a different payment method.")
        order = purchase.child_orders.get()
        return order, _payment_attempt_for_purchase(purchase=purchase, payment_method=payment_method, order=order)
    if session.status != CheckoutSession.Status.DRAFT:
        raise ValidationError("Checkout has already been finalized.")
    project = StudioProject.objects.select_related("product__storefront__organization", "variant").get(pk=session.studio_project_id)
    validate_shipping(session)
    unit, subtotal, shipping, discount, total, snapshot = _pricing(project)
    if payment_method not in CustomerPurchase.PaymentMethod.values:
        raise ValidationError("Unsupported payment method.")
    get_payment_config(payment_method)
    purchase = _create_purchase(
        session=session,
        payment_method=payment_method,
        subtotal=subtotal,
        shipping=shipping,
        discount=discount,
        total=total,
        currency=project.product.currency.upper(),
        pricing_snapshot=snapshot,
    )
    line_snapshot = snapshot["lines"][0]
    order = _create_child_order(
        purchase=purchase,
        product=project.product,
        variant=project.variant,
        quantity=project.quantity,
        unit=unit,
        subtotal=subtotal,
        shipping=shipping,
        discount=discount,
        kind=CartItem.Kind.STUDIO,
        pricing_snapshot=line_snapshot,
        studio_project=project,
    )
    order.checkout = session
    order.save(update_fields=["checkout", "updated_at"])
    session.status, session.placed_at = CheckoutSession.Status.PLACED, timezone.now()
    session.subtotal, session.shipping_amount, session.discount_amount = subtotal, shipping, discount
    session.total, session.currency, session.pricing_snapshot = total, project.product.currency.upper(), snapshot
    session.save(update_fields=["status", "placed_at", "subtotal", "shipping_amount", "discount_amount", "total", "currency", "pricing_snapshot", "updated_at"])
    attempt = _payment_attempt_for_purchase(purchase=purchase, payment_method=payment_method, order=order)
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
    if attempt.status == PaymentAttempt.Status.REQUIRES_ACTION and attempt.provider_reference:
        return attempt
    if attempt.status == PaymentAttempt.Status.SUCCEEDED:
        return attempt
    if attempt.status not in {PaymentAttempt.Status.PENDING, PaymentAttempt.Status.FAILED}:
        raise ValidationError("Payment attempt cannot be initiated.")
    try:
        data = create_remote_payment(attempt, return_url=return_url)
    except Exception as exc:
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.failure_code = exc.__class__.__name__
        attempt.failure_message = "Payment provider initiation failed."
        attempt.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        raise ValidationError("Payment provider initiation failed.") from exc
    attempt.provider_reference, attempt.redirect_url = data.get("reference", ""), data.get("redirect_url", "")
    attempt.provider_payload = {"client_secret": data.get("client_secret", "")}
    attempt.status, attempt.failure_code, attempt.failure_message = PaymentAttempt.Status.REQUIRES_ACTION, "", ""
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
