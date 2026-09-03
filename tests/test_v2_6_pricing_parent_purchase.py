from decimal import Decimal

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError

from apps.checkout.models import CartItem, CustomerPurchase, PaymentAttempt
from apps.checkout.services import (
    add_cart_item,
    create_cart_checkout,
    initiate_online_payment,
    place_cart_purchase,
    process_webhook,
)
from apps.integrations.models import IntegrationConfig
from tests.v2_6_helpers import fill_guest_shipping, make_catalog


@pytest.mark.django_db
def test_guest_multi_line_checkout_creates_one_parent_and_preserves_lines_and_quantities():
    _, plain_product, plain_variant = make_catalog("guestplain")
    _, ready_product, ready_variant = make_catalog("guestready", ready=True)
    identity = "guest-parent"
    cart = add_cart_item(customer=None, guest_identity=identity, product=plain_product, variant=plain_variant, quantity=3, kind=CartItem.Kind.PLAIN).cart
    add_cart_item(customer=None, guest_identity=identity, product=ready_product, variant=ready_variant, quantity=2, kind=CartItem.Kind.READY_DESIGNED)
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity)

    purchase, attempt = place_cart_purchase(
        session=checkout,
        actor=AnonymousUser(),
        guest_identity=identity,
        payment_method=CustomerPurchase.PaymentMethod.COD,
    )
    children = list(purchase.child_orders.select_related("item", "production_job", "fulfillment"))
    assert CustomerPurchase.objects.filter(checkout=checkout).count() == 1
    assert len(children) == 2
    assert {child.item.purchase_kind for child in children} == {CartItem.Kind.PLAIN, CartItem.Kind.READY_DESIGNED}
    assert sorted(child.item.quantity for child in children) == [2, 3]
    assert all(child.purchase_id == purchase.pk for child in children)
    assert all(child.production_job.order_id == child.pk for child in children)
    assert all(child.fulfillment.order_id == child.pk for child in children)
    assert all(child.production_job.manufacturer_id is None for child in children)
    assert attempt.purchase_id == purchase.pk and attempt.order_id is None
    assert attempt.amount == purchase.total


@pytest.mark.django_db
def test_server_authoritative_price_ignores_browser_price_and_reprices_at_placement(client):
    _, product, variant = make_catalog("serverprice", base_price="500.00")
    response = client.post(
        f"/cart/add/{product.pk}/",
        {"variant": variant.pk, "quantity": 2, "price": "1.00", "currency": "USD"},
    )
    assert response.status_code == 302 and response.url == "/cart/"
    cart_response = client.get("/cart/")
    assert b"1000.00" in cart_response.content
    checkout_response = client.get("/cart/checkout/")
    assert checkout_response.status_code == 302
    checkout_url = checkout_response.url
    checkout = product.cart_items.first().cart.checkout_session
    original_snapshot = checkout.pricing_snapshot
    assert original_snapshot["lines"][0]["unit_customer_price"] == "500.00"

    product.base_price = Decimal("650.00")
    product.save(update_fields=["base_price", "updated_at"])
    response = client.post(
        checkout_url,
        {
            "shipping_name": "Guest",
            "shipping_email": "guest-price@example.test",
            "shipping_phone": "01000000000",
            "shipping_address1": "1 Main St",
            "shipping_city": "Cairo",
            "shipping_region": "Cairo",
            "shipping_country": "EG",
            "postal_code": "11511",
            "payment_method": "cod",
            "action": "place",
            "total": "2.00",
            "price": "1.00",
        },
    )
    assert response.status_code == 302
    purchase = CustomerPurchase.objects.get(checkout=checkout)
    assert purchase.total == Decimal("1300.00")
    assert purchase.pricing_snapshot["lines"][0]["unit_customer_price"] == "650.00"
    assert purchase.pricing_snapshot["authoritative_inputs"] == ["StoreProduct.base_price", "ProductVariant.price_adjustment"]

    product.base_price = Decimal("900.00")
    product.save(update_fields=["base_price", "updated_at"])
    purchase.refresh_from_db()
    assert purchase.total == Decimal("1300.00")
    assert purchase.pricing_snapshot["lines"][0]["unit_customer_price"] == "650.00"


@pytest.mark.django_db
def test_reference_only_product_is_not_commercially_purchasable():
    _, product, variant = make_catalog("referenceonly")
    product.designed_product.reference_only = True
    product.designed_product.save(update_fields=["reference_only", "updated_at"])
    with pytest.raises(ValidationError, match="Reference-only"):
        add_cart_item(customer=None, guest_identity="guest-reference", product=product, variant=variant, kind=CartItem.Kind.PLAIN)


@pytest.mark.django_db
def test_placement_retry_returns_same_parent_and_payment_attempt():
    _, product, variant = make_catalog("retryplace")
    identity = "guest-retry"
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, quantity=1, kind=CartItem.Kind.PLAIN).cart
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity)
    first_purchase, first_attempt = place_cart_purchase(
        session=checkout,
        actor=AnonymousUser(),
        guest_identity=identity,
        payment_method="cod",
    )
    second_purchase, second_attempt = place_cart_purchase(
        session=checkout,
        actor=AnonymousUser(),
        guest_identity=identity,
        payment_method="cod",
    )
    assert first_purchase.pk == second_purchase.pk
    assert first_attempt.pk == second_attempt.pk
    assert CustomerPurchase.objects.filter(checkout=checkout).count() == 1
    assert PaymentAttempt.objects.filter(purchase=first_purchase).count() == 1


@pytest.mark.django_db
def test_same_placement_conflicting_payment_method_is_rejected():
    _, product, variant = make_catalog("conflictingplace")
    identity = "guest-conflict-place"
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN).cart
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity)
    place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="cod")
    with pytest.raises(ValidationError, match="different payment method"):
        place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="stripe")
    assert CustomerPurchase.objects.filter(checkout=checkout).count() == 1
    assert PaymentAttempt.objects.filter(purchase__checkout=checkout).count() == 1


@pytest.mark.django_db
def test_online_payment_initiation_is_idempotent_and_webhook_is_authoritative(monkeypatch):
    _, product, variant = make_catalog("onlinepay")
    identity = "guest-online"
    cfg = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    cfg.enabled = True
    cfg.last_test_status = IntegrationConfig.TestStatus.SUCCESS
    cfg.save(update_fields=["enabled", "last_test_status", "updated_at"])
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN).cart
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity)
    purchase, attempt = place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="stripe")
    assert purchase.status == CustomerPurchase.Status.PENDING_PAYMENT

    calls = []
    def fake_remote(payment_attempt, return_url=""):
        calls.append((payment_attempt.pk, return_url))
        return {"reference": "pi_v2_6", "status": "requires_action", "client_secret": "test_secret", "redirect_url": ""}
    monkeypatch.setattr("apps.checkout.services.create_remote_payment", fake_remote)
    first = initiate_online_payment(attempt=attempt, return_url="https://example.test/return")
    second = initiate_online_payment(attempt=PaymentAttempt.objects.get(pk=attempt.pk), return_url="https://example.test/return")
    assert first.pk == second.pk and len(calls) == 1
    purchase.refresh_from_db()
    assert purchase.status == CustomerPurchase.Status.PENDING_PAYMENT

    event1 = process_webhook(
        provider="stripe",
        event_id="evt_v2_6",
        payload_hash="a" * 64,
        reference="pi_v2_6",
        success=True,
        failed=False,
        payload={"id": "evt_v2_6"},
    )
    event2 = process_webhook(
        provider="stripe",
        event_id="evt_v2_6",
        payload_hash="a" * 64,
        reference="pi_v2_6",
        success=True,
        failed=False,
        payload={"id": "evt_v2_6"},
    )
    purchase.refresh_from_db()
    assert event1.pk == event2.pk
    assert purchase.status == CustomerPurchase.Status.CONFIRMED
    assert PaymentAttempt.objects.filter(purchase=purchase).count() == 1


@pytest.mark.django_db
def test_guest_and_authenticated_use_same_catalog_price_authority():
    customer = __import__("django.contrib.auth").contrib.auth.get_user_model().objects.create_user(username="sameprice", password="password12345")
    _, product, variant = make_catalog("sameauthority", base_price="777.00")
    guest_item = add_cart_item(customer=None, guest_identity="same-price-guest", product=product, variant=variant, kind=CartItem.Kind.PLAIN)
    authenticated_item = add_cart_item(customer=customer, product=product, variant=variant, kind=CartItem.Kind.PLAIN)
    assert guest_item.variant.price == authenticated_item.variant.price == Decimal("777.00")
