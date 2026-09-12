import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.public_profiles.models import ManufacturerCapabilityVerification

from .test_manufacturer_portal_acceptance import manufacturer

User = get_user_model()


def _staff(name, *, change=False):
    user = User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password123",
        is_staff=True,
    )
    codenames = [
        "view_manufacturercapabilityverification",
        "view_manufacturerpublicproductapproval",
    ]
    if change:
        codenames.append("change_manufacturercapabilityverification")
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return user


def _subscription_staff(name, codename=None):
    user = User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password123",
        is_staff=True,
    )
    if codename:
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="subscriptions",
                codename=codename,
            )
        )
    return user


@pytest.mark.django_db
def test_subscription_navigation_matches_route_authorization_without_permission_broadening(client):
    index_url = reverse("fabinzi_admin:index")
    subscriptions_url = reverse("fabinzi_admin:maneg-v2-9-subscriptions")

    operator = _subscription_staff("round2-nav-operator", "manage_professional_subscription")
    assert operator.has_perm("subscriptions.manage_professional_subscription")
    assert not operator.has_perm("subscriptions.view_organizationsubscription")
    assert not operator.has_perm("subscriptions.view_subscriptionplanpolicy")
    assert not operator.has_perm("subscriptions.view_subscriptionbillingconfirmation")
    client.force_login(operator)
    entry = client.get(index_url)
    assert entry.status_code == 200
    assert f'href="{subscriptions_url}"'.encode() in entry.content
    queue = client.get(subscriptions_url)
    assert queue.status_code == 200
    assert b'Manufacturer Pro upgrade requests' in queue.content
    assert f'href="{subscriptions_url}" aria-current="page"'.encode() in queue.content

    read_only = _subscription_staff(
        "round2-nav-billing-viewer",
        "view_subscriptionbillingconfirmation",
    )
    client.force_login(read_only)
    read_entry = client.get(index_url)
    assert read_entry.status_code == 200
    assert f'href="{subscriptions_url}"'.encode() in read_entry.content
    assert client.get(subscriptions_url).status_code == 200
    assert client.post(subscriptions_url, {"action": "cancel_manufacturer_upgrade"}).status_code == 403

    unrelated = _subscription_staff("round2-nav-unrelated")
    client.force_login(unrelated)
    unrelated_entry = client.get(index_url)
    assert unrelated_entry.status_code == 200
    assert f'href="{subscriptions_url}"'.encode() not in unrelated_entry.content
    assert client.get(subscriptions_url).status_code == 403


@pytest.mark.django_db
def test_maneg_capability_verify_and_record_specific_revoke_are_permissioned_and_audited(client):
    _owner, organization, _profile, _application = manufacturer("round2-ops-capability")
    listing = ManufacturerListing.objects.create(organization=organization)
    capability = ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.PRINT,
        name="Digital production print",
        is_active=True,
    )
    route = reverse("fabinzi_admin:maneg-v2-5-manufacturer-public-controls")

    viewer = _staff("round2-capability-viewer", change=False)
    client.force_login(viewer)
    page = client.get(route)
    assert page.status_code == 200
    denied = client.post(
        route,
        {
            "action": "verify_capability",
            "capability_id": capability.pk,
            "canonical_code": ManufacturerCapabilityVerification.CanonicalCode.DTF,
        },
        follow=True,
    )
    assert denied.status_code == 200
    assert not ManufacturerCapabilityVerification.objects.filter(capability=capability).exists()

    operator = _staff("round2-capability-operator", change=True)
    client.force_login(operator)
    verified = client.post(
        route,
        {
            "action": "verify_capability",
            "capability_id": capability.pk,
            "canonical_code": ManufacturerCapabilityVerification.CanonicalCode.DTF,
            "notes": "Round 2 explicit DTF verification",
        },
        follow=True,
    )
    assert verified.status_code == 200
    row = ManufacturerCapabilityVerification.objects.get(
        capability=capability,
        canonical_code=ManufacturerCapabilityVerification.CanonicalCode.DTF,
    )
    assert row.status == ManufacturerCapabilityVerification.Status.VERIFIED
    assert row.capability_id == capability.pk
    assert AuditEvent.objects.filter(
        action="public_profile.manufacturer_capability.verified",
        object_id=str(row.pk),
    ).exists()

    # Multiple explicit canonical meanings remain supported for one operational capability.
    second = client.post(
        route,
        {
            "action": "verify_capability",
            "capability_id": capability.pk,
            "canonical_code": ManufacturerCapabilityVerification.CanonicalCode.DTG,
        },
    )
    assert second.status_code == 302
    assert ManufacturerCapabilityVerification.objects.filter(
        capability=capability,
        status=ManufacturerCapabilityVerification.Status.VERIFIED,
    ).count() == 2

    revoke = client.post(
        route,
        {
            "action": "revoke_capability",
            "verification_id": row.pk,
            "notes": "Round 2 record-specific revoke",
        },
        follow=True,
    )
    assert revoke.status_code == 200
    row.refresh_from_db()
    assert row.status == ManufacturerCapabilityVerification.Status.REVOKED
    assert row.revoked_at is not None
    assert AuditEvent.objects.filter(
        action="public_profile.manufacturer_capability.revoked",
        object_id=str(row.pk),
    ).exists()
    assert ManufacturerCapabilityVerification.objects.get(
        capability=capability,
        canonical_code=ManufacturerCapabilityVerification.CanonicalCode.DTG,
    ).status == ManufacturerCapabilityVerification.Status.VERIFIED
