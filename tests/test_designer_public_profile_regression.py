import pytest

from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization


@pytest.mark.django_db
def test_designer_public_profile_renders_legacy_instagram_handle_without_500(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="designer-public-profile-regression",
        password="strong-pass-123",
    )
    organization = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="FABINZI Demo Studio",
        email="designer-public-profile@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=user,
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Membership.Role.OWNER,
        is_active=True,
    )
    DesignerProfile.objects.create(
        organization=organization,
        studio_name="FABINZI Demo Studio",
        portfolio_url="https://example.com/fabinzi-demo-designer/portfolio",
        social_links={"instagram": "@fabinzi_demo"},
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(
        organization=organization,
        status=OnboardingApplication.Status.APPROVED,
    )

    client.force_login(user)
    response = client.get(f"/designer/public-profile/?org={organization.pk}")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Designer public profile" in body
    assert "https://www.instagram.com/fabinzi_demo/" in body
