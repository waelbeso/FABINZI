import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import OnboardingApplication, Organization
from apps.organizations.services import submit_application
from apps.subscriptions.models import OnboardingPlanSelection
from .v2_3_support import v2_3_reference_rows


@pytest.mark.django_db
def test_legacy_designer_post_without_plan_defaults_to_starter_on_submission(client, v2_3_reference_rows):
    owner = User.objects.create_user(
        username="pr33-legacy-default-plan",
        email="pr33-legacy-default-plan@example.test",
        password="StrongPass123!",
    )
    client.force_login(owner)
    response = client.post(
        reverse("designer"),
        {
            "org-display_name": "PR33 Legacy Starter Studio",
            "org-legal_name": "",
            "org-email": "pr33-legacy-studio@example.test",
            "org-phone": "",
            "org-website": "",
            "org-address_line1": "",
            "org-address_line2": "",
            "org-city": "Cairo",
            "org-region": "Cairo",
            "org-country": "EG",
            "profile-studio_name": "PR33 Legacy Starter Studio",
            "profile-portfolio_url": "",
            "profile-legal_registration_number": "",
            "profile-tax_number": "",
            "profile-payout_information": "",
            "profile-accept_terms": "on",
            # Intentionally omit profile-plan_policy_id: this is the legacy/default path.
        },
    )
    assert response.status_code == 302

    organization = Organization.objects.get(
        created_by=owner,
        kind=Organization.Kind.DESIGNER,
        display_name="PR33 Legacy Starter Studio",
    )
    application = organization.onboarding_application
    assert application.status == OnboardingApplication.Status.DRAFT
    assert not OnboardingPlanSelection.objects.filter(application=application).exists()

    submit_application(application=application, actor=owner)
    application.refresh_from_db()
    selection = OnboardingPlanSelection.objects.get(application=application)
    assert application.status == OnboardingApplication.Status.SUBMITTED
    assert selection.plan_code == "designer_starter"
    assert selection.price_snapshot["monthly_price"] == "0.00"
    assert selection.payment_due_at is None
