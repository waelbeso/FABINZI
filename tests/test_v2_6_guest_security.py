import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.accounts.guest_identity import GUEST_SESSION_KEY
from apps.checkout.models import Cart, CartItem, CustomerPurchase
from apps.checkout.services import (
    add_cart_item,
    create_cart_checkout,
    make_guest_purchase_token,
    place_cart_purchase,
)
from apps.checkout.views import _enforce_web_rate
from apps.integrations.models import IntegrationConfig
from apps.storefront.models import StudioProject
from tests.v2_6_helpers import User, fill_guest_shipping, make_catalog, seed_guest_identity


@pytest.mark.django_db
def test_different_guest_sessions_cannot_mutate_each_others_cart(client):
    _, product, variant = make_catalog("isoguest")
    first_identity = seed_guest_identity(client, "guest-one")
    first_item = add_cart_item(customer=None, guest_identity=first_identity, product=product, variant=variant, quantity=1, kind=CartItem.Kind.PLAIN)

    from django.test import Client
    other = Client()
    seed_guest_identity(other, "guest-two")
    response = other.post(reverse("cart-item-update", kwargs={"pk": first_item.pk}), {"quantity": 9})
    assert response.status_code == 302
    first_item.refresh_from_db()
    assert first_item.quantity == 1
    assert Cart.objects.filter(customer__isnull=True, status=Cart.Status.ACTIVE).count() >= 1


@pytest.mark.django_db
def test_guest_product_web_flow_adds_to_cart_without_user_and_studio_still_redirects_login(client):
    _, product, variant = make_catalog("webguest", customization=True)
    before_users = User.objects.count()
    product_url = reverse("public-store-product", kwargs={"store_slug": product.storefront.slug, "product_slug": product.slug})
    page = client.get(product_url)
    assert page.status_code == 200
    assert b"Add to Cart" in page.content
    assert b"Sign in to customize" in page.content
    response = client.post(reverse("cart-add-product", kwargs={"product_id": product.pk}), {"variant": variant.pk, "quantity": 2})
    assert response.status_code == 302 and response.url == reverse("cart")
    assert User.objects.count() == before_users
    assert StudioProject.objects.count() == 0
    studio = client.get(f"{reverse('studio')}?product={product.pk}")
    assert studio.status_code == 302
    assert "/account/login/" in studio.url or "/account/two_factor/" in studio.url or "login" in studio.url


@pytest.mark.django_db
def test_guest_checkout_requires_email_and_shipping_fields():
    _, product, variant = make_catalog("guestrequired")
    identity = "guest-required"
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN).cart
    checkout = create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity)
    with pytest.raises(ValidationError, match="email"):
        place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="cod")


@pytest.mark.django_db
def test_secure_guest_purchase_access_requires_signed_token_and_is_private(client):
    _, product, variant = make_catalog("secureguest")
    identity = seed_guest_identity(client, "guest-secure")
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN).cart
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity)
    purchase, _ = place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="cod")
    token = make_guest_purchase_token(purchase)

    numeric = client.get(reverse("purchase-detail", kwargs={"pk": purchase.pk}))
    assert numeric.status_code == 302
    invalid = client.get(reverse("guest-purchase-detail", kwargs={"token": "invalid-token"}))
    assert invalid.status_code == 404
    valid = client.get(reverse("guest-purchase-detail", kwargs={"token": token}))
    assert valid.status_code == 200
    assert b'content="noindex,nofollow,noarchive"' in valid.content
    head = valid.content.split(b"</head>", 1)[0]
    assert token.encode() not in head
    assert purchase.shipping_snapshot["email"].encode() not in head


@pytest.mark.django_db
def test_unrelated_authenticated_user_cannot_use_guest_purchase_token(client):
    _, product, variant = make_catalog("authdenyguest")
    identity = "guest-auth-deny"
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN).cart
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity)
    purchase, _ = place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="cod")
    token = make_guest_purchase_token(purchase)
    intruder = User.objects.create_user(username="guest-token-intruder", password="password12345")
    client.force_login(intruder)
    response = client.get(reverse("guest-purchase-detail", kwargs={"token": token}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_guest_confirmation_email_state_is_truthful_when_mailgun_unavailable():
    _, product, variant = make_catalog("guestemail")
    IntegrationConfig.objects.filter(provider=IntegrationConfig.Provider.MAILGUN).update(enabled=False)
    identity = "guest-email"
    cart = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN).cart
    checkout = fill_guest_shipping(create_cart_checkout(cart=cart, actor=AnonymousUser(), guest_identity=identity), identity, email="guest-mail@example.test")
    purchase, _ = place_cart_purchase(session=checkout, actor=AnonymousUser(), guest_identity=identity, payment_method="cod")
    purchase.refresh_from_db()
    assert purchase.guest_confirmation_email_status == CustomerPurchase.GuestEmailStatus.SKIPPED
    assert purchase.guest_confirmation_email_updated_at is not None


@override_settings(REST_FRAMEWORK={"DEFAULT_THROTTLE_RATES": {"anon": "1/hour", "customer_place": "1/hour"}})
def test_guest_web_rate_limit_reuses_existing_rate_configuration():
    cache.clear()
    request = RequestFactory().post("/checkout/1/")
    request.user = AnonymousUser()
    class Session(dict):
        modified = False
    request.session = Session({GUEST_SESSION_KEY: "rate-guest"})
    _enforce_web_rate(request, "place")
    with pytest.raises(PermissionDenied, match="Too many requests"):
        _enforce_web_rate(request, "place")


@pytest.mark.django_db
def test_arabic_guest_cart_and_checkout_render_rtl(client):
    _, product, variant = make_catalog("arabicguest")
    identity = seed_guest_identity(client, "guest-ar")
    add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, kind=CartItem.Kind.PLAIN)
    cart = client.get(f"{reverse('cart')}?lang=ar")
    assert cart.status_code == 200 and b'dir="rtl"' in cart.content
    checkout_start = client.get(reverse("cart-checkout-start"))
    checkout = client.get(f"{checkout_start.url}?lang=ar")
    assert checkout.status_code == 200 and b'dir="rtl"' in checkout.content
