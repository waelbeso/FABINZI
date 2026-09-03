import os

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.artwork.models import (
    Artwork,
    ArtworkAsset,
    ArtworkRegistrationCase,
    ArtworkRegistrationSource,
    ArtworkVersion,
    DesignedProduct,
    IPDeclaration,
)
from apps.artwork.services import (
    add_registration_document,
    create_designed_product,
    create_registration_case,
    transition_registration_case,
)
from apps.design.golden_reference import seed_fabinzi_reference_demo
from apps.design.manufacturer_projection import manufacturer_technical_projection
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
    ReferencePackage,
    SizeChartRow,
)
from apps.design.reference_v2_4 import enrich_source_supported_reference_mapping
from apps.design.services import (
    evaluate_version_eligibility,
    review_version,
    set_production_engineering_validation,
    submit_version,
    technical_completeness,
)
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.subscriptions.services import ensure_subscription_for_organization

User = get_user_model()


def _designer(name="designer-v24"):
    user = User.objects.create_user(username=name, email=f"{name}@example.test", password="password123")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=f"{name} studio",
        email=f"org-{name}@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    ensure_subscription_for_organization(org, actor=user)
    return user, org


def _manufacturer(name="manufacturer-v24"):
    user = User.objects.create_user(username=name, email=f"{name}@example.test", password="password123")
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name=f"{name} factory",
        email=f"org-{name}@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    ensure_subscription_for_organization(org, actor=user)
    return user, org


def _media(user, *, name, mime, access="private", metadata=None):
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=f"tests/v2-4/{user.pk}/{name}",
        original_filename=name,
        mime_type=mime,
        size_bytes=100,
        checksum_sha256=("a" * 64),
        access=access,
        metadata=metadata or {},
        uploaded_by=user,
    )


def _complete_design(user, org, *, title="Production Complete Design"):
    design = GarmentDesign.objects.create(
        organization=org,
        title=title,
        category="T-Shirt",
        created_by=user,
    )
    version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        base_material="180 GSM cotton",
        construction_notes="Factory-ready construction notes subject to review.",
        technical_specs={"seam": "reference"},
        product_class=GarmentDesignVersion.ProductClass.APPAREL,
        size_system=GarmentDesignVersion.SizeSystem.MULTI_SIZE,
        decoration_applicability=GarmentDesignVersion.DecorationApplicability.CONFIGURED,
        requires_3d_source=True,
        qc_requirements={"measurement_check": True},
        created_by=user,
    )
    size = SizeChartRow.objects.create(version=version, size_label="M", measurements={"legacy": "kept"})
    point = DesignPointOfMeasure.objects.create(
        version=version,
        symbolic_ref="POM-TEST-01",
        name="Half chest",
        unit=DesignPointOfMeasure.Unit.CM,
        tolerance_plus="1.0",
        tolerance_minus="1.0",
    )
    DesignPOMValue.objects.create(point=point, size=size, value="53.0")
    DesignMaterial.objects.create(
        version=version,
        symbolic_ref="MAT-TEST-01",
        role="main_body",
        name="Cotton jersey",
        composition="100% cotton",
        gsm="180",
    )

    pattern_media = _media(user, name="pattern-M.dxf", mime="application/dxf")
    techpack_media = _media(user, name="tech-pack.pdf", mime="application/pdf")
    threed_media = _media(user, name="source.glb", mime="model/gltf-binary")
    technical_media = _media(user, name="construction.pdf", mime="application/pdf")
    image_media = _media(user, name="product.png", mime="image/png")
    pattern = DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.PATTERN, media_asset=pattern_media, label="M pattern", size_label="M")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.TECH_PACK, media_asset=techpack_media, label="Tech Pack")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.THREE_D, media_asset=threed_media, label="3D source")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.TECHNICAL, media_asset=technical_media, label="Construction source")
    image = DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.PRODUCT_IMAGE, media_asset=image_media, label="Black product image")
    DesignPatternRequirement.objects.create(version=version, size=size, required=True, declared_scale_1_to_1=True, pattern_asset=pattern)
    colorway = DesignColorway.objects.create(version=version, symbolic_ref="CW-TEST-BLK", name="Black", hex_color="#000000")
    DesignColorwayImage.objects.create(colorway=colorway, asset=image, role=DesignColorwayImage.Role.PRODUCT_DETAIL)
    DecorationZone.objects.create(
        version=version,
        symbolic_ref="DZ-TEST-FRONT",
        name="Front",
        surface="FRONT",
        method=DecorationZone.Method.PRINT,
        allowed_methods=[DecorationZone.ProductionMethod.DTF, DecorationZone.ProductionMethod.DTG],
        placement={"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.5},
        max_width_mm="300",
        max_height_mm="380",
    )
    return design, version


@pytest.mark.django_db
def test_golden_fixture_maps_exactly_five_products_and_preserves_not_for_production(monkeypatch):
    monkeypatch.setenv("FABINZI_ALLOW_REFERENCE_DEMO_SEED", "1")
    result = seed_fabinzi_reference_demo(contract_fixture=True)
    mapping = enrich_source_supported_reference_mapping()

    assert sorted(result["products"]) == ["GP001", "GP002", "GP003", "GP004", "GP005"]
    assert ReferencePackage.objects.count() == 5
    assert not ReferencePackage.objects.filter(product_ref="GP006").exists()
    assert not result["direct_binary_evidence"]
    assert mapping["package_binary_verification_claimed"] is False
    for package in ReferencePackage.objects.all():
        assert package.status == ReferencePackage.Status.APPROVED_REFERENCE
        assert package.golden_reference_complete is True
        assert package.public_reference_allowed is True
        assert package.production_engineering_validated is False

    gp003 = GarmentDesignVersion.objects.get(symbolic_ref="GDV-DDR-001-V1")
    assert list(gp003.size_rows.values_list("size_label", flat=True)) == ["XS", "S", "M", "L", "XL"]
    assert gp003.points_of_measure.count() == 10
    assert gp003.materials.count() == 3
    assert gp003.technical_blockers.filter(status="open").count() == 8
    assert gp003.decoration_applicability == GarmentDesignVersion.DecorationApplicability.NOT_APPLICABLE
    assert gp003.decoration_zones.count() == 0
    assert gp003.pattern_requirements.count() == 5
    assert gp003.pattern_requirements.filter(pattern_asset__isnull=False).count() == 0
    eligibility = evaluate_version_eligibility(gp003)
    assert eligibility["reference_approved"] is True
    assert eligibility["production_eligible"] is False
    assert eligibility["commercial_eligible"] is False


@pytest.mark.django_db
def test_reference_mapping_supports_apparel_accessory_headwear_and_no_decoration(monkeypatch):
    monkeypatch.setenv("FABINZI_ALLOW_REFERENCE_DEMO_SEED", "1")
    seed_fabinzi_reference_demo(contract_fixture=True)
    enrich_source_supported_reference_mapping()
    assert GarmentDesignVersion.objects.get(symbolic_ref="GDV-MTS-001-V1").size_system == "multi_size"
    assert GarmentDesignVersion.objects.get(symbolic_ref="GDV-WTS-001-V1").size_rows.count() == 5
    assert GarmentDesignVersion.objects.get(symbolic_ref="GDV-DDR-001-V1").decoration_applicability == "not_applicable"
    assert GarmentDesignVersion.objects.get(symbolic_ref="GDV-CBG-001-V1").size_system == "one_size_accessory"
    cap = GarmentDesignVersion.objects.get(symbolic_ref="GDV-CAP-001-V1")
    assert cap.product_class == "headwear"
    assert cap.decoration_zones.get(symbolic_ref="DZ-CAP-FRONT-001").effective_methods() == ["embroidery"]


@pytest.mark.django_db
def test_real_designer_production_completeness_is_stricter_than_golden_reference():
    user, org = _designer()
    _, version = _complete_design(user, org)
    result = technical_completeness(version)
    assert result == {"complete": True, "errors": []}

    version.pattern_requirements.update(declared_scale_1_to_1=False)
    result = technical_completeness(version)
    assert result["complete"] is False
    assert any("Pattern scale declaration" in item for item in result["errors"])


@pytest.mark.django_db
def test_four_design_eligibility_concerns_remain_distinct():
    user, org = _designer("eligibility-v24")
    staff = User.objects.create_user(username="staff-v24", password="password123", is_staff=True)
    design, version = _complete_design(user, org, title="Eligibility Design")

    before = evaluate_version_eligibility(version)
    assert before["technical_complete"] is True
    assert before["technical_approved"] is False
    assert before["commercial_eligible"] is False
    assert before["production_eligible"] is False

    submit_version(version=version, actor=user)
    review_version(version=version, reviewer=staff, decision="approved", notes="Technical review pass")
    approved = evaluate_version_eligibility(version)
    assert approved["technical_approved"] is True
    assert approved["commercial_eligible"] is True
    assert approved["production_eligible"] is False

    set_production_engineering_validation(version=version, reviewer=staff, validated=True, notes="Factory engineering evidence reviewed")
    production = evaluate_version_eligibility(version)
    assert production["commercial_eligible"] is True
    assert production["production_eligible"] is True


@pytest.mark.django_db
def test_manufacturer_projection_is_same_gdv_and_withholds_private_asset_identifiers(monkeypatch):
    monkeypatch.setenv("FABINZI_ALLOW_REFERENCE_DEMO_SEED", "1")
    result = seed_fabinzi_reference_demo(contract_fixture=True)
    enrich_source_supported_reference_mapping()
    version = GarmentDesignVersion.objects.get(symbolic_ref="GDV-CBG-001-V1")
    manufacturer_user = User.objects.get(username="fabinzi-reference-manufacturer")
    manufacturer_org = Organization.objects.get(pk=result["demo_manufacturer_organization_id"])

    projection = manufacturer_technical_projection(
        version=version,
        manufacturer_organization=manufacturer_org,
        actor=manufacturer_user,
    )
    assert projection["gdv_id"] == version.pk
    assert projection["gdv_ref"] == "GDV-CBG-001-V1"
    assert projection["same_gdv_invariant"] is True
    assert projection["source_reference"]["product_ref"] == "GP004"
    assert projection["assets"]["private_assets_authorized"] is False
    assert projection["eligibility"]["production_eligible"] is False


@pytest.mark.django_db
def test_private_technical_design_asset_rejects_public_media():
    user, org = _designer("asset-v24")
    design = GarmentDesign.objects.create(organization=org, title="Asset gate", created_by=user)
    version = GarmentDesignVersion.objects.create(design=design, version_number=1, created_by=user)
    public_media = _media(user, name="public-tech.pdf", mime="application/pdf", access=MediaAsset.Access.PUBLIC)
    asset = DesignAsset(version=version, kind=DesignAsset.Kind.TECH_PACK, media_asset=public_media)
    with pytest.raises(ValidationError):
        asset.full_clean()


@pytest.mark.django_db
def test_registration_case_cannot_fabricate_visual_scc_applicability_or_external_submission():
    user, org = _designer("registration-v24")
    artwork = Artwork.objects.create(organization=org, title="Registration candidate", created_by=user)
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, intended_methods=["dtf"], created_by=user)
    case = create_registration_case(version=version, applicant=user)
    staff = User.objects.create_user(username="registration-staff-v24", password="password123", is_staff=True)
    transition_registration_case(case=case, reviewer=staff, status=ArtworkRegistrationCase.Status.STAFF_REVIEW)
    with pytest.raises(ValidationError):
        transition_registration_case(case=case, reviewer=staff, status=ArtworkRegistrationCase.Status.READY_FOR_EXTERNAL_SUBMISSION)

    source = ArtworkRegistrationSource.objects.create(
        source_name="Written works source snapshot",
        source_filename="written-works-source.pdf",
        source_version="source-snapshot-1",
        visual_graphic_applicability_confirmed=False,
        source_limitations="Supplied source concerns written works; visual/graphic applicability not proven.",
    )
    case.source_snapshot = source
    case.save(update_fields=["source_snapshot"])
    with pytest.raises(ValidationError):
        transition_registration_case(case=case, reviewer=staff, status=ArtworkRegistrationCase.Status.READY_FOR_EXTERNAL_SUBMISSION)


@pytest.mark.django_db
def test_customer_studio_private_media_cannot_become_registration_evidence():
    user, org = _designer("privacy-v24")
    artwork = Artwork.objects.create(organization=org, title="Privacy boundary", created_by=user)
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, intended_methods=["dtf"], created_by=user)
    case = create_registration_case(version=version, applicant=user)
    studio_media = _media(
        user,
        name="customer-studio.png",
        mime="image/png",
        metadata={"studio_private_upload": True},
    )
    with pytest.raises(ValidationError):
        add_registration_document(case=case, actor=user, media_asset=studio_media, kind="supporting_copy")


@pytest.mark.django_db
def test_ready_designed_product_supports_independent_artwork_creator_attribution():
    garment_user, garment_org = _designer("garment-author-v24")
    artwork_user, artwork_org = _designer("artwork-author-v24")
    _, garment_version = _complete_design(garment_user, garment_org, title="Attributed garment")
    garment_version.status = GarmentDesignVersion.Status.APPROVED
    garment_version.production_engineering_validated = True
    garment_version.save(update_fields=["status", "production_engineering_validated"])
    garment_version.design.status = GarmentDesign.Status.APPROVED
    garment_version.design.save(update_fields=["status"])

    artwork = Artwork.objects.create(organization=artwork_org, title="Independent Artwork", status=Artwork.Status.APPROVED, created_by=artwork_user)
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        intended_methods=["dtf"],
        technical_check_status=ArtworkVersion.TechnicalCheckStatus.PASS,
        created_by=artwork_user,
    )
    product = create_designed_product(
        organization=garment_org,
        actor=garment_user,
        garment_version=garment_version,
        artwork_version=artwork_version,
        title="Cross-creator Ready Designed Product",
    )
    assert product.garment_creator_organization_id == garment_org.pk
    assert product.artwork_creator_organization_id == artwork_org.pk
    assert product.economic_attribution["garment_creator_organization_id"] == garment_org.pk
    assert product.economic_attribution["artwork_creator_organization_id"] == artwork_org.pk


@pytest.mark.django_db
def test_v2_4_creator_technical_routes_are_server_authorized(client):
    user, org = _designer("portal-v24")
    other = User.objects.create_user(username="portal-outsider-v24", password="password123")
    design = GarmentDesign.objects.create(organization=org, title="Portal design", created_by=user)
    GarmentDesignVersion.objects.create(design=design, version_number=1, created_by=user)
    artwork = Artwork.objects.create(organization=org, title="Portal artwork", created_by=user)
    ArtworkVersion.objects.create(artwork=artwork, version_number=1, intended_methods=["dtf"], created_by=user)

    client.force_login(user)
    assert client.get(f"/designer/designs/{design.pk}/technical/").status_code == 200
    assert client.get(f"/designer/artworks/{artwork.pk}/technical/").status_code == 200

    client.force_login(other)
    assert client.get(f"/designer/designs/{design.pk}/technical/").status_code == 403
    assert client.get(f"/designer/artworks/{artwork.pk}/technical/").status_code == 403
