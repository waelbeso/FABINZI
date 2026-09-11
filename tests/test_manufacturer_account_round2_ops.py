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
