import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkReview, ArtworkVersion, IPCase, IPCaseEvidence, IPDeclaration
from apps.artwork.public import public_artwork_queryset
from apps.artwork.services import (
    add_artwork_asset,
    add_ip_case_evidence,
    create_artwork,
    create_ip_case,
    moderate_ip_case,
    review_artwork_version,
    set_ip_declaration,
    submit_artwork_version,
)
from apps.audit.models import AuditEvent
from apps.media.designer_services import create_private_designer_asset, require_private_designer_asset
from apps.media.models import MediaAsset
from apps.organizations.designer_context import resolve_designer_membership
from apps.organizations.designer_services import (
    attach_designer_verification_document,
    secure_add_or_update_member,
    secure_deactivate_member,
    update_active_designer_profile,
)
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization, VerificationDocument

from .conftest import VALID_PNG

User = get_user_model()


def designer_org(user, name="Studio", *, status=Organization.VerificationStatus.ACTIVE, role=Membership.Role.OWNER, app_status=OnboardingApplication.Status.APPROVED):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@example.test",
        verification_status=status,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=role)
    DesignerProfile.objects.create(organization=org, studio_name=name, terms_accepted=True)
    OnboardingApplication.objects.create(organization=org, status=app_status)
    return org


def private_upload(name="asset.png", content=VALID_PNG, mime="image/png"):
    return SimpleUploadedFile(name, content, content_type=mime)


def complete_private_artwork(owner, org, *, title="Private Wave"):
    artwork = create_artwork(organization=org, actor=owner, title=title, tags=["wave"])
    version = artwork.versions.get()
    preview = create_private_designer_asset(upload=private_upload("preview.png"), owner=owner, organization=org, purpose="artwork_preview")
    source = create_private_designer_asset(upload=private_upload("source.png"), owner=owner, organization=org, purpose="artwork_source")
    rights = create_private_designer_asset(upload=private_upload("rights.png"), owner=owner, organization=org, purpose="artwork_rights_evidence")
    add_artwork_asset(version=version, actor=owner, media_asset=preview, kind=ArtworkAsset.Kind.PREVIEW)
    add_artwork_asset(version=version, actor=owner, media_asset=source, kind=ArtworkAsset.Kind.SOURCE)
    add_artwork_asset(version=version, actor=owner, media_asset=rights, kind=ArtworkAsset.Kind.RIGHTS_EVIDENCE)
    set_ip_declaration(
        version=version,
        actor=owner,
        rights_basis=IPDeclaration.RightsBasis.ORIGINAL,
        rights_holder_name=org.display_name,
        accepts_ip_policy=True,
    )
    return artwork, version, preview, source, rights


@pytest.mark.django_db
@pytest.mark.parametrize(
    "app_status,org_status",
    [
        (OnboardingApplication.Status.DRAFT, Organization.VerificationStatus.DRAFT),
        (OnboardingApplication.Status.REVISION_REQUIRED, Organization.VerificationStatus.DRAFT),
        (OnboardingApplication.Status.SUBMITTED, Organization.VerificationStatus.PENDING),
        (OnboardingApplication.Status.APPROVED, Organization.VerificationStatus.ACTIVE),
        (OnboardingApplication.Status.REJECTED, Organization.VerificationStatus.REJECTED),
        (OnboardingApplication.Status.APPROVED, Organization.VerificationStatus.SUSPENDED),
    ],
)
def test_designer_onboarding_states_render_without_crossing_access(client, app_status, org_status):
    user = User.objects.create_user(username=f"state-{app_status}-{org_status}", password="password123")
    designer_org(user, f"State {app_status} {org_status}", status=org_status, app_status=app_status)
    client.force_login(user)
    response = client.get(reverse("designer"))
    assert response.status_code == 200
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    if org_status == Organization.VerificationStatus.ACTIVE:
        assert b"Designer workspace" in response.content or "مساحة المصمم" in response.content.decode("utf-8")
    else:
        assert b"Garment Designs" not in response.content or app_status == OnboardingApplication.Status.REVISION_REQUIRED


@pytest.mark.django_db
def test_no_designer_org_gets_onboarding_not_another_tenant(client):
    user = User.objects.create_user(username="no-designer", password="password123")
    other = User.objects.create_user(username="other-owner", password="password123")
    designer_org(other, "Other Tenant")
    client.force_login(user)
    response = client.get(reverse("designer"))
    assert response.status_code == 200
    assert b"Other Tenant" not in response.content


@pytest.mark.django_db
def test_tenant_switch_and_invalid_org_id_remain_owned(client):
    user = User.objects.create_user(username="multi", password="password123")
    one = designer_org(user, "Studio One")
    two = designer_org(user, "Studio Two")
    stranger = User.objects.create_user(username="stranger", password="password123")
    foreign = designer_org(stranger, "Foreign Studio")
    client.force_login(user)
    response = client.get(f"{reverse('designer')}?org={two.pk}")
    assert response.status_code == 200 and b"Studio Two" in response.content
    assert client.session["designer_organization_id"] == two.pk
    response = client.get(f"{reverse('designer')}?org={foreign.pk}")
    assert response.status_code == 200
    assert b"Foreign Studio" not in response.content
    assert client.session["designer_organization_id"] in {one.pk, two.pk}


@pytest.mark.django_db
def test_manager_cannot_grant_or_remove_owner_and_last_owner_is_protected():
    owner = User.objects.create_user(username="rbac-owner", password="password123")
    manager = User.objects.create_user(username="rbac-manager", password="password123")
    candidate = User.objects.create_user(username="rbac-candidate", password="password123")
    org = designer_org(owner, "RBAC Studio")
    Membership.objects.create(organization=org, user=manager, role=Membership.Role.MANAGER)
    with pytest.raises(PermissionDenied):
        secure_add_or_update_member(organization=org, actor=manager, user=candidate, role=Membership.Role.OWNER)
    owner_membership = Membership.objects.get(organization=org, user=owner)
    with pytest.raises(PermissionDenied):
        secure_deactivate_member(membership=owner_membership, actor=manager)
    with pytest.raises(ValidationError):
        secure_add_or_update_member(organization=org, actor=owner, user=owner, role=Membership.Role.MANAGER)
    with pytest.raises(ValidationError):
        secure_deactivate_member(membership=owner_membership, actor=owner)


@pytest.mark.django_db
def test_team_api_matches_web_rbac(client):
    owner = User.objects.create_user(username="api-owner", password="password123")
    manager = User.objects.create_user(username="api-manager", password="password123")
    target = User.objects.create_user(username="api-target", password="password123")
    org = designer_org(owner, "API Studio")
    Membership.objects.create(organization=org, user=manager, role=Membership.Role.MANAGER)
    client.force_login(manager)
    response = client.post(
        f"/api/v1/businesses/{org.pk}/members/",
        data=json.dumps({"user_id": target.pk, "role": Membership.Role.OWNER}),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert not Membership.objects.filter(organization=org, user=target).exists()


@pytest.mark.django_db
def test_active_profile_mutation_is_allowlisted_and_audited():
    owner = User.objects.create_user(username="profile-owner", password="password123")
    org = designer_org(owner, "Profile Studio")
    profile = org.designer_profile
    profile.legal_registration_number = "LEGAL-KEEP"
    profile.tax_number = "TAX-KEEP"
    profile.payout_information = "PRIVATE-KEEP"
    profile.save()
    update_active_designer_profile(
        organization=org,
        actor=owner,
        organization_data={"display_name": "Profile Studio Updated", "legal_name": "SHOULD-NOT-CHANGE"},
        profile_data={"studio_name": "Updated Studio", "tax_number": "NO", "payout_information": "NO"},
    )
    org.refresh_from_db(); profile.refresh_from_db()
    assert org.display_name == "Profile Studio Updated"
    assert org.legal_name == ""
    assert profile.studio_name == "Updated Studio"
    assert profile.tax_number == "TAX-KEEP"
    assert profile.payout_information == "PRIVATE-KEEP"
    assert AuditEvent.objects.filter(action="designer.profile.updated", metadata__organization_id=org.pk).exists()


@pytest.mark.django_db
def test_private_designer_upload_service_rejects_foreign_organization(settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="media-owner", password="password123")
    foreign_owner = User.objects.create_user(username="media-foreign", password="password123")
    designer_org(owner, "Owned Media")
    foreign = designer_org(foreign_owner, "Foreign Media")
    with pytest.raises(PermissionDenied):
        create_private_designer_asset(upload=private_upload(), owner=owner, organization=foreign, purpose="technical")


@pytest.mark.django_db
def test_designer_private_media_route_is_tenant_isolated_and_noindex(client, settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="route-owner", password="password123")
    other = User.objects.create_user(username="route-other", password="password123")
    org = designer_org(owner, "Route Studio")
    designer_org(other, "Other Route Studio")
    asset = create_private_designer_asset(upload=private_upload(), owner=owner, organization=org, purpose="technical")
    client.force_login(other)
    assert client.get(reverse("private-designer-media", args=[asset.pk])).status_code == 404
    client.force_login(owner)
    response = client.get(reverse("private-designer-media", args=[asset.pk]))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert asset.provider_asset_id.encode() not in getattr(response, "content", b"")


@pytest.mark.django_db
def test_verification_document_requires_same_designer_tenant_and_rejects_studio_media(settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="verify-owner", password="password123")
    foreign_owner = User.objects.create_user(username="verify-foreign", password="password123")
    org = designer_org(owner, "Verify Studio", status=Organization.VerificationStatus.DRAFT, app_status=OnboardingApplication.Status.DRAFT)
    foreign = designer_org(foreign_owner, "Verify Foreign", status=Organization.VerificationStatus.DRAFT, app_status=OnboardingApplication.Status.DRAFT)
    application = org.onboarding_application
    own_asset = create_private_designer_asset(upload=private_upload("verify.pdf", b"pdf", "application/pdf"), owner=owner, organization=org, purpose="verification")
    foreign_asset = create_private_designer_asset(upload=private_upload("foreign.pdf", b"pdf", "application/pdf"), owner=foreign_owner, organization=foreign, purpose="verification")
    doc = attach_designer_verification_document(application=application, actor=owner, media_asset=own_asset, document_type=VerificationDocument.DocumentType.REGISTRATION)
    assert doc.application_id == application.pk
    with pytest.raises(PermissionDenied):
        attach_designer_verification_document(application=application, actor=owner, media_asset=foreign_asset, document_type=VerificationDocument.DocumentType.TAX)
    studio_asset = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="studio-private/guess.png", original_filename="guess.png", mime_type="image/png", size_bytes=10, access=MediaAsset.Access.PRIVATE, uploaded_by=owner, metadata={"studio_private_upload": True})
    with pytest.raises(ValidationError):
        attach_designer_verification_document(application=application, actor=owner, media_asset=studio_asset, document_type=VerificationDocument.DocumentType.OTHER)


@pytest.mark.django_db
def test_verification_document_api_numeric_id_cannot_cross_tenant(client, settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="verify-api-owner", password="password123")
    foreign_owner = User.objects.create_user(username="verify-api-foreign", password="password123")
    org = designer_org(owner, "Verify API", status=Organization.VerificationStatus.DRAFT, app_status=OnboardingApplication.Status.DRAFT)
    foreign = designer_org(foreign_owner, "Verify API Foreign", status=Organization.VerificationStatus.DRAFT, app_status=OnboardingApplication.Status.DRAFT)
    foreign_asset = create_private_designer_asset(upload=private_upload("foreign.pdf", b"pdf", "application/pdf"), owner=foreign_owner, organization=foreign, purpose="verification")
    client.force_login(owner)
    response = client.post(
        f"/api/v1/onboarding/{org.onboarding_application.pk}/documents/",
        data=json.dumps({"media_asset_id": foreign_asset.pk, "document_type": VerificationDocument.DocumentType.REGISTRATION}),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert not VerificationDocument.objects.filter(application=org.onboarding_application).exists()


@pytest.mark.django_db
def test_artwork_preview_lifecycle_private_to_public_and_takedown(client, settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="art-life-owner", password="password123")
    staff = User.objects.create_user(username="art-life-staff", password="password123", is_staff=True)
    org = designer_org(owner, "Lifecycle Studio")
    artwork, version, preview, source, rights = complete_private_artwork(owner, org)
    assert preview.access == MediaAsset.Access.PRIVATE
    assert source.access == MediaAsset.Access.PRIVATE
    assert rights.access == MediaAsset.Access.PRIVATE
    assert not public_artwork_queryset().filter(pk=artwork.pk).exists()
    submit_artwork_version(version=version, actor=owner)
    preview.refresh_from_db(); source.refresh_from_db(); rights.refresh_from_db()
    assert preview.access == source.access == rights.access == MediaAsset.Access.PRIVATE
    review_artwork_version(version=version, reviewer=staff, decision=ArtworkReview.Decision.APPROVED, notes="Approved")
    preview.refresh_from_db(); source.refresh_from_db(); rights.refresh_from_db(); artwork.refresh_from_db(); version.refresh_from_db()
    assert preview.access == MediaAsset.Access.PRIVATE
    assert source.access == MediaAsset.Access.PRIVATE
    assert rights.access == MediaAsset.Access.PRIVATE
    derivative_row = version.assets.filter(kind=ArtworkAsset.Kind.PREVIEW, media_asset__metadata__artwork_public_derivative=True).select_related("media_asset").get()
    derivative = derivative_row.media_asset
    assert derivative.access == MediaAsset.Access.PUBLIC
    assert derivative.provider_asset_id == preview.provider_asset_id
    assert derivative.pk != preview.pk
    assert public_artwork_queryset().filter(pk=artwork.pk).exists()
    response = client.get((derivative.metadata or {})["public_url"])
    assert response.status_code == 200
    case = create_ip_case(actor=owner, artwork=artwork, reporter_name="Claimant", reporter_email="claim@example.test", claimant_rights="Documented claim", allegation="Claim")
    moderate_ip_case(case=case, reviewer=staff, status=IPCase.Status.RESOLVED, resolution=IPCase.Resolution.TAKEDOWN, notes="Takedown")
    derivative.refresh_from_db(); artwork.refresh_from_db()
    assert artwork.status == Artwork.Status.SUSPENDED
    assert derivative.access == MediaAsset.Access.PRIVATE
    assert not public_artwork_queryset().filter(pk=artwork.pk).exists()
    assert client.get(f"/artwork/media/{derivative.pk}/").status_code == 404


@pytest.mark.django_db
def test_artwork_source_rights_and_ip_evidence_never_public(settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="private-ip-owner", password="password123")
    staff = User.objects.create_user(username="private-ip-staff", password="password123", is_staff=True)
    org = designer_org(owner, "Private IP Studio")
    artwork, version, preview, source, rights = complete_private_artwork(owner, org)
    submit_artwork_version(version=version, actor=owner)
    review_artwork_version(version=version, reviewer=staff, decision=ArtworkReview.Decision.APPROVED)
    case = create_ip_case(actor=owner, artwork=artwork, reporter_name="C", reporter_email="c@example.test", claimant_rights="rights", allegation="claim")
    evidence = create_private_designer_asset(upload=private_upload("evidence.pdf", b"evidence", "application/pdf"), owner=owner, organization=org, purpose="ip_case_evidence")
    add_ip_case_evidence(case=case, actor=owner, media_asset=evidence)
    for asset in (source, rights, evidence):
        asset.refresh_from_db()
        assert asset.access == MediaAsset.Access.PRIVATE
        assert not (asset.metadata or {}).get("public_url")


@pytest.mark.django_db
def test_ip_evidence_rejects_another_designer_organization(settings):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="ip-owner-a", password="password123")
    other = User.objects.create_user(username="ip-owner-b", password="password123")
    org = designer_org(owner, "IP A")
    foreign = designer_org(other, "IP B")
    artwork = Artwork.objects.create(organization=org, title="A", created_by=owner)
    case = create_ip_case(actor=owner, artwork=artwork, reporter_name="C", reporter_email="c@example.test", claimant_rights="r", allegation="a")
    foreign_asset = create_private_designer_asset(upload=private_upload("foreign.pdf", b"x", "application/pdf"), owner=other, organization=foreign, purpose="ip_case_evidence")
    with pytest.raises(PermissionDenied):
        add_ip_case_evidence(case=case, actor=owner, media_asset=foreign_asset)
    assert not IPCaseEvidence.objects.filter(case=case).exists()


@pytest.mark.django_db
def test_all_designer_routes_are_noindex_and_absent_from_sitemap(client):
    owner = User.objects.create_user(username="seo-owner", password="password123")
    org = designer_org(owner, "SEO Studio")
    client.force_login(owner)
    urls = [
        reverse("designer"), reverse("designer-profile"), reverse("designer-team"),
        reverse("designer-design-list"), reverse("designer-artworks"), reverse("designer-products"),
        reverse("designer-rfqs"), reverse("designer-store"), reverse("designer-fulfillment"), reverse("designer-finance"),
    ]
    for url in urls:
        response = client.get(f"{url}?org={org.pk}")
        assert response.status_code == 200
        assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
        assert b'<meta name="robots" content="noindex,nofollow,noarchive">' in response.content
    sitemap = client.get(reverse("sitemap-xml")).content.decode("utf-8")
    assert "/designer/" not in sitemap
    assert "/media/designer-private/" not in sitemap


@pytest.mark.django_db
def test_public_artwork_api_never_contains_designer_private_urls(settings, client):
    settings.ENVIRONMENT = "test"; settings.PRIVATE_MEDIA_STORAGE_MODE = "local"
    owner = User.objects.create_user(username="api-art-owner", password="password123")
    staff = User.objects.create_user(username="api-art-staff", password="password123", is_staff=True)
    org = designer_org(owner, "API Artwork")
    artwork, version, preview, source, rights = complete_private_artwork(owner, org)
    submit_artwork_version(version=version, actor=owner)
    review_artwork_version(version=version, reviewer=staff, decision=ArtworkReview.Decision.APPROVED)
    response = client.get("/api/v1/artworks/public/")
    assert response.status_code == 200
    payload = response.content.decode("utf-8")
    assert "designer-private" not in payload
    assert source.provider_asset_id not in payload
    assert rights.provider_asset_id not in payload
    assert f"/artwork/media/" in payload
