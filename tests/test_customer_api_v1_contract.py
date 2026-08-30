import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.artwork.models import ArtworkAsset
from apps.checkout.services import add_cart_item, create_cart_checkout, get_active_cart, place_cart_purchase
from apps.media.models import MediaAsset
from apps.notifications.models import Notification
from tests.conftest import VALID_PNG
from tests.test_commerce_extension import fill_shipping, make_catalog

User = get_user_model()


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _make_public_catalog(prefix="contract", *, customization=True):
    org, product, variant = make_catalog(prefix, customization=customization)
    product.storefront.name_ar = "متجر الاختبار"
    product.storefront.about_en = "English storefront"
    product.storefront.about_ar = "واجهة عربية"
    product.storefront.save(update_fields=["name_ar", "about_en", "about_ar", "updated_at"])
    product.title_ar = "منتج عربي"
    product.description_en = "English description"
    product.description_ar = "وصف عربي"
    product.save(update_fields=["title_ar", "description_en", "description_ar", "updated_at"])

    product_image = product.images.first().media_asset
    product_image.metadata = {"public_url": f"https://cdn.example.test/{prefix}-product.png", "width": 800, "height": 800}
    product_image.save(update_fields=["metadata"])

    version = product.designed_product.artwork_version
    version.metadata = {"suitable_for_print": True, "public_production_methods": ["print"]}
    version.save(update_fields=["metadata"])
    preview = MediaAsset.objects.create(
        provider=MediaAsset.Provider.CLOUDFLARE_IMAGES,
        provider_asset_id=f"https://cdn.example.test/{prefix}-art.png",
        original_filename="art.png",
        mime_type="image/png",
        size_bytes=123,
        access=MediaAsset.Access.PUBLIC,
        metadata={"public_url": f"https://cdn.example.test/{prefix}-art.png", "width": 600, "height": 600},
        uploaded_by=product.designed_product.created_by,
    )
    ArtworkAsset.objects.create(version=version, kind=ArtworkAsset.Kind.PREVIEW, media_asset=preview)
    return org, product, variant, version


@pytest.mark.django_db
def test_public_store_and_product_contract_is_paginated_localized_and_supply_safe():
    _org, product, variant, _version = _make_public_catalog("discover")
    client = APIClient()

    stores = client.get(reverse("v1:customer:stores"), {"q": "discover"})
    assert stores.status_code == 200
    assert set(stores.data) == {"count", "next", "previous", "results"}
    assert stores.data["count"] == 1
    assert stores.data["results"][0]["slug"] == product.storefront.slug

    products = client.get(reverse("v1:customer:products"), {"store": product.storefront.slug, "customizable": "true"}, HTTP_ACCEPT_LANGUAGE="ar")
    assert products.status_code == 200
    assert products.data["count"] == 1
    row = products.data["results"][0]
    assert row["title"] == "منتج عربي"
    assert row["description"] == "وصف عربي"
    assert row["base_price"] == {"amount": "500.00", "currency": "EGP"}
    assert row["variants"][0]["sku"] == variant.sku
    assert isinstance(row["variants"][0]["available"], bool)
    assert row["images"][0] == {
        "url": "https://cdn.example.test/discover-product.png",
        "width": 800,
        "height": 800,
        "alt": "",
    }
    serialized = str(row).lower()
    for forbidden in ("stock_quantity", "price_adjustment", "manufacturer", "rfq", "unit_cost", "technical_specs", "tech_pack", "commission"):
        assert forbidden not in serialized

    detail = client.get(reverse("v1:customer:product-detail", kwargs={"store_slug": product.storefront.slug, "product_slug": product.slug}), HTTP_ACCEPT_LANGUAGE="en")
    assert detail.status_code == 200
    assert detail.data["title"] == product.title_en
    assert detail.data["decoration_zones"][0]["name"] == "Front"
    assert detail.data["decoration_zones"][0]["placement"] == {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6}


@pytest.mark.django_db
def test_artwork_marketplace_contract_freezes_real_filters_and_public_fields_only():
    org, product, _variant, version = _make_public_catalog("art-filter")
    artwork = version.artwork
    artwork.title = "Print Horizon"
    artwork.description = "A print-ready public work"
    artwork.tags = ["print", "modern"]
    artwork.save(update_fields=["title", "description", "tags", "updated_at"])

    client = APIClient()
    response = client.get(reverse("v1:customer:artworks"), {"q": "Horizon", "method": "print"})
    assert response.status_code == 200
    assert response.data["count"] == 1
    row = response.data["results"][0]
    assert row["id"] == artwork.pk
    assert row["approved_version_id"] == version.pk
    assert row["creator"] == {"name": org.display_name}
    assert row["preview"] == {"url": "https://cdn.example.test/art-filter-art.png", "width": 600, "height": 600}
    assert row["production_methods"] == ["print"]
    assert "metadata" not in row
    assert "production_notes" not in row

    invalid = client.get(reverse("v1:customer:artworks"), {"method": "laser"})
    assert invalid.status_code == 400
    assert invalid.data["error"]["code"] == "validation_error"
    assert "method" in invalid.data["error"]["fields"]


@pytest.mark.django_db
def test_studio_contract_reconstructs_normalized_persisted_state():
    customer = User.objects.create_user(username="studio-contract", password="password12345")
    _org, product, variant, _version = _make_public_catalog("studio-contract")
    client = _auth(customer)

    created = client.post(
        reverse("v1:customer:studio-projects"),
        {"store_slug": product.storefront.slug, "product_slug": product.slug, "variant_sku": variant.sku, "quantity": 1, "customer_notes": "mobile draft"},
        format="json",
    )
    assert created.status_code == 201, created.data
    project_id = created.data["id"]
    assert created.data["status"] == "draft"
    assert created.data["variant"]["sku"] == variant.sku
    assert created.data["decoration_zones"][0]["name"] == "Front"

    enabled = client.post(reverse("v1:customer:studio-customization", kwargs={"project_id": project_id}), {}, format="json")
    assert enabled.status_code == 201
    element = client.post(
        reverse("v1:customer:studio-element", kwargs={"project_id": project_id}),
        {
            "kind": "text",
            "decoration_zone": "Front",
            "text": "FABINZI",
            "production_method": "print",
            "transform": {"x": 0.5, "y": 0.5, "scale": 0.3, "rotation": 370},
            "style": {"font": "sans"},
            "rights_confirmed": False,
        },
        format="json",
    )
    assert element.status_code == 201, element.data
    assert element.data["transform"] == {"x": 0.5, "y": 0.5, "scale": 0.3, "rotation": 10.0}

    reloaded = client.get(reverse("v1:customer:studio-project-detail", kwargs={"project_id": project_id}))
    assert reloaded.status_code == 200
    assert reloaded.data["elements"][0]["text"] == "FABINZI"
    assert reloaded.data["elements"][0]["transform"]["rotation"] == 10.0
    validation = client.get(reverse("v1:customer:studio-validation", kwargs={"project_id": project_id}))
    assert validation.status_code == 200
    assert validation.data["valid"] is True
    assert validation.data["unit_price"] == {"amount": "500.00", "currency": "EGP"}
    ready = client.post(reverse("v1:customer:studio-ready", kwargs={"project_id": project_id}), {}, format="json")
    assert ready.status_code == 200
    assert ready.data["status"] == "ready"
    assert ready.data["ready_at"] is not None


@pytest.mark.django_db
def test_private_upload_contract_returns_application_url_not_storage_key_and_enforces_owner():
    owner = User.objects.create_user(username="upload-owner", password="password12345")
    other = User.objects.create_user(username="upload-other", password="password12345")
    _org, product, variant, _version = _make_public_catalog("upload-contract")
    owner_client = _auth(owner)
    project = owner_client.post(reverse("v1:customer:studio-projects"), {"store_slug": product.storefront.slug, "product_slug": product.slug, "variant_sku": variant.sku}, format="json")
    assert project.status_code == 201
    project_id = project.data["id"]

    upload = SimpleUploadedFile("private.png", VALID_PNG, content_type="image/png")
    response = owner_client.post(reverse("v1:customer:studio-upload", kwargs={"project_id": project_id}), {"file": upload}, format="multipart")
    assert response.status_code == 201, response.data
    assert response.data["mime_type"] == "image/png"
    assert response.data["size_bytes"] > 0
    assert response.data["access_url"] == f"/api/v1/customer/media/{response.data['id']}/"
    serialized = str(response.data).lower()
    for forbidden in ("provider_asset_id", "studio-private/", "bucket", "access_key", "secret"):
        assert forbidden not in serialized

    owner_access = owner_client.get(response.data["access_url"])
    other_access = _auth(other).get(response.data["access_url"])
    assert owner_access.status_code == 200
    assert other_access.status_code == 404


@pytest.mark.django_db
def test_notification_feed_is_paginated_localized_and_uses_parent_purchase_deep_link():
    customer = User.objects.create_user(username="notification-contract", password="password12345")
    _org, product, variant, _version = _make_public_catalog("notification-contract", customization=False)
    add_cart_item(customer=customer, product=product, variant=variant, quantity=1, kind="plain")
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(customer), actor=customer), customer)
    purchase, _attempt = place_cart_purchase(session=session, actor=customer, payment_method="cod")
    Notification.objects.filter(recipient=customer).delete()
    for index in range(24):
        Notification.objects.create(
            recipient=customer,
            type="general",
            title_en=f"Notice {index}",
            title_ar=f"تنبيه {index}",
            body_en=f"Body {index}",
            body_ar=f"نص {index}",
            destination="",
        )
    Notification.objects.create(
        recipient=customer,
        type="order_status",
        title_en="Purchase update",
        title_ar="تحديث الطلب",
        body_en="Your purchase has an update.",
        body_ar="يوجد تحديث على طلبك.",
        destination=f"/purchases/{purchase.pk}/",
    )
    client = _auth(customer)
    response = client.get(reverse("v1:customer:notifications"), HTTP_ACCEPT_LANGUAGE="ar")
    assert response.status_code == 200
    assert response.data["count"] == 25
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None
    targeted = next(row for row in response.data["results"] if row["type"] == "order_status")
    assert targeted["title"] == "تحديث الطلب"
    assert targeted["target"] == {"resource": "purchase", "reference": str(purchase.number)}
    assert "destination" not in targeted

    preferences = client.patch(reverse("v1:customer:notification-preferences"), {"email_enabled": True, "sms_enabled": False}, format="json")
    assert preferences.status_code == 200
    assert preferences.data["email_enabled"] is True
    assert preferences.data["sms_enabled"] is False
