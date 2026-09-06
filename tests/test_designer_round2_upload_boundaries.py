from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.artwork.models import ArtworkAsset
from apps.artwork.services import create_artwork
from apps.design.models import DesignAsset
from apps.design.services import create_design
from apps.media.models import MediaAsset
from apps.organizations.models import Membership

from .conftest import VALID_PNG
from .test_designer_round2_upload_reproduction import _active_designer, _post_upload


User = get_user_model()


@pytest.mark.django_db
def test_round2_design_no_file_is_rejected_before_storage(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-design-no-file", password="password123")
    organization = _active_designer(owner, "Round2 Design No File")
    design = create_design(organization=organization, actor=owner, title="No file")
    version = design.versions.get()
    client.force_login(owner)

    with patch("apps.organizations.designer_views.create_private_designer_asset") as create_media:
        response = _post_upload(
            client,
            "designer-design-detail",
            design.pk,
            organization,
            version.pk,
            DesignAsset.Kind.PATTERN,
            None,
            "No file",
        )

    assert response.status_code == 302
    create_media.assert_not_called()
    assert MediaAsset.objects.count() == 0


@pytest.mark.django_db
def test_round2_design_empty_file_creates_no_media(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-design-empty", password="password123")
    organization = _active_designer(owner, "Round2 Design Empty")
    design = create_design(organization=organization, actor=owner, title="Empty file")
    version = design.versions.get()
    client.force_login(owner)

    response = _post_upload(
        client,
        "designer-design-detail",
        design.pk,
        organization,
        version.pk,
        DesignAsset.Kind.TECHNICAL,
        SimpleUploadedFile("empty.txt", b"", content_type="text/plain"),
        "Empty",
    )

    assert response.status_code == 302
    assert MediaAsset.objects.count() == 0
    assert DesignAsset.objects.count() == 0


@pytest.mark.django_db
def test_round2_design_oversize_file_creates_no_media_without_large_fixture(client, settings, tmp_path):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    settings.MEDIA_ROOT = tmp_path
    owner = User.objects.create_user(username="round2-design-large", password="password123")
    organization = _active_designer(owner, "Round2 Design Large")
    design = create_design(organization=organization, actor=owner, title="Large file")
    version = design.versions.get()
    client.force_login(owner)

    oversized = SimpleUploadedFile("large.dxf", b"0\nEOF\n", content_type="application/dxf")
    assert oversized.size > 4
    with patch("apps.media.designer_services.DESIGNER_PRIVATE_FILE_MAX_BYTES", 4):
        response = _post_upload(
            client,
            "designer-design-detail",
            design.pk,
            organization,
            version.pk,
            DesignAsset.Kind.PATTERN,
            oversized,
            "Large",
        )

    assert response.status_code == 302
    html = client.get(response["Location"]).content.decode("utf-8")
    assert "larger than the 50 MB Designer workspace limit" in html
    assert MediaAsset.objects.count() == 0
    assert DesignAsset.objects.count() == 0
    assert not any(path.is_file() for path in tmp_path.rglob("*"))
    assert not default_storage.exists("designer-private")


@pytest.mark.django_db
def test_round2_design_product_image_mime_is_rejected_before_storage(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-design-image-mime", password="password123")
    organization = _active_designer(owner, "Round2 Design Image MIME")
    design = create_design(organization=organization, actor=owner, title="Image MIME")
    version = design.versions.get()
    client.force_login(owner)

    with patch("apps.organizations.designer_views.create_private_designer_asset") as create_media:
        response = _post_upload(
            client,
            "designer-design-detail",
            design.pk,
            organization,
            version.pk,
            DesignAsset.Kind.PRODUCT_IMAGE,
            SimpleUploadedFile("not-image.pdf", b"%PDF-1.4", content_type="application/pdf"),
            "Not image",
        )

    assert response.status_code == 302
    create_media.assert_not_called()
    assert MediaAsset.objects.count() == 0


@pytest.mark.django_db
def test_round2_design_wrong_role_cannot_store_asset(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-design-role-owner", password="password123")
    accountant = User.objects.create_user(username="round2-design-accountant", password="password123")
    organization = _active_designer(owner, "Round2 Design Role")
    Membership.objects.create(
        organization=organization,
        user=accountant,
        role=Membership.Role.ACCOUNTANT,
    )
    design = create_design(organization=organization, actor=owner, title="Role boundary")
    version = design.versions.get()
    client.force_login(accountant)

    response = _post_upload(
        client,
        "designer-design-detail",
        design.pk,
        organization,
        version.pk,
        DesignAsset.Kind.PATTERN,
        SimpleUploadedFile("role.dxf", b"0\nEOF\n", content_type="application/dxf"),
        "Role",
    )

    assert response.status_code == 302
    assert MediaAsset.objects.count() == 0
    assert DesignAsset.objects.count() == 0


@pytest.mark.django_db
def test_round2_design_cross_tenant_resource_fails_closed_before_storage(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    actor = User.objects.create_user(username="round2-design-tenant-a", password="password123")
    foreign_owner = User.objects.create_user(username="round2-design-tenant-b", password="password123")
    actor_org = _active_designer(actor, "Round2 Design Tenant A")
    foreign_org = _active_designer(foreign_owner, "Round2 Design Tenant B")
    design = create_design(organization=foreign_org, actor=foreign_owner, title="Foreign design")
    version = design.versions.get()
    client.force_login(actor)

    response = _post_upload(
        client,
        "designer-design-detail",
        design.pk,
        actor_org,
        version.pk,
        DesignAsset.Kind.PATTERN,
        SimpleUploadedFile("foreign.dxf", b"0\nEOF\n", content_type="application/dxf"),
        "Foreign",
    )

    assert response.status_code == 404
    assert MediaAsset.objects.count() == 0
    assert DesignAsset.objects.count() == 0


@pytest.mark.django_db
def test_round2_artwork_cross_tenant_resource_fails_closed_before_storage(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    actor = User.objects.create_user(username="round2-art-tenant-a", password="password123")
    foreign_owner = User.objects.create_user(username="round2-art-tenant-b", password="password123")
    actor_org = _active_designer(actor, "Round2 Artwork Tenant A")
    foreign_org = _active_designer(foreign_owner, "Round2 Artwork Tenant B")
    artwork = create_artwork(organization=foreign_org, actor=foreign_owner, title="Foreign artwork")
    version = artwork.versions.get()
    client.force_login(actor)

    response = _post_upload(
        client,
        "designer-artwork-detail",
        artwork.pk,
        actor_org,
        version.pk,
        ArtworkAsset.Kind.PREVIEW,
        SimpleUploadedFile("foreign.png", VALID_PNG, content_type="image/png"),
        "Foreign",
    )

    assert response.status_code == 404
    assert MediaAsset.objects.count() == 0
    assert ArtworkAsset.objects.count() == 0
