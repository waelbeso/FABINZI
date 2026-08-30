import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.checkout.models import CustomerPurchase
from apps.checkout.services import add_cart_item, create_cart_checkout, get_active_cart, place_cart_purchase
from apps.media.models import MediaAsset
from tests.test_commerce_extension import fill_shipping, make_catalog

User = get_user_model()


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.mark.django_db
def test_customer_private_routes_reject_unauthenticated_requests_without_session_fallback():
    customer = User.objects.create_user(username="security-owner", password="password12345")
    client = APIClient()
    client.force_login(customer)
    response = client.get(reverse("v1:customer:me"))
    assert response.status_code == 401
    assert response.data["error"]["code"] == "authentication_required"


@pytest.mark.django_db
def test_customer_cannot_read_another_customers_parent_purchase_and_existence_is_hidden():
    owner = User.objects.create_user(username="purchase-owner", password="password12345")
    intruder = User.objects.create_user(username="purchase-intruder", password="password12345")
    _org, product, variant = make_catalog("security-purchase")
    add_cart_item(customer=owner, product=product, variant=variant, quantity=1, kind="plain")
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(owner), actor=owner), owner)
    purchase, _attempt = place_cart_purchase(session=session, actor=owner, payment_method="cod")
    assert isinstance(purchase, CustomerPurchase)

    response = _auth(intruder).get(reverse("v1:customer:purchase-detail", kwargs={"purchase_reference": purchase.number}))
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"
    assert "owner" not in str(response.data).lower()


@pytest.mark.django_db
def test_customer_cannot_read_another_customers_private_media_and_storage_identity_is_hidden():
    owner = User.objects.create_user(username="media-owner", password="password12345")
    intruder = User.objects.create_user(username="media-intruder", password="password12345")
    asset = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="studio-private/security-owner/nonexistent.png",
        original_filename="private.png",
        mime_type="image/png",
        size_bytes=100,
        access=MediaAsset.Access.PRIVATE,
        metadata={"studio_private_upload": True, "width": 10, "height": 10},
        uploaded_by=owner,
    )

    response = _auth(intruder).get(reverse("v1:customer:private-media", kwargs={"asset_id": asset.pk}))
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"
    body = str(response.data).lower()
    assert "studio-private" not in body
    assert "provider_asset_id" not in body


@pytest.mark.django_db
def test_customer_identity_and_purchase_contract_do_not_leak_staff_or_supply_fields():
    customer = User.objects.create_user(username="no-leak", password="password12345", email="no-leak@example.test")
    client = _auth(customer)
    me = client.get(reverse("v1:customer:me"))
    assert me.status_code == 200
    serialized = str(me.data).lower()
    for forbidden in ("is_staff", "is_superuser", "password", "groups", "permissions", "last_login"):
        assert forbidden not in serialized

    _org, product, variant = make_catalog("no-leak-product")
    add_cart_item(customer=customer, product=product, variant=variant, quantity=1, kind="plain")
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(customer), actor=customer), customer)
    purchase, _attempt = place_cart_purchase(session=session, actor=customer, payment_method="cod")
    detail = client.get(reverse("v1:customer:purchase-detail", kwargs={"purchase_reference": purchase.number}))
    assert detail.status_code == 200
    serialized = str(detail.data).lower()
    for forbidden in ("manufacturer", "rfq", "quote", "unit_cost", "payout", "commission", "audit", "production_notes"):
        assert forbidden not in serialized
