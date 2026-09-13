import io
from copy import deepcopy

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.media.designer_public_services import designer_public_image_eligible
from apps.media.models import MediaAsset
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization, PublicProfileRevision
from apps.organizations.public_profile_services import normalize_public_profile_data
from apps.public_profiles.services import ensure_public_state
from apps.subscriptions.designer_upgrade_services import create_designer_upgrade_request, review_designer_upgrade_request
from apps.subscriptions.models import DesignerSubscriptionUpgradeRequest, OrganizationSubscription, SubscriptionBillingConfirmation, SubscriptionPeriod
from apps.subscriptions.services import ensure_subscription_for_organization, entitlement_summary
from .v2_3_support import v2_3_reference_rows

User = get_user_model()
pytestmark = pytest.mark.usefixtures("v2_3_reference_rows")


def _user(name, *, superuser=False):
    return User.objects.create_user(username=name, email=f"{name}@example.test", password="password12345", is_staff=superuser, is_superuser=superuser)


def _designer(owner, name="Phase 4 Studio", role=Membership.Role.OWNER):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        email=f"{owner.username}@phase4.test",
        phone="01000000000",
        website="https://example.test",
        city="Cairo",
        region="Cairo Governorate",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=role, is_active=True)
    DesignerProfile.objects.create(
        organization=org,
        studio_name=f"{name} Studio",
        portfolio_url="https://example.test/portfolio",
        social_links={"linkedin": "https://www.linkedin.com/in/example/"},
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(organization=org, status=OnboardingApplication.Status.APPROVED)
    ensure_subscription_for_organization(org)
    ensure_public_state(org)
    return org


def _url(path, org):
    return f"{path}?org={org.pk}"


def _public_form(org, **overrides):
    profile = org.designer_profile
    data = {
        "action": "save_revision",
        "public_name_en": org.display_name,
        "public_name_ar": "",
        "bio_en": "Phase 4 public biography",
        "bio_ar": "",
        "specializations": "casualwear, menswear",
        "profile_image_id": "",
        "cover_image_id": "",
        "city": org.city,
        "region": org.region,
        "country": org.country,
        "studio_name": profile.studio_name,
        "website": org.website,
        "portfolio_url": profile.portfolio_url,
        "social_instagram": "",
        "social_behance": "",
        "social_linkedin": profile.social_links.get("linkedin", ""),
    }
    data.update(overrides)
    return data


def _image(name="phase4.png"):
    data = io.BytesIO()
    Image.new("RGB", (8, 8), (80, 90, 100)).save(data, format="PNG")
    return SimpleUploadedFile(name, data.getvalue(), content_type="image/png")


def _fake_public_creator(*, upload, organization, actor, purpose, request=None):
    payload = upload.read()
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=f"phase4-{organization.pk}-{purpose}-{MediaAsset.objects.count()}",
        original_filename=upload.name,
        mime_type=upload.content_type or "image/png",
        size_bytes=len(payload),
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=actor,
        metadata={"organization_id": organization.pk, "purpose": purpose, "designer_public_upload": True, "public_url": f"https://imagedelivery.net/test/{organization.pk}/{purpose}"},
    )


@pytest.mark.django_db
def test_team_missing_identity_controlled_existing_identity_no_separate_designer_subscription(client):
    owner = _user("phase4-team-owner")
    org = _designer(owner)
    client.force_login(owner)
    missing = client.post(_url("/designer/team/", org), {"action": "upsert", "email": "missing@example.test", "role": Membership.Role.DESIGNER})
    assert missing.status_code == 200
    assert b"team-member-error" in missing.content
    assert b"No FABINZI account exists" in missing.content

    invitee = _user("phase4-team-existing")
    assert not OrganizationSubscription.objects.filter(organization__memberships__user=invitee).exists()
    added = client.post(_url("/designer/team/", org), {"action": "upsert", "email": invitee.email, "role": Membership.Role.DESIGNER})
    assert added.status_code == 302
    membership = Membership.objects.get(organization=org, user=invitee)
    assert membership.is_active and membership.role == Membership.Role.DESIGNER
    duplicate = client.post(_url("/designer/team/", org), {"action": "upsert", "email": invitee.email, "role": Membership.Role.DESIGNER})
    assert duplicate.status_code == 302
    assert Membership.objects.filter(organization=org, user=invitee).count() == 1


@pytest.mark.django_db
def test_team_seat_unauthorized_and_tenant_boundaries(client):
    owner = _user("phase4-seat-owner")
    org = _designer(owner, "Phase 4 Seat Studio")
    first = _user("phase4-seat-first")
    second = _user("phase4-seat-second")
    client.force_login(owner)
    assert client.post(_url("/designer/team/", org), {"action": "upsert", "email": first.email, "role": Membership.Role.DESIGNER}).status_code == 302
    seat_denial = client.post(_url("/designer/team/", org), {"action": "upsert", "email": second.email, "role": Membership.Role.DESIGNER})
    assert seat_denial.status_code == 200
    assert not Membership.objects.filter(organization=org, user=second).exists()

    client.force_login(first)
    assert client.post(_url("/designer/team/", org), {"action": "upsert", "email": second.email, "role": Membership.Role.DESIGNER}).status_code == 403

    other_owner = _user("phase4-other-owner")
    other = _designer(other_owner, "Phase 4 Other Studio")
    other_member = Membership.objects.create(organization=other, user=_user("phase4-other-member"), role=Membership.Role.DESIGNER, is_active=True)
    client.force_login(owner)
    assert client.post(_url("/designer/team/", org), {"action": "deactivate", "membership_id": other_member.pk}).status_code == 404
    other_member.refresh_from_db()
    assert other_member.is_active


@pytest.mark.django_db
def test_organization_profile_readonly_edit_cancel_and_save_returns_closed(client):
    owner = _user("phase4-profile-owner")
    org = _designer(owner, "Phase 4 Profile Studio")
    client.force_login(owner)
    initial = client.get(_url("/designer/profile/", org))
    assert initial.status_code == 200 and b"designer-profile-readonly" in initial.content
    assert b"designer-profile-form" not in initial.content and b"profile-edit-action" in initial.content

    editing = client.get(_url("/designer/profile/", org) + "&edit=1")
    assert b"designer-profile-form" in editing.content and b"autofocus" in editing.content
    assert b"profile-cancel-action" in editing.content
    before = org.display_name
    client.get(_url("/designer/profile/", org))
    org.refresh_from_db()
    assert org.display_name == before

    saved = client.post(
        _url("/designer/profile/", org),
        {
            "display_name": "Phase 4 Proposed Name",
            "studio_name": "Proposed Atelier",
            "email": org.email,
            "phone": org.phone,
            "website": org.website,
            "address_line1": "1 Test Street",
            "address_line2": "",
            "city": "New Cairo",
            "region": org.region,
            "country": org.country,
            "portfolio_url": org.designer_profile.portfolio_url,
            "instagram": "",
            "behance": "",
            "linkedin": "https://www.linkedin.com/in/example/",
        },
    )
    assert saved.status_code == 302
    org.refresh_from_db()
    assert org.display_name == before
    assert org.address_line1 == "1 Test Street"
    revision = PublicProfileRevision.objects.get(organization=org)
    assert revision.status == PublicProfileRevision.Status.SUBMITTED
    assert revision.proposed_data["organization"]["display_name"] == "Phase 4 Proposed Name"
    assert revision.proposed_data["organization"]["city"] == "New Cairo"
    assert revision.proposed_data["profile"]["studio_name"] == "Proposed Atelier"
    after = client.get(_url("/designer/profile/", org))
    assert b"designer-profile-readonly" in after.content and b"designer-profile-form" not in after.content


@pytest.mark.django_db
def test_public_profile_closed_default_upload_validation_ownership_and_no_auto_publish(client, monkeypatch):
    owner = _user("phase4-public-owner")
    org = _designer(owner, "Phase 4 Public Studio")
    state = ensure_public_state(org)
    visibility_before = state.visibility
    client.force_login(owner)

    initial = client.get(_url("/designer/public-profile/", org))
    assert b"designer-public-profile-readonly" in initial.content and b"designer-public-profile-form" not in initial.content
    assert b"REVISION STATE" in initial.content and b"public-profile-edit-action" in initial.content
    editing = client.get(_url("/designer/public-profile/", org) + "&edit=1")
    assert b"profile_image_upload" in editing.content and b"cover_image_upload" in editing.content

    invalid = _public_form(org, public_name_en="Keep This Value")
    invalid["profile_image_upload"] = SimpleUploadedFile("bad.txt", b"not-an-image", content_type="text/plain")
    response = client.post(_url("/designer/public-profile/", org) + "&edit=1", invalid)
    assert response.status_code == 200 and b"public-profile-error" in response.content and b"Keep This Value" in response.content
    assert not PublicProfileRevision.objects.filter(organization=org).exists()

    oversized = _public_form(org, public_name_en="Keep Oversize Value")
    oversized["cover_image_upload"] = SimpleUploadedFile("huge.png", b"x" * (10 * 1024 * 1024 + 1), content_type="image/png")
    response = client.post(_url("/designer/public-profile/", org) + "&edit=1", oversized)
    assert response.status_code == 200 and b"Keep Oversize Value" in response.content
    assert not PublicProfileRevision.objects.filter(organization=org).exists()

    other_owner = _user("phase4-media-other-owner")
    other = _designer(other_owner, "Phase 4 Other Public Studio")
    foreign = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="foreign", original_filename="foreign.png", mime_type="image/png", size_bytes=10, access=MediaAsset.Access.PUBLIC, uploaded_by=other_owner, metadata={"organization_id": other.pk, "designer_public_upload": True})
    private = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="private", original_filename="private.png", mime_type="image/png", size_bytes=10, access=MediaAsset.Access.PRIVATE, uploaded_by=owner, metadata={"private_url": "https://private.example.test/secret-token"})
    for asset in (foreign, private):
        response = client.post(_url("/designer/public-profile/", org) + "&edit=1", _public_form(org, profile_image_id=str(asset.pk)))
        assert response.status_code == 200 and b"public-profile-error" in response.content
        assert b"secret-token" not in response.content
        assert not PublicProfileRevision.objects.filter(organization=org).exists()

    monkeypatch.setattr("apps.public_profiles.portal_views.create_designer_public_image", _fake_public_creator)
    valid = _public_form(org, public_name_en="Uploaded Draft Name")
    valid["profile_image_upload"] = _image("profile.png")
    valid["cover_image_upload"] = _image("cover.png")
    response = client.post(_url("/designer/public-profile/", org) + "&edit=1", valid)
    assert response.status_code == 302
    revision = PublicProfileRevision.objects.get(organization=org)
    assert revision.status == PublicProfileRevision.Status.DRAFT
    ids = [revision.proposed_data["public_state"]["profile_image_id"], revision.proposed_data["public_state"]["cover_image_id"]]
    assert all(ids) and ids[0] != ids[1]
    for asset in MediaAsset.objects.filter(pk__in=ids):
        assert str(asset.metadata["organization_id"]) == str(org.pk)
        assert designer_public_image_eligible(asset, org)
    state.refresh_from_db()
    assert state.visibility == visibility_before and state.profile_image_id is None and state.cover_image_id is None

    normalized = normalize_public_profile_data(
        organization=org,
        proposed_data={
            "organization": {"display_name": org.display_name, "website": org.website, "city": org.city, "region": org.region, "country": org.country},
            "public_state": {"public_name_en": org.display_name, "profile_image_id": ids[0], "cover_image_id": ids[1]},
            "profile": {"studio_name": org.designer_profile.studio_name, "portfolio_url": org.designer_profile.portfolio_url, "social_links": {}},
        },
    )
    assert normalized["public_state"]["profile_image_id"] == ids[0]


@pytest.mark.django_db
def test_public_profile_submit_keeps_approved_current_separate_from_pending(client):
    owner = _user("phase4-submit-owner")
    org = _designer(owner, "Phase 4 Submit Studio")
    state = ensure_public_state(org)
    state.public_name_en = "Approved Current Name"
    state.save(update_fields=["public_name_en", "updated_at"])
    client.force_login(owner)
    response = client.post(_url("/designer/public-profile/", org) + "&edit=1", _public_form(org, action="submit_revision", public_name_en="Pending Proposed Name"))
    assert response.status_code == 302
    revision = PublicProfileRevision.objects.get(organization=org)
    assert revision.status == PublicProfileRevision.Status.SUBMITTED
    state.refresh_from_db()
    assert state.public_name_en == "Approved Current Name"
    page = client.get(_url("/designer/public-profile/", org))
    assert b"Approved Current Name" in page.content and b"Pending Proposed Name" in page.content
    assert b"designer-public-profile-form" not in page.content


def _paid_state(org):
    sub = OrganizationSubscription.objects.get(organization=org)
    summary = entitlement_summary(org)
    return {
        "subscription": (sub.current_plan_id, sub.status, sub.started_at, sub.current_period_start, sub.current_period_end, sub.next_billing_at, deepcopy(sub.policy_snapshot), deepcopy(sub.price_snapshot)),
        "periods": list(SubscriptionPeriod.objects.filter(subscription=sub).order_by("pk").values()),
        "billing": list(SubscriptionBillingConfirmation.objects.filter(organization=org).order_by("pk").values()),
        "seats": list(Membership.objects.filter(organization=org, is_active=True).order_by("pk").values_list("pk", "user_id", "role")),
        "entitlement": (summary["plan_code"], summary["design_limit"], summary["artwork_limit"], summary["team_limit"], summary["team_used"]),
    }


@pytest.mark.django_db
def test_designer_upgrade_request_owner_idempotent_and_request_approve_reject_never_mutate_paid_state():
    owner = _user("phase4-upgrade-owner")
    org = _designer(owner, "Phase 4 Upgrade Studio")
    member = _user("phase4-upgrade-member")
    Membership.objects.create(organization=org, user=member, role=Membership.Role.DESIGNER, is_active=True)
    operator = _user("phase4-upgrade-operator", superuser=True)
    before = _paid_state(org)

    with pytest.raises(PermissionDenied):
        create_designer_upgrade_request(organization=org, actor=member)
    first, created = create_designer_upgrade_request(organization=org, actor=owner)
    assert created and first.plan_code == "designer_pro" and first.policy_snapshot and first.price_snapshot
    second, created = create_designer_upgrade_request(organization=org, actor=owner)
    assert not created and second.pk == first.pk
    assert DesignerSubscriptionUpgradeRequest.objects.filter(organization=org, status="pending").count() == 1
    assert _paid_state(org) == before

    review_designer_upgrade_request(upgrade_request=first, actor=operator, decision=DesignerSubscriptionUpgradeRequest.Status.APPROVED)
    first.refresh_from_db()
    assert first.status == DesignerSubscriptionUpgradeRequest.Status.APPROVED and first.reviewed_by == operator
    assert _paid_state(org) == before

    rejected, created = create_designer_upgrade_request(organization=org, actor=owner)
    assert created and _paid_state(org) == before
    with pytest.raises(ValidationError):
        review_designer_upgrade_request(upgrade_request=rejected, actor=operator, decision=DesignerSubscriptionUpgradeRequest.Status.REJECTED, rejection_reason="")
    assert _paid_state(org) == before
    review_designer_upgrade_request(upgrade_request=rejected, actor=operator, decision=DesignerSubscriptionUpgradeRequest.Status.REJECTED, rejection_reason="Commercial review declined the request.")
    assert _paid_state(org) == before


@pytest.mark.django_db
def test_subscription_page_real_usage_owner_request_and_non_owner_denial(client):
    owner = _user("phase4-sub-owner")
    org = _designer(owner, "Phase 4 Subscription Studio")
    member = _user("phase4-sub-member")
    Membership.objects.create(organization=org, user=member, role=Membership.Role.DESIGNER, is_active=True)
    before = _paid_state(org)
    client.force_login(owner)
    page = client.get(_url("/designer/subscription/", org))
    assert page.status_code == 200 and b"designer-current-plan" in page.content and b"designer-usage" in page.content
    assert b"designer-upgrade-request-form" in page.content
    assert client.post(_url("/designer/subscription/", org), {"action": "request_upgrade"}).status_code == 302
    assert _paid_state(org) == before
    page = client.get(_url("/designer/subscription/", org))
    assert b"Pending" in page.content and b"designer-upgrade-pending-note" in page.content and b"designer-upgrade-request-form" not in page.content

    client.force_login(member)
    denied = client.post(_url("/designer/subscription/", org), {"action": "request_upgrade"})
    assert denied.status_code == 200
    assert DesignerSubscriptionUpgradeRequest.objects.filter(organization=org).count() == 1
    assert _paid_state(org) == before
