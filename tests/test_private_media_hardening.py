from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.media.models import MediaAsset
from apps.media.services import (
    ProductionStorageUnavailable,
    assert_production_file_storage,
    create_private_studio_image,
    private_media_response,
    private_media_storage_mode,
)

User = get_user_model()
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da63fcff1f0002eb01f58f59975b0000000049454e44ae426082"
)


def upload():
    return SimpleUploadedFile("private.png", PNG_1X1, content_type="image/png")


@pytest.mark.django_db
def test_test_environment_uses_private_local_storage_even_when_debug_is_false(tmp_path):
    owner = User.objects.create_user(username="local-test-owner", password="password12345")
    with override_settings(
        DEBUG=False,
        ENVIRONMENT="test",
        PRIVATE_MEDIA_STORAGE_MODE="local",
        MEDIA_ROOT=tmp_path,
    ):
        asset = create_private_studio_image(upload=upload(), owner=owner)
        assert private_media_storage_mode() == "local"

    assert asset.provider == MediaAsset.Provider.LOCAL_DEV
    assert asset.access == MediaAsset.Access.PRIVATE
    assert asset.uploaded_by == owner
    assert asset.provider_asset_id.startswith(f"studio-private/{owner.pk}/")


@pytest.mark.django_db
def test_production_s3_upload_is_private_and_stores_no_credentials():
    owner = User.objects.create_user(username="s3-owner", password="password12345")
    fake_config = SimpleNamespace(
        config={"bucket": "private-fabinzi-bucket", "region": "eu-central-1"},
        get_secrets=lambda: {"access_key_id": "AKIA_TEST_ONLY", "secret_access_key": "SUPER_SECRET_NEVER_EXPOSE"},
    )
    client = Mock()
    with override_settings(ENVIRONMENT="production", PRIVATE_MEDIA_STORAGE_MODE="s3"), patch("apps.media.services.active_provider", return_value=fake_config), patch("apps.media.services._s3_client", return_value=client):
        asset = create_private_studio_image(upload=upload(), owner=owner)

    assert asset.provider == MediaAsset.Provider.AMAZON_S3
    assert asset.access == MediaAsset.Access.PRIVATE
    assert asset.uploaded_by == owner
    assert asset.provider_asset_id.startswith(f"studio-private/{owner.pk}/")
    assert "private-fabinzi-bucket" not in asset.provider_asset_id
    assert "AKIA_TEST_ONLY" not in str(asset.metadata)
    assert "SUPER_SECRET_NEVER_EXPOSE" not in str(asset.metadata)
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "private-fabinzi-bucket"
    assert kwargs["Key"] == asset.provider_asset_id
    assert kwargs["CacheControl"] == "private, no-store"
    assert "ACL" not in kwargs
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs


def test_production_storage_mode_cannot_fall_back_to_local():
    with override_settings(ENVIRONMENT="production", PRIVATE_MEDIA_STORAGE_MODE="local"):
        with pytest.raises(ProductionStorageUnavailable, match="not permitted"):
            private_media_storage_mode()


@pytest.mark.django_db
def test_production_s3_unavailable_fails_closed():
    with override_settings(ENVIRONMENT="production", PRIVATE_MEDIA_STORAGE_MODE="s3"), patch(
        "apps.media.services.active_provider",
        side_effect=ProductionStorageUnavailable("amazon_s3 is not configured and enabled"),
    ):
        with pytest.raises(ProductionStorageUnavailable, match="amazon_s3"):
            assert_production_file_storage()


@pytest.mark.django_db
def test_production_private_preview_uses_short_lived_authorized_signed_access_and_never_secret_key(client):
    owner = User.objects.create_user(username="signed-owner", password="password12345")
    other = User.objects.create_user(username="signed-other", password="password12345")
    asset = MediaAsset.objects.create(
        provider=MediaAsset.Provider.AMAZON_S3,
        provider_asset_id=f"studio-private/{owner.pk}/file.png",
        original_filename="file.png",
        mime_type="image/png",
        size_bytes=100,
        access=MediaAsset.Access.PRIVATE,
        uploaded_by=owner,
        metadata={"studio_private_upload": True},
    )
    fake_config = SimpleNamespace(
        config={"bucket": "private-fabinzi-bucket"},
        get_secrets=lambda: {"access_key_id": "AKIA_TEST_ONLY", "secret_access_key": "SUPER_SECRET_NEVER_EXPOSE"},
    )
    s3 = Mock()
    s3.generate_presigned_url.return_value = "https://storage.example/private/file.png?X-Amz-Credential=AKIA_TEST_ONLY&X-Amz-Signature=abc123"

    with override_settings(ENVIRONMENT="production", PRIVATE_MEDIA_STORAGE_MODE="s3"), patch("apps.media.services.active_provider", return_value=fake_config), patch("apps.media.services._s3_client", return_value=s3):
        signed = private_media_response(asset)
    assert signed.startswith("https://storage.example/private/")
    assert "SUPER_SECRET_NEVER_EXPOSE" not in signed
    s3.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "private-fabinzi-bucket", "Key": asset.provider_asset_id},
        ExpiresIn=300,
    )

    protected = reverse("private-studio-media", args=[asset.pk])
    client.force_login(other)
    assert client.get(protected).status_code == 404

    client.force_login(owner)
    with patch("apps.media.views.private_media_response", return_value=signed):
        response = client.get(protected)
    assert response.status_code == 302
    assert response["Location"] == signed
    assert "SUPER_SECRET_NEVER_EXPOSE" not in response["Location"]
    assert "no-store" in response["Cache-Control"]
    assert "noindex" in response["X-Robots-Tag"]
