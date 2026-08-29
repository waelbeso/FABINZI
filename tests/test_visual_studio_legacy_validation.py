import pytest
from django.contrib.auth import get_user_model

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomerCustomization, CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject
from apps.storefront.services import validate_studio_project

User = get_user_model()


@pytest.mark.django_db
def test_legacy_text_with_blank_method_and_rights_false_validates_without_mutating_history():
    owner = User.objects.create_user(username="legacy-text-owner", password="password12345")
    customer = User.objects.create_user(username="legacy-text-customer", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="Legacy Text Designer", email="legacy-text@test.local", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=org, title="Legacy Text Tee", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    zone = DecorationZone.objects.create(version=garment, name="Front", method=DecorationZone.Method.BOTH, placement={"x": .5, "y": .5})
    artwork = Artwork.objects.create(organization=org, title="Base Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment, artwork_version=version, title="Legacy Text Product", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = Storefront.objects.create(organization=org, slug="legacy-text-store", status=Storefront.Status.PUBLISHED, name_en="Legacy Text Store")
    product = StoreProduct.objects.create(storefront=store, designed_product=designed, slug="legacy-text-product", status=StoreProduct.Status.PUBLISHED, title_en="Legacy Text Product", base_price="450.00", customization_enabled=True)
    variant = ProductVariant.objects.create(product=product, sku="LEG-TEXT-M", size="M", is_active=True)
    project = StudioProject.objects.create(customer=customer, product=product, variant=variant, status=StudioProject.Status.READY, quantity=1)
    customization = CustomerCustomization.objects.create(project=project, enabled=True)
    element = CustomizationElement.objects.create(
        customization=customization,
        decoration_zone=zone,
        kind=CustomizationElement.Kind.TEXT,
        text="Historical text",
        production_method="",
        rights_confirmed=False,
        transform={"x": .5, "y": .5, "scale": .2, "rotation": 0},
    )

    result = validate_studio_project(project)
    assert result["valid"] is True
    element.refresh_from_db()
    assert element.production_method == ""
    assert element.rights_confirmed is False
    assert element.artwork_version_id is None
