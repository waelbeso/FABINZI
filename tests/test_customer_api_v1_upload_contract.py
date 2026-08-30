import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.media.services import STUDIO_IMAGE_MAX_BYTES
from tests.test_commerce_extension import make_catalog

User = get_user_model()


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _project(client, product, variant):
    response = client.post(
        reverse("v1:customer:studio-projects"),
        {"store_slug": product.storefront.slug, "product_slug": product.slug, "variant_sku": variant.sku},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["id"]


@pytest.mark.django_db
def test_customer_studio_upload_rejects_non_multipart_with_standard_415_error():
    customer = User.objects.create_user(username="upload-415", password="password12345")
    _org, product, variant = make_catalog("upload-415", customization=True)
    client = _auth(customer)
    project_id = _project(client, product, variant)

    response = client.post(
        reverse("v1:customer:studio-upload", kwargs={"project_id": project_id}),
        {"file": "not-a-multipart-file"},
        format="json",
    )
    assert response.status_code == 415
    assert response.data["error"]["code"] == "unsupported_media_type"
    assert set(response.data["error"]) == {"code", "message", "fields", "request_id"}


@pytest.mark.django_db
def test_customer_studio_upload_rejects_over_10mb_with_413_without_storage_leak():
    customer = User.objects.create_user(username="upload-413", password="password12345")
    _org, product, variant = make_catalog("upload-413", customization=True)
    client = _auth(customer)
    project_id = _project(client, product, variant)
    upload = SimpleUploadedFile(
        "too-large.png",
        b"x" * (STUDIO_IMAGE_MAX_BYTES + 1),
        content_type="image/png",
    )

    response = client.post(
        reverse("v1:customer:studio-upload", kwargs={"project_id": project_id}),
        {"file": upload},
        format="multipart",
    )
    assert response.status_code == 413
    assert response.data["error"]["code"] == "upload_error"
    assert "file" in response.data["error"]["fields"]
    serialized = str(response.data).lower()
    for forbidden in ("provider_asset_id", "studio-private/", "bucket", "access_key", "secret_key"):
        assert forbidden not in serialized
