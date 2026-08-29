import pytest
from django.urls import reverse

from apps.finance.models import PayoutProfile
from apps.operations.models import ProductionJob

from .test_manufacturer_portal_acceptance import assigned_job, invited_rfq, manufacturer


@pytest.mark.django_db
def test_arabic_portal_localizes_real_organization_and_production_states(client):
    owner, org, _, _ = manufacturer("presentation-ar")
    data = assigned_job(org, prefix="presentation-ar-job")
    data["job"].status = ProductionJob.Status.READY
    data["job"].save(update_fields=["status"])
    client.force_login(owner)

    dashboard = client.get(reverse("manufacturer") + f"?org={org.pk}&lang=ar")
    assert dashboard.status_code == 200
    text = dashboard.content.decode()
    assert "نشط" in text

    production = client.get(
        reverse("manufacturer-production-detail", args=[data["job"].pk])
        + f"?org={org.pk}&lang=ar"
    )
    assert production.status_code == 200
    text = production.content.decode()
    assert "جاهز للتنفيذ" in text
    assert "Ready for fulfillment" not in text


@pytest.mark.django_db
def test_verified_payout_profile_is_read_only_in_manufacturer_portal(client):
    owner, org, _, _ = manufacturer("presentation-finance")
    profile = PayoutProfile.objects.create(
        organization=org,
        method=PayoutProfile.Method.BANK,
        account_holder="Factory presentation-finance",
        destination_hint="•••• 7788",
        status=PayoutProfile.Status.VERIFIED,
    )
    client.force_login(owner)

    response = client.get(reverse("manufacturer-finance") + f"?org={org.pk}&lang=en")
    assert response.status_code == 200
    text = response.content.decode()
    assert profile.account_holder in text
    assert "Verified payout details are read-only here" in text
    assert 'value="save_payout"' not in text
    assert 'value="submit_payout"' not in text

    arabic = client.get(reverse("manufacturer-finance") + f"?org={org.pk}&lang=ar")
    assert arabic.status_code == 200
    text = arabic.content.decode()
    assert "موثّق" in text
    assert "Verified" not in text


@pytest.mark.django_db
def test_new_quote_form_does_not_imply_unpersisted_moq_or_fee_values(client):
    owner, org, _, _ = manufacturer("presentation-rfq")
    _, _, _, _, invitation = invited_rfq(org, prefix="presentation-rfq-design")
    client.force_login(owner)

    response = client.get(
        reverse("manufacturer-rfq-detail", args=[invitation.pk])
        + f"?org={org.pk}&lang=en"
    )
    assert response.status_code == 200
    text = response.content.decode()
    assert 'name="minimum_order_quantity" value=""' in text
    assert 'name="setup_fee" value=""' in text
    assert 'name="sample_fee" value=""' in text
    assert 'name="shipping_estimate" value=""' in text
