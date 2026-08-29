import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.notifications.models import Notification
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.organizations.services import create_designer_onboarding, create_manufacturer_onboarding, review_application, submit_application, user_has_org_access


@pytest.mark.django_db
def test_designer_onboarding_creates_owner_and_audit():
    user = User.objects.create_user(username="designer", password="StrongPass123!")
    app = create_designer_onboarding(user=user, organization_data={"display_name": "Studio One", "email": "studio@example.com"}, profile_data={"studio_name": "Studio One", "terms_accepted": True})
    assert app.organization.kind == Organization.Kind.DESIGNER
    assert Membership.objects.filter(organization=app.organization, user=user, role=Membership.Role.OWNER).exists()
    assert user_has_org_access(user, app.organization)
    assert AuditEvent.objects.filter(action="onboarding.designer.created").exists()


@pytest.mark.django_db
def test_manufacturer_requires_registration_before_submission():
    user = User.objects.create_user(username="factory", password="StrongPass123!")
    app = create_manufacturer_onboarding(user=user, organization_data={"display_name": "Factory", "email": "factory@example.com"}, profile_data={"terms_accepted": True, "commercial_registration": ""})
    with pytest.raises(ValidationError):
        submit_application(application=app, actor=user)


@pytest.mark.django_db
def test_submit_review_approve_updates_org_and_notifies():
    owner = User.objects.create_user(username="owner", password="StrongPass123!")
    staff = User.objects.create_user(username="staff", password="StrongPass123!", is_staff=True)
    app = create_manufacturer_onboarding(user=owner, organization_data={"display_name": "Factory", "email": "factory@example.com"}, profile_data={"terms_accepted": True, "commercial_registration": "CR-1"})
    submit_application(application=app, actor=owner)
    app.refresh_from_db()
    assert app.status == OnboardingApplication.Status.SUBMITTED
    app.organization.refresh_from_db()
    assert app.organization.verification_status == Organization.VerificationStatus.PENDING
    review_application(application=app, reviewer=staff, decision=OnboardingApplication.Status.APPROVED, notes="Verified")
    app.refresh_from_db(); app.organization.refresh_from_db()
    assert app.status == OnboardingApplication.Status.APPROVED
    assert app.organization.verification_status == Organization.VerificationStatus.ACTIVE
    assert Notification.objects.filter(recipient=owner, type="business_onboarding_review").exists()
    assert AuditEvent.objects.filter(action="onboarding.approved").exists()


@pytest.mark.django_db
def test_non_staff_cannot_review():
    owner = User.objects.create_user(username="owner2", password="StrongPass123!")
    app = create_designer_onboarding(user=owner, organization_data={"display_name": "D", "email": "d@example.com"}, profile_data={"terms_accepted": True})
    submit_application(application=app, actor=owner)
    with pytest.raises(PermissionDenied):
        review_application(application=app, reviewer=owner, decision=OnboardingApplication.Status.APPROVED)


@pytest.mark.django_db
def test_tenant_isolation():
    one = User.objects.create_user(username="one", password="StrongPass123!")
    two = User.objects.create_user(username="two", password="StrongPass123!")
    app = create_designer_onboarding(user=one, organization_data={"display_name": "Private Studio", "email": "p@example.com"}, profile_data={"terms_accepted": True})
    assert user_has_org_access(one, app.organization)
    assert not user_has_org_access(two, app.organization)


@pytest.mark.django_db
def test_portal_creates_designer_draft(client):
    user = User.objects.create_user(username="webdesigner", password="StrongPass123!")
    client.force_login(user)
    response = client.post(reverse("designer"), {"org-display_name": "Web Studio", "org-legal_name": "", "org-email": "web@example.com", "org-phone": "", "org-website": "", "org-address_line1": "", "org-address_line2": "", "org-city": "Cairo", "org-region": "Cairo", "org-country": "EG", "profile-studio_name": "Web Studio", "profile-portfolio_url": "", "profile-legal_registration_number": "", "profile-tax_number": "", "profile-payout_information": "", "profile-accept_terms": "on"})
    assert response.status_code == 302
    assert Organization.objects.filter(display_name="Web Studio", kind=Organization.Kind.DESIGNER).exists()


@pytest.mark.django_db
def test_api_is_authenticated(client):
    response = client.get("/api/v1/onboarding/designer/")
    assert response.status_code in (401, 403)
