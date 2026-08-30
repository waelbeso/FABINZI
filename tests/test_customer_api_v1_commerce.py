import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.checkout.models import CartItem, CustomerPurchase, PaymentAttempt
from apps.integrations.models import IntegrationConfig
from apps.storefront.models import StudioProject
from apps.storefront.services import create_studio_project
from tests.test_commerce_extension import fill_shipping, make_catalog, ready_studio

User = get_user_model()


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _add_plain(client, product, variant, quantity=1, **extra):
    payload = {
        "kind": "plain",
        "store_slug": product.storefront.slug,
        "product_slug": product.slug,
        "variant_sku": variant.sku,
        "quantity": quantity,
    }
    payload.update(extra)
    return client.post(reverse("v1:customer:cart-item-create"), payload, format="json")


def _checkout(client):
    created = client.post(reverse("v1:customer:cart-checkout"), {}, format="json")
    assert created.status_code in {200, 201}, created.data
    checkout_id = created.data["id"]
    shipping = client.patch(
        reverse("v1:customer:checkout-detail", kwargs={"checkout_id": checkout_id}),
        {
            "shipping_name": "Customer",
            "shipping_phone": "01000000000",
            "shipping_email": "customer@example.test",
            "shipping_address1": "1 Main St",
            "shipping_city": "Cairo",
            "shipping_country": "EG",
        },
        format="json",
    )
    assert shipping.status_code == 200, shipping.data
    return checkout_id


@pytest.mark.django_db
def test_cart_uses_server_authoritative_decimal_price_and_ignores_client_price_fields():
    customer = User.objects.create_user(username="api-price", password="password12345")
    _, product, variant = make_catalog("api-price")
    client = _auth(customer)
    response = _add_plain(client, product, variant, quantity=2, unit_price="0.01", total="0.02", currency="USD")
    assert response.status_code == 201, response.data
    item = response.data["items"][0]
    assert item["unit_price"] == {"amount": "500.00", "currency": "EGP"}
    assert item["line_total"] == {"amount": "1000.00", "currency": "EGP"}
    assert response.data["total"] == {"amount": "1000.00", "currency": "EGP"}
    assert "stock_quantity" not in str(response.data)
    assert "price_adjustment" not in str(response.data)


@pytest.mark.django_db
def test_invalid_variant_and_unpublished_product_are_rejected():
    customer = User.objects.create_user(username="api-invalid-product", password="password12345")
    _, product, variant = make_catalog("api-invalid-product")
    client = _auth(customer)

    bad_variant = _add_plain(client, product, variant, variant_sku="DOES-NOT-EXIST") if False else client.post(
        reverse("v1:customer:cart-item-create"),
        {"kind": "plain", "store_slug": product.storefront.slug, "product_slug": product.slug, "variant_sku": "DOES-NOT-EXIST", "quantity": 1},
        format="json",
    )
    assert bad_variant.status_code == 404
    assert bad_variant.data["error"]["code"] == "not_found"

    product.status = product.Status.HIDDEN
    product.save(update_fields=["status"])
    hidden = _add_plain(client, product, variant)
    assert hidden.status_code == 404
    assert hidden.data["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_studio_cart_requires_owner_and_ready_state():
    owner = User.objects.create_user(username="api-studio-owner", password="password12345")
    intruder = User.objects.create_user(username="api-studio-intruder", password="password12345")
    _, product, variant = make_catalog("api-studio-owner", customization=True)
    draft = create_studio_project(customer=owner, product=product, variant=variant, quantity=1)

    owner_client = _auth(owner)
    draft_result = owner_client.post(reverse("v1:customer:cart-item-create"), {"kind": "studio", "studio_project_id": draft.pk}, format="json")
    assert draft_result.status_code == 400
    assert draft_result.data["error"]["code"] == "validation_error"

    ready = ready_studio(owner, product, variant)
    intruder_result = _auth(intruder).post(reverse("v1:customer:cart-item-create"), {"kind": "studio", "studio_project_id": ready.pk}, format="json")
    assert intruder_result.status_code == 404
    assert intruder_result.data["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_place_idempotency_replay_creates_one_parent_one_attempt_and_one_child_for_quantity():
    customer = User.objects.create_user(username="api-idempotent", password="password12345")
    _, product, variant = make_catalog("api-idempotent")
    client = _auth(customer)
    assert _add_plain(client, product, variant, quantity=3).status_code == 201
    checkout_id = _checkout(client)
    url = reverse("v1:customer:checkout-place", kwargs={"checkout_id": checkout_id})

    first = client.post(url, {"payment_method": "cod"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-0001")
    second = client.post(url, {"payment_method": "cod"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-0001")
    assert first.status_code == 201, first.data
    assert second.status_code == 200, second.data
    assert first.data["idempotent_replay"] is False
    assert second.data["idempotent_replay"] is True
    assert first.data["purchase"]["reference"] == second.data["purchase"]["reference"]

    purchase = CustomerPurchase.objects.get(customer=customer)
    assert CustomerPurchase.objects.filter(customer=customer).count() == 1
    assert PaymentAttempt.objects.filter(purchase=purchase).count() == 1
    assert purchase.child_orders.count() == 1
    assert purchase.child_orders.get().item.quantity == 3
    assert purchase.child_orders.get().production_job.manufacturer_id is None


@pytest.mark.django_db
def test_place_different_key_after_finalization_and_same_key_different_provider_conflict():
    customer = User.objects.create_user(username="api-conflict", password="password12345")
    _, product, variant = make_catalog("api-conflict")
    client = _auth(customer)
    assert _add_plain(client, product, variant).status_code == 201
    checkout_id = _checkout(client)
    url = reverse("v1:customer:checkout-place", kwargs={"checkout_id": checkout_id})
    assert client.post(url, {"payment_method": "cod"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-0002").status_code == 201

    different_key = client.post(url, {"payment_method": "cod"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-OTHER")
    different_provider = client.post(url, {"payment_method": "stripe"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-0002")
    assert different_key.status_code == 409
    assert different_key.data["error"]["code"] == "conflict"
    assert different_provider.status_code == 409
    assert different_provider.data["error"]["code"] == "conflict"
    assert CustomerPurchase.objects.filter(customer=customer).count() == 1


@pytest.mark.django_db
def test_multiple_cart_lines_remain_distinct_children_under_one_parent():
    customer = User.objects.create_user(username="api-multi-line", password="password12345")
    _, product_a, variant_a = make_catalog("api-multi-a")
    _, product_b, variant_b = make_catalog("api-multi-b")
    client = _auth(customer)
    assert _add_plain(client, product_a, variant_a, quantity=2).status_code == 201
    assert _add_plain(client, product_b, variant_b, quantity=1).status_code == 201
    checkout_id = _checkout(client)
    placed = client.post(reverse("v1:customer:checkout-place", kwargs={"checkout_id": checkout_id}), {"payment_method": "cod"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-multiline")
    assert placed.status_code == 201, placed.data
    purchase = CustomerPurchase.objects.get(customer=customer)
    children = list(purchase.child_orders.select_related("item", "production_job", "fulfillment"))
    assert len(children) == 2
    assert sorted(child.item.quantity for child in children) == [1, 2]
    assert all(child.production_job.manufacturer_id is None for child in children)
    assert all(child.fulfillment.order_id == child.pk for child in children)


@pytest.mark.django_db
def test_unsupported_or_unavailable_payment_provider_cannot_be_forced():
    customer = User.objects.create_user(username="api-payment-option", password="password12345")
    _, product, variant = make_catalog("api-payment-option")
    client = _auth(customer)
    options = client.get(reverse("v1:customer:payment-options"))
    assert options.status_code == 200
    providers = {row["provider"] for row in options.data["results"]}
    assert "cod" in providers
    assert "stripe" not in providers

    assert _add_plain(client, product, variant).status_code == 201
    checkout_id = _checkout(client)
    placed = client.post(reverse("v1:customer:checkout-place", kwargs={"checkout_id": checkout_id}), {"payment_method": "stripe"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-disabled")
    assert placed.status_code == 409
    assert CustomerPurchase.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_client_cannot_force_online_purchase_paid_and_no_provider_secrets_are_serialized(monkeypatch):
    customer = User.objects.create_user(username="api-payment-authority", password="password12345")
    _, product, variant = make_catalog("api-payment-authority")
    cfg = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    cfg.enabled = True
    cfg.last_test_status = IntegrationConfig.TestStatus.SUCCESS
    cfg.config = {"publishable_key": "pk_test_public"}
    cfg.set_secrets({"secret_key": "sk_test_never_serialize", "webhook_secret": "whsec_never_serialize"})
    cfg.save()

    def fake_initiate(*, attempt):
        attempt.status = PaymentAttempt.Status.REQUIRES_ACTION
        attempt.provider_reference = "pi_contract_test"
        attempt.redirect_url = "https://payments.example.test/redirect"
        attempt.provider_payload = {"client_secret": "pi_contract_secret"}
        attempt.save(update_fields=["status", "provider_reference", "redirect_url", "provider_payload", "updated_at"])
        return attempt

    monkeypatch.setattr("api.customer.initiate_online_payment", fake_initiate)
    client = _auth(customer)
    assert _add_plain(client, product, variant).status_code == 201
    checkout_id = _checkout(client)
    placed = client.post(
        reverse("v1:customer:checkout-place", kwargs={"checkout_id": checkout_id}),
        {"payment_method": "stripe", "status": "paid", "paid": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="mobile-place-online",
    )
    assert placed.status_code == 201, placed.data
    purchase = CustomerPurchase.objects.get(customer=customer)
    assert purchase.status == CustomerPurchase.Status.PENDING_PAYMENT
    assert placed.data["payment"]["status"] == PaymentAttempt.Status.REQUIRES_ACTION
    assert placed.data["payment"]["client_secret"] == "pi_contract_secret"
    body = str(placed.data)
    assert "sk_test_never_serialize" not in body
    assert "whsec_never_serialize" not in body
    assert "provider_payload" not in body


@pytest.mark.django_db
def test_purchase_api_is_parent_first_and_exposes_only_canonical_fulfillment_tracking():
    customer = User.objects.create_user(username="api-purchase", password="password12345")
    _, product, variant = make_catalog("api-purchase")
    client = _auth(customer)
    assert _add_plain(client, product, variant).status_code == 201
    checkout_id = _checkout(client)
    assert client.post(reverse("v1:customer:checkout-place", kwargs={"checkout_id": checkout_id}), {"payment_method": "cod"}, format="json", HTTP_IDEMPOTENCY_KEY="mobile-place-purchase").status_code == 201
    purchase = CustomerPurchase.objects.get(customer=customer)
    fulfillment = purchase.child_orders.get().fulfillment
    fulfillment.status = "shipped"
    fulfillment.carrier = "Contract Carrier"
    fulfillment.tracking_number = "TRACK-001"
    fulfillment.tracking_url = "https://tracking.example.test/TRACK-001"
    fulfillment.save(update_fields=["status", "carrier", "tracking_number", "tracking_url"])

    listed = client.get(reverse("v1:customer:purchases"))
    detail = client.get(reverse("v1:customer:purchase-detail", kwargs={"purchase_reference": purchase.number}))
    assert listed.status_code == detail.status_code == 200
    assert listed.data["count"] == 1
    assert listed.data["results"][0]["reference"] == str(purchase.number)
    assert "items" not in listed.data["results"][0]
    assert detail.data["reference"] == str(purchase.number)
    assert detail.data["items"][0]["fulfillment"]["tracking_number"] == "TRACK-001"
    serialized = str(detail.data).lower()
    for forbidden in ("manufacturer", "rfq", "unit_cost", "commission", "payout", "audit"):
        assert forbidden not in serialized
