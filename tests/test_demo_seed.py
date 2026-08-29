import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.models import User
from apps.artwork.models import Artwork, DesignedProduct
from apps.design.models import GarmentDesign
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerQuote, RFQ
from apps.organizations.models import Organization
from apps.platform_ops.public_urls import absolute_public_url
from apps.storefront.models import StoreProduct, StudioProject


DEMO_SETTINGS = {
    "FABINZI_DEMO_SEED_ENABLED": True,
    "DEMO_ADMIN_EMAIL": "admin.qa@example.test",
    "DEMO_ADMIN_PASSWORD": "AdminDemoPass123!",
    "DEMO_DESIGNER_EMAIL": "designer.qa@example.test",
    "DEMO_DESIGNER_PASSWORD": "DesignerDemoPass123!",
    "DEMO_MANUFACTURER_EMAIL": "manufacturer.qa@example.test",
    "DEMO_MANUFACTURER_PASSWORD": "ManufacturerDemoPass123!",
    "DEMO_CUSTOMER_EMAIL": "customer.qa@example.test",
    "DEMO_CUSTOMER_PASSWORD": "CustomerDemoPass123!",
}


@pytest.mark.django_db
def test_seed_demo_refuses_when_disabled():
    with override_settings(FABINZI_DEMO_SEED_ENABLED=False):
        with pytest.raises(CommandError, match="Demo seeding is disabled"):
            call_command("seed_demo")


@pytest.mark.django_db
def test_seed_demo_requires_password_environment_values():
    with override_settings(**(DEMO_SETTINGS | {"DEMO_CUSTOMER_PASSWORD": ""})):
        with pytest.raises(CommandError, match="Missing demo password"):
            call_command("seed_demo")


@pytest.mark.django_db
def test_seed_demo_is_idempotent_and_builds_real_domain_graph():
    with override_settings(**DEMO_SETTINGS):
        call_command("seed_demo", verbosity=0)
        first = {
            "users": User.objects.filter(username__startswith="fabinzi_demo_").count(),
            "organizations": Organization.objects.filter(display_name__startswith="FABINZI Demo").count(),
            "designs": GarmentDesign.objects.filter(organization__display_name="FABINZI Demo Studio").count(),
            "artworks": Artwork.objects.filter(organization__display_name="FABINZI Demo Studio").count(),
            "designed_products": DesignedProduct.objects.filter(organization__display_name="FABINZI Demo Studio").count(),
            "store_products": StoreProduct.objects.filter(storefront__organization__display_name="FABINZI Demo Studio").count(),
            "rfqs": RFQ.objects.filter(designer_organization__display_name="FABINZI Demo Studio").count(),
            "quotes": ManufacturerQuote.objects.filter(invitation__manufacturer__display_name="FABINZI Demo Manufacturing").count(),
            "capabilities": ManufacturerCapability.objects.filter(listing__organization__display_name="FABINZI Demo Manufacturing").count(),
            "projects": StudioProject.objects.filter(customer__username="fabinzi_demo_customer").count(),
        }
        call_command("seed_demo", verbosity=0)
        second = {
            "users": User.objects.filter(username__startswith="fabinzi_demo_").count(),
            "organizations": Organization.objects.filter(display_name__startswith="FABINZI Demo").count(),
            "designs": GarmentDesign.objects.filter(organization__display_name="FABINZI Demo Studio").count(),
            "artworks": Artwork.objects.filter(organization__display_name="FABINZI Demo Studio").count(),
            "designed_products": DesignedProduct.objects.filter(organization__display_name="FABINZI Demo Studio").count(),
            "store_products": StoreProduct.objects.filter(storefront__organization__display_name="FABINZI Demo Studio").count(),
            "rfqs": RFQ.objects.filter(designer_organization__display_name="FABINZI Demo Studio").count(),
            "quotes": ManufacturerQuote.objects.filter(invitation__manufacturer__display_name="FABINZI Demo Manufacturing").count(),
            "capabilities": ManufacturerCapability.objects.filter(listing__organization__display_name="FABINZI Demo Manufacturing").count(),
            "projects": StudioProject.objects.filter(customer__username="fabinzi_demo_customer").count(),
        }

    assert first == second
    assert first == {
        "users": 4,
        "organizations": 2,
        "designs": 5,
        "artworks": 3,
        "designed_products": 6,
        "store_products": 6,
        "rfqs": 3,
        "quotes": 3,
        "capabilities": 5,
        "projects": 3,
    }
    assert User.objects.get(username="fabinzi_demo_admin").is_superuser is True
    assert Organization.objects.get(display_name="FABINZI Demo Studio").verification_status == Organization.VerificationStatus.ACTIVE
    assert Organization.objects.get(display_name="FABINZI Demo Manufacturing").verification_status == Organization.VerificationStatus.ACTIVE


def test_absolute_public_url_uses_central_setting():
    with override_settings(FABINZI_PUBLIC_BASE_URL="https://fabinzi.example/"):
        assert absolute_public_url("/orders/42/") == "https://fabinzi.example/orders/42/"
