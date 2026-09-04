import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomerCustomization, CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject
from apps.storefront.services import reopen_project_for_attention, validate_studio_project

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_visual_studio_migration_preserves_preexisting_projects_elements_and_transforms():
    owner = User.objects.create_user(username="migration-owner", password="password12345")
    customer = User.objects.create_user(username="migration-customer", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Migration Designer",
        email="migration@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=org, title="Legacy Tee", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    zone = DecorationZone.objects.create(version=garment, name="Legacy Front", method=DecorationZone.Method.BOTH, placement={"x": .5, "y": .5})
    artwork = Artwork.objects.create(organization=org, title="Legacy Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment, artwork_version=artwork_version, title="Legacy Product", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = Storefront.objects.create(organization=org, slug="migration-store", status=Storefront.Status.PUBLISHED, name_en="Migration Store")
    product = StoreProduct.objects.create(storefront=store, designed_product=designed, slug="legacy-product", status=StoreProduct.Status.PUBLISHED, title_en="Legacy Product", base_price="400.00", customization_enabled=True)
    variant = ProductVariant.objects.create(product=product, sku="MIG-LEGACY", size="M", is_active=True)
    legacy_private = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="legacy/private/image.png",
        original_filename="legacy.png",
        mime_type="image/png",
        size_bytes=10,
        access=MediaAsset.Access.PRIVATE,
        uploaded_by=customer,
        metadata={},
    )

    project = StudioProject.objects.create(customer=customer, product=product, variant=variant, status=StudioProject.Status.READY, quantity=1)
    customization = CustomerCustomization.objects.create(project=project, enabled=True)
    text_transform = {"x": .31, "y": .42, "scale": .27, "rotation": 12}
    image_transform = {"x": .62, "y": .48, "scale": .21, "rotation": -18}
    text = CustomizationElement.objects.create(
        customization=customization,
        decoration_zone=zone,
        kind=CustomizationElement.Kind.TEXT,
        text="Historical text",
        transform=text_transform,
        style={"font": "legacy"},
        production_method="",
        rights_confirmed=False,
    )
    image = CustomizationElement.objects.create(
        customization=customization,
        decoration_zone=zone,
        kind=CustomizationElement.Kind.IMAGE,
        media_asset=legacy_private,
        transform=image_transform,
        style={"legacy": True},
        production_method="",
        rights_confirmed=False,
    )
    original_ids = {project.pk, text.pk, image.pk}

    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("storefront", "0001_initial")])
        old_apps = executor.loader.project_state([("storefront", "0001_initial")]).apps
        OldProject = old_apps.get_model("storefront", "StudioProject")
        OldElement = old_apps.get_model("storefront", "CustomizationElement")

        old_project = OldProject.objects.get(pk=project.pk)
        old_text = OldElement.objects.get(pk=text.pk)
        old_image = OldElement.objects.get(pk=image.pk)
        assert old_project.status == "ready"
        assert old_text.kind == "text" and old_text.text == "Historical text"
        assert old_image.kind == "image" and old_image.media_asset_id == legacy_private.pk
        assert old_text.transform == text_transform
        assert old_image.transform == image_transform
        assert OldProject.objects.filter(pk=project.pk).count() == 1
        assert OldElement.objects.filter(customization_id=customization.pk).count() == 2

        executor = MigrationExecutor(connection)
        executor.migrate([("storefront", "0002_visual_studio_elements")])
    finally:
        # Restore the entire repository migration graph, not only storefront.
        # Backward migration of storefront can unapply dependent app migrations;
        # leaving those unapplied makes later source-only/fixture tests observe a
        # partially dismantled schema.
        executor = MigrationExecutor(connection)
        executor.migrate(latest_targets)

    project = StudioProject.objects.get(pk=project.pk)
    text = CustomizationElement.objects.get(pk=text.pk)
    image = CustomizationElement.objects.get(pk=image.pk)
    assert {project.pk, text.pk, image.pk} == original_ids
    assert project.status == StudioProject.Status.READY
    assert text.transform == text_transform
    assert image.transform == image_transform
    assert text.artwork_version_id is None and image.artwork_version_id is None
    assert text.production_method == "" and image.production_method == ""
    assert text.rights_confirmed is False and image.rights_confirmed is False
    assert CustomizationElement.objects.filter(customization__project=project).count() == 2

    # The migration preserves history rather than falsifying it. A historical
    # weak READY record that no longer satisfies today's upload provenance/
    # rights rules is blocked from new commerce, then can be reopened safely.
    with pytest.raises(ValidationError):
        validate_studio_project(project)
    reopened = reopen_project_for_attention(project=project, actor=customer)
    assert reopened.status == StudioProject.Status.DRAFT
    assert reopened.ready_at is None
    assert CustomizationElement.objects.filter(customization__project=reopened).count() == 2
    assert CustomizationElement.objects.get(pk=text.pk).transform == text_transform
    assert CustomizationElement.objects.get(pk=image.pk).transform == image_transform
