"""Round 1 application boundaries; all public provider calls are mocked."""
import hashlib
import io
import json
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from PIL import Image

from apps.integrations.models import IntegrationConfig
from apps.media import manufacturer_public_services as images
from apps.media.models import MediaAsset
from apps.finance.models import PayoutProfile
from apps.organizations.models import Membership, PublicProfileRevision
from apps.organizations.public_profile_services import current_public_profile_data, save_public_profile_revision
from .test_manufacturer_portal_acceptance import manufacturer

pytestmark = pytest.mark.django_db


def image_file(name="profile.png", fmt="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (24, 16), "purple").save(stream, fmt)
    return SimpleUploadedFile(name, stream.getvalue(), content_type="application/octet-stream")


@pytest.fixture
def provider(monkeypatch):
    integration, _ = IntegrationConfig.objects.update_or_create(provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES, defaults={"enabled": True, "config": {"account_id": "a" * 32}})
    monkeypatch.setattr(IntegrationConfig, "get_secrets", lambda self: {"api_token": "synthetic-provider-token"})
    post = Mock(return_value=Mock(ok=True, json=lambda: {"success": True, "result": {"id": "opaque-image-id", "requireSignedURLs": False, "variants": ["https://imagedelivery.net/test-account/opaque-image-id/public"]}}))
    delete = Mock(return_value=Mock(ok=True, json=lambda: {"success": True}))
    monkeypatch.setattr(images.requests, "post", post)
    monkeypatch.setattr(images.requests, "delete", delete)
    return post, delete


def test_upload_contract_and_metadata(provider):
    actor, org, _, _ = manufacturer()
    upload = image_file()
    payload = upload.read(); upload.seek(0)
    asset = images.create_manufacturer_public_image(upload=upload, organization=org, actor=actor, purpose="profile")
    post, delete = provider
    args, kwargs = post.call_args
    assert args == (f"https://api.cloudflare.com/client/v4/accounts/{'a' * 32}/images/v1",)
    assert kwargs["data"]["requireSignedURLs"] == "false"
    assert kwargs["data"]["creator"] == str(actor.pk)
    assert json.loads(kwargs["data"]["metadata"])["organization_id"] == org.pk
    assert kwargs["files"]["file"] == ("profile.png", payload, "image/png")
    assert kwargs["timeout"] == (5, 30) and kwargs["allow_redirects"] is False
    assert asset.provider_asset_id == "opaque-image-id"
    assert asset.provider == MediaAsset.Provider.CLOUDFLARE_IMAGES
    assert asset.access == MediaAsset.Access.PUBLIC
    assert asset.checksum_sha256 == hashlib.sha256(payload).hexdigest()
    assert asset.metadata["width"] == 24 and asset.metadata["height"] == 16
    assert asset.metadata["public_url"].startswith("https://imagedelivery.net/")
    delete.assert_not_called()
    assert not PublicProfileRevision.objects.exists()


@pytest.mark.parametrize("data", [b"", b"<svg></svg>", b"not an image", b"x" * (images.MAX_BYTES + 1)])
def test_invalid_bytes_never_reach_provider(provider, data):
    actor, org, _, _ = manufacturer()
    with pytest.raises(ValidationError):
        images.create_manufacturer_public_image(upload=SimpleUploadedFile("fake.png", data, content_type="image/png"), organization=org, actor=actor, purpose="profile")
    provider[0].assert_not_called()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_real_supported_formats(fmt):
    assert images.validate_public_image(image_file(fmt=fmt))[1] == images.FORMATS[fmt][0]


def test_provider_disabled_fails_closed(provider):
    actor, org, _, _ = manufacturer()
    IntegrationConfig.objects.filter(provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES).update(enabled=False)
    with pytest.raises(ValidationError, match="unavailable"):
        images.create_manufacturer_public_image(upload=image_file(), organization=org, actor=actor, purpose="cover")
    provider[0].assert_not_called()


def test_database_failure_compensates(provider, monkeypatch, caplog):
    actor, org, _, _ = manufacturer()
    monkeypatch.setattr(MediaAsset.objects, "create", Mock(side_effect=DatabaseError("synthetic database failure")))
    with pytest.raises(ValidationError, match="unavailable"):
        images.create_manufacturer_public_image(upload=image_file(), organization=org, actor=actor, purpose="cover")
    assert provider[1].call_args.args[0].endswith("/opaque-image-id")
    assert not MediaAsset.objects.exists()
    assert "synthetic-provider-token" not in caplog.text


@pytest.mark.parametrize("url", ["http://imagedelivery.net/a/b/public", "https://evil.test/a/b/public", "https://imagedelivery.net@evil.test/a/b/public", "https://imagedelivery.net/a/b/public?token=private"])
def test_unsafe_provider_delivery_compensates(provider, url):
    actor, org, _, _ = manufacturer()
    provider[0].return_value.json = lambda: {"success": True, "result": {"id": "opaque-image-id", "requireSignedURLs": False, "variants": [url]}}
    with pytest.raises(ValidationError):
        images.create_manufacturer_public_image(upload=image_file(), organization=org, actor=actor, purpose="profile")
    provider[1].assert_called_once()
    assert not MediaAsset.objects.exists()


def test_tenant_validation_authoritative_and_legacy_compatible():
    actor, org, _, _ = manufacturer("one")
    other, foreign, _, _ = manufacturer("two")
    asset = MediaAsset.objects.create(provider="local_dev", provider_asset_id="legacy", original_filename="legacy.png", mime_type="image/png", size_bytes=1, access="public", uploaded_by=actor)
    payload = current_public_profile_data(org)
    payload["public_state"]["profile_image_id"] = asset.pk
    revision = save_public_profile_revision(organization=org, actor=actor, proposed_data=payload)
    assert revision.proposed_data["public_state"]["profile_image_id"] == asset.pk
    for metadata, access, uploader in [({"organization_id": foreign.pk}, "public", actor), ({}, "private", actor), ({}, "public", other), ({"manufacturer_public_upload": True}, "public", actor)]:
        asset.metadata, asset.access, asset.uploaded_by = metadata, access, uploader
        asset.save()
        with pytest.raises(ValidationError):
            save_public_profile_revision(organization=org, actor=actor, proposed_data=payload)


def test_profile_readonly_edit_cancel_and_notifications(client):
    actor, org, _, _ = manufacturer()
    client.force_login(actor)
    url = f"/manufacturer/profile/?org={org.pk}"
    response = client.get(url)
    assert response.status_code == 200
    assert b'name="display_name"' not in response.content
    assert b'Edit profile' in response.content
    response = client.get(url + "&edit=1")
    assert b'name="display_name"' in response.content
    assert b'name="legal_name"' not in response.content
    assert b'name="tax_number"' not in response.content
    response = client.get(f"/manufacturer/notifications/?org={org.pk}")
    assert response.status_code == 200
    assert b'mfr-nav' in response.content
    assert response.content.count(b'aria-current="page"') == 1
    assert "no-store" in response["Cache-Control"]


def test_bank_roundtrip_blank_retention_verified_lock(client):
    actor, org, _, _ = manufacturer()
    client.force_login(actor)
    url = f"/manufacturer/finance/?org={org.pk}"
    iban = "EG380019000500000000263180002"
    data = {"action": "save_payout", "method": "bank", "account_holder": "Synthetic Holder", "iban": iban, "bank_name": "Synthetic Bank", "country": "EG", "payout_currency": "EGP"}
    response = client.post(url, data, follow=True)
    assert response.status_code == 200
    profile = PayoutProfile.objects.get(organization=org)
    assert profile.iban_last4 == iban[-4:]
    encrypted = profile.iban_encrypted
    assert iban.encode() not in response.content
    assert b'name="destination_hint"' not in response.content
    data["iban"] = ""
    client.post(url, data)
    profile.refresh_from_db()
    assert profile.iban_encrypted == encrypted
    profile.status = PayoutProfile.Status.VERIFIED; profile.save()
    response = client.get(url)
    assert b'name="iban"' not in response.content
    client.post(url, {**data, "account_holder": "Attack"})
    profile.refresh_from_db()
    assert profile.account_holder == "Synthetic Holder"


@pytest.mark.parametrize("role", [Membership.Role.MANAGER, Membership.Role.ACCOUNTANT])
def test_finance_view_does_not_authorize_mutation(client, role):
    actor, org, _, _ = manufacturer(role=role)
    client.force_login(actor)
    url = f"/manufacturer/finance/?org={org.pk}"
    response = client.get(url)
    assert response.status_code == 200
    assert b'name="iban"' not in response.content
    response = client.post(url, {"action": "save_payout", "method": "manual", "account_holder": "Attack", "destination_hint": "ref"})
    assert response.status_code == 302
    assert not PayoutProfile.objects.filter(organization=org).exists()


def test_upload_enters_draft_only_and_html_hides_provider(client, provider):
    actor, org, _, _ = manufacturer()
    client.force_login(actor)
    url = f"/manufacturer/public-profile/?org={org.pk}"
    response = client.post(url, {"action": "save_revision", "country": "EG", "public_name_en": "Factory", "profile_image_upload": image_file()}, follow=True)
    assert response.status_code == 200
    asset = MediaAsset.objects.get(provider_asset_id="opaque-image-id")
    revision = PublicProfileRevision.objects.get(organization=org)
    assert revision.proposed_data["public_state"]["profile_image_id"] == asset.pk
    assert revision.status == PublicProfileRevision.Status.DRAFT
    org.public_state.refresh_from_db()
    assert org.public_state.profile_image_id is None
    for private in ("opaque-image-id", "imagedelivery.net", "synthetic-provider-token"):
        assert private.encode() not in response.content


def test_provider_timeout_is_safe_and_not_retried(provider, caplog):
    actor, org, _, _ = manufacturer()
    provider[0].side_effect = images.requests.Timeout("synthetic-provider-token")
    with pytest.raises(ValidationError) as caught:
        images.create_manufacturer_public_image(upload=image_file(), organization=org, actor=actor, purpose="profile")
    provider[0].assert_called_once()
    provider[1].assert_not_called()
    assert "synthetic-provider-token" not in str(caught.value) + caplog.text
    assert not MediaAsset.objects.exists()


def test_locked_revision_and_invalid_fields_precede_upload(client, provider):
    actor, org, _, _ = manufacturer()
    client.force_login(actor)
    url = f"/manufacturer/public-profile/?org={org.pk}"
    client.post(url, {"action": "save_revision", "country": "EG", "website": "not a URL", "profile_image_upload": image_file()})
    provider[0].assert_not_called()
    revision = save_public_profile_revision(organization=org, actor=actor, proposed_data=current_public_profile_data(org))
    revision.status = PublicProfileRevision.Status.SUBMITTED; revision.save()
    client.post(url, {"action": "save_revision", "country": "EG", "profile_image_upload": image_file()})
    provider[0].assert_not_called()


@pytest.mark.parametrize("path,section", [("", "overview"), ("profile/", "profile"), ("team/", "team"), ("capabilities/", "capabilities"), ("opportunities/", "opportunities"), ("quotes/", "quotes"), ("production/", "production"), ("finance/", "finance"), ("notifications/", "notifications"), ("public-profile/", "public-profile"), ("public-products/", "public-products"), ("public-inquiries/", "public-inquiries")])
def test_sidebar_one_active_primary(client, path, section):
    actor, org, _, _ = manufacturer()
    client.force_login(actor)
    response = client.get(f"/manufacturer/{path}?org={org.pk}")
    assert response.status_code == 200
    assert response.context["manufacturer_active_section"] == section
    assert response.content.count(b'aria-current="page"') == 1
