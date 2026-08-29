from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.artwork.designer_services import add_validated_product_placement, normalize_designed_product_transform
from apps.artwork.models import Artwork, ArtworkVersion
from apps.artwork.services import create_designed_product, publish_designed_product
from apps.checkout.models import CheckoutSession, CustomerOrder, OrderItem
from apps.design.designer_services import delete_decoration_zone, delete_size_row, save_decoration_zone, save_size_row, update_version_definition
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion, SizeChartRow, TechnicalReview
from apps.design.services import create_design, create_revision, review_version
from apps.finance.models import FinancePolicy, LedgerEntry, PayoutProfile
from apps.finance.services import account_balance, organization_account, request_settlement
from apps.manufacturer_marketplace.services import add_capability, create_rfq, get_or_create_listing, open_rfq, publish_listing, select_quote, submit_quote
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization
from apps.storefront.designer_services import hide_store_product, update_store_product, update_variant
from apps.storefront.models import StoreProduct, StoreProductImage
from apps.storefront.services import add_variant, create_store_product, create_storefront, publish_store_product, publish_storefront

User = get_user_model()


def active_designer(user, name="Designer Studio", role=Membership.Role.OWNER):
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name=name, email=f"{name.lower().replace(' ', '-')}@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=user)
    Membership.objects.create(organization=org, user=user, role=role)
    DesignerProfile.objects.create(organization=org, studio_name=name, terms_accepted=True)
    OnboardingApplication.objects.create(organization=org, status=OnboardingApplication.Status.APPROVED)
    return org


def approved_inputs(org, user, *, category="apparel", method=DecorationZone.Method.BOTH):
    design = GarmentDesign.objects.create(organization=org, title="Core Tee", category=category, status=GarmentDesign.Status.APPROVED, created_by=user)
    garment = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, base_material="Cotton", technical_specs={"gsm": "180"}, created_by=user)
    zone = DecorationZone.objects.create(version=garment, name="Front", method=method, placement={"x": 0.5, "y": 0.42}, max_width_mm=220, max_height_mm=280)
    artwork = Artwork.objects.create(organization=org, title="Wave", status=Artwork.Status.APPROVED, created_by=user)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, metadata={"public_production_methods": ["print", "embroidery"]}, created_by=user)
    return garment, zone, artwork_version


def published_designed_product(org, user):
    garment, zone, artwork_version = approved_inputs(org, user)
    product = create_designed_product(organization=org, actor=user, garment_version=garment, artwork_version=artwork_version, title="Wave Tee")
    add_validated_product_placement(product=product, actor=user, decoration_zone=zone, transform={"x": .5, "y": .5, "scale": .3, "rotation": 12}, production_method="print")
    publish_designed_product(product=product, actor=user)
    return product, garment, zone, artwork_version


def public_image(user, key="/static/test-product.png"):
    return MediaAsset.objects.create(provider=MediaAsset.Provider.CLOUDFLARE_IMAGES, provider_asset_id=key, original_filename="product.png", mime_type="image/png", size_bytes=10, access=MediaAsset.Access.PUBLIC, uploaded_by=user, metadata={"public_url": key})


@pytest.mark.django_db
def test_garment_create_search_and_revision_workflow(client):
    owner = User.objects.create_user(username="design-owner", password="password123")
    staff = User.objects.create_user(username="design-staff", password="password123", is_staff=True)
    org = active_designer(owner)
    design = create_design(organization=org, actor=owner, title="Structured Jacket", category="outerwear")
    version = design.versions.get()
    update_version_definition(version=version, actor=owner, data={"base_material": "Wool", "technical_specs": {"weight_gsm": "320"}})
    save_size_row(version=version, actor=owner, size_label="M", measurements={"chest_cm": "54"})
    save_decoration_zone(version=version, actor=owner, name="Chest", method="embroidery", placement={"x": .5, "y": .35})
    version.status = GarmentDesignVersion.Status.SUBMITTED; version.save(update_fields=["status"])
    design.status = GarmentDesign.Status.IN_REVIEW; design.save(update_fields=["status"])
    review_version(version=version, reviewer=staff, decision=TechnicalReview.Decision.REVISION_REQUIRED, notes="Adjust seam allowance")
    revision = create_revision(design=design, actor=owner)
    assert revision.version_number == 2
    assert revision.size_rows.filter(size_label="M").exists()
    client.force_login(owner)
    response = client.get(f"/designer/designs/?org={org.pk}&q=Structured&status=draft")
    assert response.status_code == 200


@pytest.mark.django_db
def test_submitted_version_definition_is_immutable():
    owner = User.objects.create_user(username="immutable-owner", password="password123")
    org = active_designer(owner)
    version = create_design(organization=org, actor=owner, title="Immutable").versions.get()
    version.status = GarmentDesignVersion.Status.SUBMITTED; version.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        update_version_definition(version=version, actor=owner, data={"base_material": "Changed"})


@pytest.mark.django_db
def test_size_chart_crud_and_cross_version_protection():
    owner = User.objects.create_user(username="size-owner", password="password123")
    org = active_designer(owner)
    v1 = create_design(organization=org, actor=owner, title="A").versions.get()
    v2 = create_design(organization=org, actor=owner, title="B").versions.get()
    row = save_size_row(version=v1, actor=owner, size_label="M", measurements={"chest_cm": 52})
    row = save_size_row(version=v1, actor=owner, row=row, size_label="M", measurements={"chest_cm": 53})
    assert row.measurements["chest_cm"] == 53
    with pytest.raises(ValidationError):
        save_size_row(version=v2, actor=owner, row=row, size_label="M", measurements={})
    delete_size_row(row=row, actor=owner)
    assert not SizeChartRow.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
def test_decoration_zone_normalization_and_invalid_values():
    owner = User.objects.create_user(username="zone-owner", password="password123")
    org = active_designer(owner)
    version = create_design(organization=org, actor=owner, title="Zone Tee").versions.get()
    zone = save_decoration_zone(version=version, actor=owner, name="Front", method="print", placement={"x": "0.50000", "y": "0.25000"})
    assert zone.placement == {"x": .5, "y": .25}
    with pytest.raises(ValidationError):
        save_decoration_zone(version=version, actor=owner, name="Bad", method="print", placement={"x": 1.2, "y": .5})
    with pytest.raises(ValidationError):
        save_decoration_zone(version=version, actor=owner, name="Bad method", method="laser", placement={"x": .5, "y": .5})


@pytest.mark.django_db
def test_referenced_decoration_zone_cannot_be_deleted():
    owner = User.objects.create_user(username="zone-protected", password="password123")
    org = active_designer(owner)
    product, garment, zone, _ = published_designed_product(org, owner)
    garment.status = GarmentDesignVersion.Status.DRAFT; garment.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        delete_decoration_zone(zone=zone, actor=owner)
    assert DecorationZone.objects.filter(pk=zone.pk).exists()


@pytest.mark.django_db
def test_designed_product_requires_same_org_and_approved_inputs():
    owner = User.objects.create_user(username="product-owner", password="password123")
    other = User.objects.create_user(username="product-other", password="password123")
    org = active_designer(owner, "Product A")
    other_org = active_designer(other, "Product B")
    garment, _, artwork_version = approved_inputs(org, owner)
    foreign_garment, _, _ = approved_inputs(other_org, other)
    with pytest.raises(ValidationError):
        create_designed_product(organization=org, actor=owner, garment_version=foreign_garment, artwork_version=artwork_version, title="Cross")
    garment.status = GarmentDesignVersion.Status.DRAFT; garment.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        create_designed_product(organization=org, actor=owner, garment_version=garment, artwork_version=artwork_version, title="Draft")


@pytest.mark.django_db
def test_designed_product_transform_persists_and_bounds_are_enforced():
    owner = User.objects.create_user(username="transform-owner", password="password123")
    org = active_designer(owner)
    garment, zone, artwork_version = approved_inputs(org, owner, method=DecorationZone.Method.PRINT)
    product = create_designed_product(organization=org, actor=owner, garment_version=garment, artwork_version=artwork_version, title="Placement")
    placement = add_validated_product_placement(product=product, actor=owner, decoration_zone=zone, transform={"x": .5, "y": .5, "scale": .3, "rotation": 33}, production_method="print")
    placement.refresh_from_db()
    assert placement.transform == {"x": .5, "y": .5, "scale": .3, "rotation": 33.0}
    with pytest.raises(ValidationError):
        normalize_designed_product_transform({"x": .02, "y": .5, "scale": .5, "rotation": 45})
    with pytest.raises(ValidationError):
        add_validated_product_placement(product=product, actor=owner, decoration_zone=zone, transform={"x": .5, "y": .5, "scale": .2}, production_method="embroidery")


@pytest.mark.django_db
def test_designed_product_publish_requires_placement():
    owner = User.objects.create_user(username="publish-owner", password="password123")
    org = active_designer(owner)
    garment, _, artwork_version = approved_inputs(org, owner)
    product = create_designed_product(organization=org, actor=owner, garment_version=garment, artwork_version=artwork_version, title="No Placement")
    with pytest.raises(ValidationError):
        publish_designed_product(product=product, actor=owner)


def manufacturer_org(user, name):
    org = Organization.objects.create(kind=Organization.Kind.MANUFACTURER, display_name=name, email=f"{name.lower().replace(' ', '-')}@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=user)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    listing = get_or_create_listing(organization=org, actor=user)
    listing.headline_en = f"{name} manufacturing"; listing.save()
    add_capability(listing=listing, actor=user, capability_type="cut_sew", name="Apparel", min_quantity=10, max_quantity=1000, lead_time_days=14)
    publish_listing(listing=listing, actor=user)
    return org


@pytest.mark.django_db
def test_rfq_real_quote_comparison_and_selection_integrity(client):
    owner = User.objects.create_user(username="rfq-owner", password="password123")
    m1 = User.objects.create_user(username="rfq-m1", password="password123")
    m2 = User.objects.create_user(username="rfq-m2", password="password123")
    org = active_designer(owner, "RFQ Studio")
    product, *_ = published_designed_product(org, owner)
    factory1 = manufacturer_org(m1, "Factory One")
    factory2 = manufacturer_org(m2, "Factory Two")
    rfq = create_rfq(designer_organization=org, actor=owner, designed_product=product, title="Summer Run", quantity=100)
    open_rfq(rfq=rfq, actor=owner, manufacturer_ids=[factory1.pk, factory2.pk])
    q1 = submit_quote(invitation=rfq.invitations.get(manufacturer=factory1), actor=m1, unit_price="120", setup_fee="500", production_lead_days=12, minimum_order_quantity=50)
    q2 = submit_quote(invitation=rfq.invitations.get(manufacturer=factory2), actor=m2, unit_price="125", setup_fee="0", production_lead_days=9, minimum_order_quantity=20)
    selection = select_quote(quote=q2, actor=owner)
    assert selection.rfq_id == rfq.pk and selection.manufacturer_id == factory2.pk
    assert q1.estimated_total == Decimal("12500")
    client.force_login(owner)
    response = client.get(f"/designer/rfqs/{rfq.pk}/?org={org.pk}")
    text = response.content.decode("utf-8")
    assert "120" in text and "125" in text
    assert "Real submitted quote data with no fabricated Manufacturer ranking or score." in text
    assert 'aria-label="rating"' not in text.lower()
    assert "score:" not in text.lower()


@pytest.mark.django_db
def test_cross_designer_cannot_open_or_view_another_rfq(client):
    owner = User.objects.create_user(username="rfq-a", password="password123")
    other = User.objects.create_user(username="rfq-b", password="password123")
    org = active_designer(owner, "RFQ A")
    other_org = active_designer(other, "RFQ B")
    product, *_ = published_designed_product(org, owner)
    rfq = create_rfq(designer_organization=org, actor=owner, designed_product=product, title="Private RFQ", quantity=25)
    with pytest.raises(PermissionDenied):
        open_rfq(rfq=rfq, actor=other, manufacturer_ids=[])
    client.force_login(other)
    response = client.get(f"/designer/rfqs/{rfq.pk}/?org={other_org.pk}")
    assert response.status_code == 404


def draft_store_product(org, owner, *, publish=False):
    designed, *_ = published_designed_product(org, owner)
    store = create_storefront(organization=org, actor=owner, slug=f"store-{org.pk}", name_en="Designer Store", name_ar="متجر المصمم")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(storefront=store, actor=owner, designed_product=designed, slug="wave-tee", title_en="Wave Tee", title_ar="تيشيرت ويف", base_price=Decimal("550.00"), currency="EGP", customization_enabled=True, fulfillment_mode=StoreProduct.FulfillmentMode.STOCK)
    variant = add_variant(product=product, actor=owner, sku=f"SKU-{org.pk}", size="M", stock_quantity=7)
    StoreProductImage.objects.create(product=product, media_asset=public_image(owner), alt_en="Wave Tee", alt_ar="تيشيرت ويف")
    if publish:
        publish_store_product(product=product, actor=owner)
    return store, product, variant


@pytest.mark.django_db
def test_store_uses_same_public_records_real_price_stock_and_customization(client):
    owner = User.objects.create_user(username="store-owner", password="password123")
    org = active_designer(owner, "Store Studio")
    store, product, variant = draft_store_product(org, owner, publish=True)
    client.force_login(owner)
    designer_response = client.get(f"/designer/store/products/{product.pk}/?org={org.pk}")
    assert designer_response.status_code == 200
    client.logout()
    public_response = client.get(f"/store/{store.slug}/{product.slug}/")
    assert public_response.status_code == 200
    body = public_response.content.decode("utf-8")
    assert product.title_en in body and "550" in body
    assert product.customization_enabled is True and variant.stock_quantity == 7


@pytest.mark.django_db
def test_store_requires_hide_before_commercial_or_variant_edit():
    owner = User.objects.create_user(username="store-edit", password="password123")
    org = active_designer(owner, "Store Edit")
    _, product, variant = draft_store_product(org, owner, publish=True)
    with pytest.raises(ValidationError):
        update_store_product(product=product, actor=owner, data={"base_price": Decimal("600")})
    with pytest.raises(ValidationError):
        update_variant(variant=variant, actor=owner, data={"stock_quantity": 4})
    hide_store_product(product=product, actor=owner)
    update_store_product(product=product, actor=owner, data={"base_price": Decimal("600")})
    update_variant(variant=variant, actor=owner, data={"stock_quantity": 4})
    product.refresh_from_db(); variant.refresh_from_db()
    assert product.base_price == Decimal("600") and variant.stock_quantity == 4


@pytest.mark.django_db
def test_store_cross_tenant_product_detail_is_404(client):
    owner = User.objects.create_user(username="store-a", password="password123")
    other = User.objects.create_user(username="store-b", password="password123")
    org = active_designer(owner, "Store A")
    other_org = active_designer(other, "Store B")
    _, product, _ = draft_store_product(org, owner)
    client.force_login(other)
    assert client.get(f"/designer/store/products/{product.pk}/?org={other_org.pk}").status_code == 404


def fulfillment_fixture(owner, org):
    customer = User.objects.create_user(username=f"customer-{org.pk}", password="password123", email=f"private-{org.pk}@customer.test")
    store, product, variant = draft_store_product(org, owner, publish=True)
    checkout = CheckoutSession.objects.create(customer=customer, status="placed", subtotal=550, total=550, currency="EGP")
    order = CustomerOrder.objects.create(checkout=checkout, customer=customer, designer_organization=org, status="confirmed", payment_method="cod", subtotal=550, total=550, currency="EGP", shipping_snapshot={"address": "PRIVATE CUSTOMER ADDRESS"})
    OrderItem.objects.create(order=order, store_product=product, variant=variant, sku=variant.sku, title=product.title_en, unit_price=550, quantity=1, line_total=550)
    fulfillment = FulfillmentRecord.objects.create(order=order, status=FulfillmentRecord.Status.SHIPPED, carrier="Carrier", tracking_number=f"TRACK-{org.pk}")
    return customer, order, fulfillment


@pytest.mark.django_db
def test_fulfillment_is_tenant_scoped_and_minimizes_customer_pii(client):
    owner = User.objects.create_user(username="fulfill-owner", password="password123")
    other = User.objects.create_user(username="fulfill-other", password="password123")
    org = active_designer(owner, "Fulfillment A")
    other_org = active_designer(other, "Fulfillment B")
    customer, order, fulfillment = fulfillment_fixture(owner, org)
    client.force_login(owner)
    body = client.get(f"/designer/fulfillment/?org={org.pk}").content.decode("utf-8")
    assert str(order.number) in body and fulfillment.tracking_number in body
    assert customer.email not in body and "PRIVATE CUSTOMER ADDRESS" not in body
    assert "Start production" not in body and "Record QC" not in body
    client.force_login(other)
    body = client.get(f"/designer/fulfillment/?org={other_org.pk}").content.decode("utf-8")
    assert str(order.number) not in body


@pytest.mark.django_db
def test_finance_isolation_earnings_term_and_masked_destination(client):
    owner = User.objects.create_user(username="finance-owner-new", password="password123")
    other = User.objects.create_user(username="finance-other-new", password="password123")
    org = active_designer(owner, "Finance A")
    other_org = active_designer(other, "Finance B")
    account = organization_account(org, "EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING, amount=Decimal("900"), currency="EGP", available_at=timezone.now(), memo="Order earnings")
    PayoutProfile.objects.create(organization=org, method="bank", account_holder="Finance A", destination_hint="****1234", status=PayoutProfile.Status.VERIFIED)
    client.force_login(owner)
    body = client.get(f"/designer/finance/?org={org.pk}").content.decode("utf-8")
    assert "Designer Earnings" in body and "****1234" in body
    assert "full account" not in body.lower()
    client.force_login(other)
    other_body = client.get(f"/designer/finance/?org={other_org.pk}").content.decode("utf-8")
    assert "900" not in other_body and "****1234" not in other_body


@pytest.mark.django_db
def test_settlement_requires_verified_profile_minimum_and_same_org():
    owner = User.objects.create_user(username="settle-owner-new", password="password123")
    other = User.objects.create_user(username="settle-other-new", password="password123")
    org = active_designer(owner, "Settle A")
    active_designer(other, "Settle B")
    FinancePolicy.objects.create(name="designer-acceptance", platform_fee_bps=1000, settlement_delay_days=0, minimum_payout=Decimal("100"), is_active=True)
    account = organization_account(org, "EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING, amount=Decimal("500"), currency="EGP", available_at=timezone.now())
    with pytest.raises(ValidationError):
        request_settlement(organization=org, actor=owner, amount=Decimal("200"), currency="EGP")
    PayoutProfile.objects.create(organization=org, method="bank", account_holder="A", destination_hint="****0001", status=PayoutProfile.Status.VERIFIED)
    with pytest.raises(ValidationError):
        request_settlement(organization=org, actor=owner, amount=Decimal("50"), currency="EGP")
    with pytest.raises(PermissionDenied):
        request_settlement(organization=org, actor=other, amount=Decimal("100"), currency="EGP")
    settlement = request_settlement(organization=org, actor=owner, amount=Decimal("200"), currency="EGP")
    assert settlement.amount == Decimal("200.00")
    assert account_balance(account)["reserved"] == Decimal("200.00")
