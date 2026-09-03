from pathlib import Path

import pytest
from django.urls import resolve, reverse

from apps.manufacturer_marketplace.models import RFQ
from .v2_7_helpers import user


def test_v2_7_urls_keep_existing_manufacturer_media_route_and_add_minimum_maneg_route():
    assert resolve("/manufacturer/production/1/media/spec/2/").url_name == "manufacturer-production-media"
    match = resolve("/Maneg/production-routing/")
    assert match.url_name == "maneg-v2-7-routing"


def test_customer_api_v1_route_namespace_is_not_replaced_by_v2_7():
    match = resolve("/api/v1/payment-options/")
    assert match.app_name == "v1"
    assert match.namespace == "v1"


def test_operational_production_template_uses_frozen_spec_manifest_not_live_artwork_traversal():
    root = Path(__file__).resolve().parents[1]
    text = (root / "templates/manufacturer/production_detail.html").read_text()
    assert "snapshot.authorized_private_media" in text
    assert "manufacturer-production-media' job.id 'spec'" in text
    assert "element.artwork_version.assets" not in text


def test_v2_7_dedicated_workflow_exists_and_targets_only_v2_7_branch():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/v2-7-focused.yml").read_text()
    assert "name: V2-7 Focused" in text
    assert "work/v2-manufacturing-routing-production-qc-fulfillment" in text
    assert "Verify frozen Customer API v1 no drift" in text
    assert "Validate Golden reference integrity metadata only" in text
    assert "Verify canonical brand hashes" in text


@pytest.mark.django_db
def test_maneg_v2_7_route_is_staff_admin_surface_not_public_marketplace_surface(client):
    response = client.get("/Maneg/production-routing/")
    assert response.status_code in {302, 403}
    assert not RFQ.objects.filter(source=RFQ.Source.CUSTOMER_ORDER).exists()
