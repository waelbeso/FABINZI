from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.artwork.models import ArtworkAsset
from apps.artwork.services import create_artwork
from apps.design.models import DesignAsset
from apps.design.services import create_design
from apps.media.models import MediaAsset
from apps.media.services import ProductionStorageUnavailable
from apps.organizations.models import (
    DesignerProfile,
    Membership,
    OnboardingApplication,
    Organization,
)

from .conftest import VALID_PNG


User = get_user_model()


def _active_designer(owner, name):
    organization = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(
        organization=organization,
        user=owner,
        role=Membership.Role.OWNER,
    )
    DesignerProfile.objects.create(
        organization=organization,
        studio_name=name,
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(
        organization=organization,
        status=OnboardingApplication.Status.APPROVED,
    )
    return organization


def _post_upload(client, route_name, object_id, organization, version_id, kind, upload, label):
    return client.post(
        f"{reverse(route_name, args=[object_id])}?org={organization.pk}",
        data={
            "action": "upload_asset",
            "version_id": str(version_id),
            "kind": kind,
            "label": label,
            "file": upload,
        },
        follow=False,
    )


@pytest.mark.django_db
def test_round2_design_dxf_actual_http_upload_succeeds_in_local_test_storage(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-design-owner", password="password123")
    organization = _active_designer(owner, "Round2 Design Studio")
    design = create_design(
        organization=organization,
        actor=owner,
        title="Round 2 DXF reproduction",
    )
    version = design.versions.get()
    client.force_login(owner)

    dxf_payload = b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n"
    response = _post_upload(
        client,
        "designer-design-detail",
        design.pk,
        organization,
        version.pk,
        DesignAsset.Kind.PATTERN,
        SimpleUploadedFile(
            "round2-pattern.dxf",
            dxf_payload,
            content_type="application/dxf",
        ),
        "Round 2 DXF",
    )

    assert response.status_code == 302
    asset = DesignAsset.objects.select_related("media_asset").get(
        version=version,
        kind=DesignAsset.Kind.PATTERN,
    )
    media = asset.media_asset
    assert asset.label == "Round 2 DXF"
    assert media.access == MediaAsset.Access.PRIVATE
    assert media.provider == MediaAsset.Provider.LOCAL_DEV
    assert media.original_filename == "round2-pattern.dxf"
    assert media.mime_type == "application/dxf"
    assert media.metadata["designer_private_upload"] is True
    assert media.metadata["organization_id"] == organization.pk
    assert media.metadata["purpose"] == "design_pattern"
    assert default_storage.exists(media.provider_asset_id)
    assert MediaAsset.objects.count() == 1
    assert DesignAsset.objects.filter(media_asset=media).count() == 1


@pytest.mark.django_db
def test_round2_artwork_actual_http_uploads_succeed_in_local_test_storage(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-artwork-owner", password="password123")
    organization = _active_designer(owner, "Round2 Artwork Studio")
    artwork = create_artwork(
        organization=organization,
        actor=owner,
        title="Round 2 Artwork reproduction",
    )
    version = artwork.versions.get()
    client.force_login(owner)

    cases = (
        (
            ArtworkAsset.Kind.PREVIEW,
            "round2-preview.png",
            VALID_PNG,
            "image/png",
            "Preview",
        ),
        (
            ArtworkAsset.Kind.SOURCE,
            "round2-source.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>',
            "image/svg+xml",
            "Production Source",
        ),
        (
            ArtworkAsset.Kind.RIGHTS_EVIDENCE,
            "round2-rights.pdf",
            b"%PDF-1.4\n% Round 2 rights evidence\n",
            "application/pdf",
            "Rights Evidence",
        ),
    )

    for kind, filename, payload, mime_type, label in cases:
        response = _post_upload(
            client,
            "designer-artwork-detail",
            artwork.pk,
            organization,
            version.pk,
            kind,
            SimpleUploadedFile(filename, payload, content_type=mime_type),
            label,
        )
        assert response.status_code == 302

    rows = list(
        ArtworkAsset.objects.filter(version=version)
        .select_related("media_asset")
        .order_by("id")
    )
    assert [row.kind for row in rows] == [case[0] for case in cases]
    assert all(row.media_asset.access == MediaAsset.Access.PRIVATE for row in rows)
    assert all(row.media_asset.provider == MediaAsset.Provider.LOCAL_DEV for row in rows)
    assert all(
        row.media_asset.metadata["organization_id"] == organization.pk
        for row in rows
    )
    assert all(default_storage.exists(row.media_asset.provider_asset_id) for row in rows)
    assert not MediaAsset.objects.filter(
        metadata__artwork_public_derivative=True
    ).exists()
    assert MediaAsset.objects.count() == 3
    assert ArtworkAsset.objects.filter(version=version).count() == 3


@pytest.mark.django_db
def test_round2_design_storage_unavailable_currently_escapes_as_http_500(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-design-failure", password="password123")
    organization = _active_designer(owner, "Round2 Design Failure")
    design = create_design(
        organization=organization,
        actor=owner,
        title="Round 2 storage failure",
    )
    version = design.versions.get()
    client.force_login(owner)
    client.raise_request_exception = False

    with patch(
        "apps.organizations.designer_views.create_private_designer_asset",
        side_effect=ProductionStorageUnavailable("synthetic reproduction only"),
    ):
        response = _post_upload(
            client,
            "designer-design-detail",
            design.pk,
            organization,
            version.pk,
            DesignAsset.Kind.PATTERN,
            SimpleUploadedFile(
                "round2-pattern.dxf",
                b"0\nSECTION\n0\nEOF\n",
                content_type="application/dxf",
            ),
            "Storage failure reproduction",
        )

    assert response.status_code == 500
    assert MediaAsset.objects.count() == 0
    assert DesignAsset.objects.count() == 0


@pytest.mark.django_db
def test_round2_artwork_storage_unavailable_currently_escapes_as_http_500(client, settings):
    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="round2-artwork-failure", password="password123")
    organization = _active_designer(owner, "Round2 Artwork Failure")
    artwork = create_artwork(
        organization=organization,
        actor=owner,
        title="Round 2 Artwork storage failure",
    )
    version = artwork.versions.get()
    client.force_login(owner)
    client.raise_request_exception = False

    with patch(
        "apps.organizations.designer_views.create_private_designer_asset",
        side_effect=ProductionStorageUnavailable("synthetic reproduction only"),
    ):
        response = _post_upload(
            client,
            "designer-artwork-detail",
            artwork.pk,
            organization,
            version.pk,
            ArtworkAsset.Kind.PREVIEW,
            SimpleUploadedFile(
                "round2-preview.png",
                VALID_PNG,
                content_type="image/png",
            ),
            "Storage failure reproduction",
        )

    assert response.status_code == 500
    assert MediaAsset.objects.count() == 0
    assert ArtworkAsset.objects.count() == 0
