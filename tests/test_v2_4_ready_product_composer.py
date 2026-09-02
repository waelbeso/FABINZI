import pytest
from django.contrib.auth import get_user_model

from apps.artwork.models import Artwork, ArtworkPlacement, ArtworkVersion, DesignedProduct
from apps.design.models import (
    DecorationZone,
    DesignAsset,
    DesignColorway,
    DesignColorwayImage,
    DesignMaterial,
    DesignPOMValue,
    DesignPatternRequirement,
    DesignPointOfMeasure,
    GarmentDesign,
    GarmentDesignVersion,
    SizeChartRow,
)
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.subscriptions.services import ensure_subscription_for_organization

User = get_user_model()


def _designer(name):
    user = User.objects.create_user(username=name, email=f"{name}@example.test", password="password123")
    org = Organization.objects.create(kind="designer", display_name=name, email=f"org-{name}@example.test", verification_status="active", created_by=user)
    Membership.objects.create(organization=org, user=user, role="owner")
    ensure_subscription_for_organization(org, actor=user)
    return user, org


def _media(user, name, mime):
    return MediaAsset.objects.create(
        provider="local_dev", provider_asset_id=f"v24/{user.pk}/{name}", original_filename=name,
        mime_type=mime, size_bytes=10, checksum_sha256="b" * 64, access="private", uploaded_by=user,
    )


def _eligible_garment(user, org):
    design = GarmentDesign.objects.create(organization=org, title="Own garment", status="approved", created_by=user)
    version = GarmentDesignVersion.objects.create(
        design=design, version_number=1, status="approved", base_material="cotton", construction_notes="construction",
        technical_specs={"ready": True}, product_class="apparel", size_system="multi_size", decoration_applicability="configured",
        requires_3d_source=True, qc_requirements={"qc": True}, production_engineering_validated=True, created_by=user,
    )
    size = SizeChartRow.objects.create(version=version, size_label="M")
    pom = DesignPointOfMeasure.objects.create(version=version, symbolic_ref="POM-RDP-1", name="Half chest")
    DesignPOMValue.objects.create(point=pom, size=size, value="50")
    DesignMaterial.objects.create(version=version, symbolic_ref="MAT-RDP-1", role="main", name="Cotton")
    pattern = DesignAsset.objects.create(version=version, kind="pattern", media_asset=_media(user, "pattern.dxf", "application/dxf"))
    DesignAsset.objects.create(version=version, kind="tech_pack", media_asset=_media(user, "tech.pdf", "application/pdf"))
    DesignAsset.objects.create(version=version, kind="3d", media_asset=_media(user, "source.glb", "model/gltf-binary"))
    DesignAsset.objects.create(version=version, kind="technical", media_asset=_media(user, "construction.pdf", "application/pdf"))
    image = DesignAsset.objects.create(version=version, kind="product_image", media_asset=_media(user, "product.png", "image/png"))
    DesignPatternRequirement.objects.create(version=version, size=size, declared_scale_1_to_1=True, pattern_asset=pattern)
    colorway = DesignColorway.objects.create(version=version, symbolic_ref="CW-RDP-1", name="Black")
    DesignColorwayImage.objects.create(colorway=colorway, asset=image, role="product_detail")
    zone = DecorationZone.objects.create(
        version=version, symbolic_ref="DZ-RDP-FRONT", name="Front", surface="FRONT", method="print",
        allowed_methods=["dtf", "dtg"], placement={"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.5},
        max_width_mm="300", max_height_mm="380",
    )
    return version, zone


@pytest.mark.django_db
def test_ready_product_composer_allows_independent_approved_artwork_creator_and_canonical_zone(client):
    garment_user, garment_org = _designer("composer-garment")
    artwork_user, artwork_org = _designer("composer-artwork")
    garment_version, zone = _eligible_garment(garment_user, garment_org)
    artwork = Artwork.objects.create(organization=artwork_org, title="Independent approved artwork", status="approved", created_by=artwork_user)
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork, version_number=1, status="approved", intended_methods=["dtf"], technical_check_status="pass", created_by=artwork_user,
    )

    client.force_login(garment_user)
    response = client.post(
        "/designer/products/compose/",
        {"garment_version_id": garment_version.pk, "artwork_version_id": artwork_version.pk, "title": "Cross creator product"},
    )
    assert response.status_code == 302
    product = DesignedProduct.objects.get(title="Cross creator product")
    assert product.organization_id == garment_org.pk
    assert product.garment_creator_organization_id == garment_org.pk
    assert product.artwork_creator_organization_id == artwork_org.pk

    response = client.post(
        f"/designer/products/compose/{product.pk}/",
        {"action": "add_placement", "zone_id": zone.pk, "production_method": "dtf", "x": "0.25", "y": "0.25", "width": "0.20", "height": "0.20", "rotation": "0"},
    )
    assert response.status_code == 302
    placement = ArtworkPlacement.objects.get(product=product)
    assert placement.decoration_zone_id == zone.pk
    assert placement.production_method == "dtf"


@pytest.mark.django_db
def test_ready_product_composer_rejects_other_organizations_garment(client):
    owner, owner_org = _designer("composer-owner")
    outsider, outsider_org = _designer("composer-outsider")
    garment_version, _ = _eligible_garment(owner, owner_org)
    artwork = Artwork.objects.create(organization=owner_org, title="Approved artwork", status="approved", created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status="approved", intended_methods=["dtf"], technical_check_status="pass", created_by=owner)

    client.force_login(outsider)
    response = client.post(
        "/designer/products/compose/",
        {"garment_version_id": garment_version.pk, "artwork_version_id": artwork_version.pk, "title": "Unauthorized product"},
    )
    assert response.status_code == 200
    assert not DesignedProduct.objects.filter(title="Unauthorized product").exists()
