import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from apps.checkout.models import Cart, CartItem, CheckoutSession
from apps.checkout.services import (
    GuestCartMergeConflict,
    add_cart_item,
    create_cart_checkout,
    get_active_cart,
    merge_guest_cart_into_customer,
)
from apps.storefront.models import StudioProject
from tests.v2_6_helpers import User, make_catalog, seed_guest_identity


@pytest.mark.django_db
def test_guest_cart_adopted_when_customer_has_no_active_cart():
    customer = User.objects.create_user(username="adopt-customer", password="password12345")
    _, product, variant = make_catalog("adopt")
    identity = "guest-adopt"
    item = add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, quantity=2, kind=CartItem.Kind.PLAIN)
    guest_cart_id = item.cart_id
    checkout = create_cart_checkout(cart=item.cart, actor=AnonymousUser(), guest_identity=identity)

    merged = merge_guest_cart_into_customer(guest_identity=identity, customer=customer)
    merged.refresh_from_db()
    checkout.refresh_from_db()
    assert merged.pk == guest_cart_id
    assert merged.customer_id == customer.pk and merged.guest_key_hash == ""
    assert merged.status == Cart.Status.ACTIVE
    assert checkout.customer_id == customer.pk and checkout.status == CheckoutSession.Status.DRAFT
    assert Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).count() == 1


@pytest.mark.django_db
def test_guest_existing_customer_merge_combines_identical_plain_and_keeps_distinct():
    customer = User.objects.create_user(username="merge-customer", password="password12345")
    _, product_a, variant_a = make_catalog("mergeplain")
    _, product_b, variant_b = make_catalog("mergedistinct")
    account_item = add_cart_item(customer=customer, product=product_a, variant=variant_a, quantity=2, kind=CartItem.Kind.PLAIN)
    identity = "guest-merge"
    guest_same = add_cart_item(customer=None, guest_identity=identity, product=product_a, variant=variant_a, quantity=3, kind=CartItem.Kind.PLAIN)
    guest_source = guest_same.cart
    add_cart_item(customer=None, guest_identity=identity, product=product_b, variant=variant_b, quantity=4, kind=CartItem.Kind.PLAIN)

    merged = merge_guest_cart_into_customer(guest_identity=identity, customer=customer)
    assert merged.pk == account_item.cart_id
    assert merged.items.count() == 2
    assert merged.items.get(store_product=product_a, variant=variant_a).quantity == 5
    assert merged.items.get(store_product=product_b, variant=variant_b).quantity == 4
    guest_source.refresh_from_db()
    assert guest_source.status == Cart.Status.CONVERTED and guest_source.merged_into_id == merged.pk
    assert Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).count() == 1


@pytest.mark.django_db
def test_guest_ready_designed_identical_lines_combine():
    customer = User.objects.create_user(username="ready-merge-customer", password="password12345")
    _, product, variant = make_catalog("readymerge", ready=True)
    account = add_cart_item(customer=customer, product=product, variant=variant, quantity=1, kind=CartItem.Kind.READY_DESIGNED).cart
    identity = "guest-ready-merge"
    add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, quantity=2, kind=CartItem.Kind.READY_DESIGNED)
    merged = merge_guest_cart_into_customer(guest_identity=identity, customer=customer)
    assert merged.pk == account.pk
    line = merged.items.get(kind=CartItem.Kind.READY_DESIGNED, store_product=product, variant=variant)
    assert line.quantity == 3 and line.studio_project_id is None


@pytest.mark.django_db
def test_repeated_merge_is_idempotent():
    customer = User.objects.create_user(username="idempotent-merge", password="password12345")
    _, product, variant = make_catalog("idemmerge")
    add_cart_item(customer=customer, product=product, variant=variant, quantity=1, kind=CartItem.Kind.PLAIN)
    identity = "guest-idempotent"
    add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, quantity=2, kind=CartItem.Kind.PLAIN)
    first = merge_guest_cart_into_customer(guest_identity=identity, customer=customer)
    second = merge_guest_cart_into_customer(guest_identity=identity, customer=customer)
    assert first.pk == second.pk
    assert second.items.get(store_product=product).quantity == 3
    assert Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).count() == 1


@pytest.mark.django_db
def test_incompatible_currency_merge_preserves_both_active_carts():
    customer = User.objects.create_user(username="currency-merge", password="password12345")
    _, egp_product, egp_variant = make_catalog("mergeegp", currency="EGP")
    _, usd_product, usd_variant = make_catalog("mergeusd", currency="USD")
    account_cart = add_cart_item(customer=customer, product=usd_product, variant=usd_variant, kind=CartItem.Kind.PLAIN).cart
    identity = "guest-currency"
    guest_cart = add_cart_item(customer=None, guest_identity=identity, product=egp_product, variant=egp_variant, kind=CartItem.Kind.PLAIN).cart

    with pytest.raises(GuestCartMergeConflict):
        merge_guest_cart_into_customer(guest_identity=identity, customer=customer)

    account_cart.refresh_from_db(); guest_cart.refresh_from_db()
    assert account_cart.status == Cart.Status.ACTIVE
    assert guest_cart.status == Cart.Status.ACTIVE and guest_cart.merged_into_id is None
    assert account_cart.items.count() == 1 and guest_cart.items.count() == 1


@pytest.mark.django_db
def test_failed_merge_is_atomic_and_does_not_partially_transfer():
    customer = User.objects.create_user(username="atomic-merge", password="password12345")
    _, target_product, target_variant = make_catalog("atomictarget")
    _, valid_product, valid_variant = make_catalog("atomicvalid")
    _, stale_product, stale_variant = make_catalog("atomicstale")
    account_item = add_cart_item(customer=customer, product=target_product, variant=target_variant, quantity=7, kind=CartItem.Kind.PLAIN)
    identity = "guest-atomic"
    guest_cart = add_cart_item(customer=None, guest_identity=identity, product=valid_product, variant=valid_variant, quantity=2, kind=CartItem.Kind.PLAIN).cart
    add_cart_item(customer=None, guest_identity=identity, product=stale_product, variant=stale_variant, quantity=3, kind=CartItem.Kind.PLAIN)
    stale_product.status = stale_product.Status.HIDDEN
    stale_product.save(update_fields=["status", "updated_at"])

    with pytest.raises(GuestCartMergeConflict):
        merge_guest_cart_into_customer(guest_identity=identity, customer=customer)

    account_item.refresh_from_db(); guest_cart.refresh_from_db()
    assert account_item.quantity == 7
    assert account_item.cart.items.count() == 1
    assert guest_cart.status == Cart.Status.ACTIVE and guest_cart.items.count() == 2


@pytest.mark.django_db
def test_guest_cannot_add_studio_and_no_fake_user_or_project_is_created():
    _, product, variant = make_catalog("gueststudio", customization=True)
    before_users = User.objects.count()
    before_projects = StudioProject.objects.count()
    with pytest.raises(PermissionDenied):
        add_cart_item(
            customer=None,
            guest_identity="guest-studio",
            product=product,
            variant=variant,
            kind=CartItem.Kind.STUDIO,
            studio_project=None,
        )
    assert User.objects.count() == before_users
    assert StudioProject.objects.count() == before_projects


@pytest.mark.django_db
def test_login_signal_merges_guest_cart_without_creating_second_active_cart(client):
    customer = User.objects.create_user(username="login-merge", password="password12345")
    _, product, variant = make_catalog("loginsignal")
    add_cart_item(customer=customer, product=product, variant=variant, quantity=1, kind=CartItem.Kind.PLAIN)
    identity = seed_guest_identity(client, "guest-login-signal")
    add_cart_item(customer=None, guest_identity=identity, product=product, variant=variant, quantity=2, kind=CartItem.Kind.PLAIN)
    assert client.login(username="login-merge", password="password12345")
    active = Cart.objects.get(customer=customer, status=Cart.Status.ACTIVE)
    assert active.items.get(store_product=product).quantity == 3
    assert Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).count() == 1
