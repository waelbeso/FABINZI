import hashlib
import io
import os
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from apps.organizations.models import DesignerProfile, ManufacturerProfile, Membership, Organization
from .models import (
    DecorationZone,
    DesignColorway,
    DesignMaterial,
    DesignPOMValue,
    DesignPointOfMeasure,
    DesignReferenceProvenance,
    GarmentDesign,
    GarmentDesignVersion,
    ReferenceDataset,
    ReferencePackage,
    SizeChartRow,
    TechnicalBlocker,
)

DATASET_NAME = "FABINZI Golden Reference Dataset"
DATASET_VERSION = "1.0"
REFERENCE_NOTICE = "FABINZI GOLDEN REFERENCE DATASET | DEMO / TRAINING REFERENCE | NOT FOR PRODUCTION"
IMPORT_IMPLEMENTATION_VERSION = "v2-4.1"
MACHINE_CONTRACT_IDENTITY = "FABINZI Golden Product Machine Contract"
MACHINE_CONTRACT_VERSION = "1.0"
MACHINE_CONTRACT_SHA256 = "46235ca6f221575c45645a1388ffa410e331320470508d8cf8374f7c02616a6f"
IMAGE_ROLE_CONTRACT_IDENTITY = "FABINZI Golden Image Role QA Contract"
IMAGE_ROLE_CONTRACT_VERSION = "1.0"
IMAGE_ROLE_CONTRACT_SHA256 = "74f4fb0a388ace493b06cfb6c68e7c4a8b61d73bce1b82a3c7d44fca9b3b0176"

EXPECTED_PRODUCTS = {
    "GP001": {
        "name": "Men's T-Shirt",
        "filename": "FABINZI_GP001_Golden_Reference_v1.0.zip",
        "sha256": "acece3e05f13143624e805d1e9ea57b494e0e1d58120d833144565c47e2f9edf",
        "design_ref": "DESIGN-MTS-001",
        "gdv_ref": "GDV-MTS-001-V1",
    },
    "GP002": {
        "name": "Women's T-Shirt",
        "filename": "FABINZI_GP002_Golden_Reference_v1.0.zip",
        "sha256": "a8f44ab55eda7bab03b0dd5a92a71dd62b794d81f2e89ae7c37633062a24123e",
        "design_ref": "DESIGN-WTS-001",
        "gdv_ref": "GDV-WTS-001-V1",
    },
    "GP003": {
        "name": "Day Dress",
        "filename": "FABINZI_GP003_Golden_Reference_v1.0.zip",
        "sha256": "7fee3a6362bdaa0fbd0c03f2c2a42234d960228405dd4946e40fc20d8ff6a463",
        "design_ref": "DESIGN-DDR-001",
        "gdv_ref": "GDV-DDR-001-V1",
    },
    "GP004": {
        "name": "Canvas Bag",
        "filename": "FABINZI_GP004_Golden_Reference_v1.0.zip",
        "sha256": "b05405620189e7c9f8d564db3650a683880a9ca1670124fc7266713ead1ed75f",
        "design_ref": "DESIGN-CBG-001",
        "gdv_ref": "GDV-CBG-001-V1",
    },
    "GP005": {
        "name": "Cap",
        "filename": "FABINZI_GP005_Golden_Reference_v1.0.zip",
        "sha256": "39fdc2beb5fa38476f42235c1e11931309f73655c9fa88ee254626518d09c19c",
        "design_ref": "DESIGN-CAP-001",
        "gdv_ref": "GDV-CAP-001-V1",
    },
}

# These schema fixtures are deliberately limited to values supported by the frozen
# Golden source material already supplied to the V2 program. Missing genuine
# Pattern, 3D and image binaries are not manufactured here. A fixture import is
# contract/schema evidence only; it is never binary verification evidence.
GOLDEN_SCHEMA_FIXTURES = {
    "GP001": {
        "product_class": "apparel",
        "size_system": "multi_size",
        "category": "Men's T-Shirt",
        "base_material": "Golden reference apparel material; see frozen package for canonical material/BOM detail.",
        "construction_notes": "Golden reference construction is source-defined; not factory validated.",
        "qc_requirements": {"reference_only": True, "production_engineering_validated": False},
        "requires_3d_source": True,
        "colorway": ("CW-MTS-LAV-001", "Lavender", ""),
        "sizes": {
            "S": ["50.0", "69.0", "44.0", "20.0", "17.0", "50.0", "18.0", "8.5", "2.0"],
            "M": ["53.0", "72.0", "46.0", "21.0", "18.0", "53.0", "18.5", "9.0", "2.0"],
            "L": ["56.0", "74.0", "48.0", "22.0", "19.0", "56.0", "19.0", "9.5", "2.2"],
            "XL": ["59.0", "76.0", "50.0", "23.0", "20.0", "59.0", "19.5", "10.0", "2.2"],
        },
        "poms": [
            ("POM-MTS-01", "Half chest / pit-to-pit", "1.0"),
            ("POM-MTS-02", "Body length HPS", "1.5"),
            ("POM-MTS-03", "Shoulder width", "1.0"),
            ("POM-MTS-04", "Sleeve length", "1.0"),
            ("POM-MTS-05", "Sleeve opening half", "0.8"),
            ("POM-MTS-06", "Bottom opening half", "1.0"),
            ("POM-MTS-07", "Neck width", "0.5"),
            ("POM-MTS-08", "Front neck drop", "0.5"),
            ("POM-MTS-09", "Back neck drop", "0.4"),
        ],
        "zones": [
            ("DZ-MTS-FRONT-001", "Front Main Print Zone", "FRONT", 300, 380, ["dtf", "dtg"], {}),
            ("DZ-MTS-BACK-001", "Back Print Zone", "BACK", 320, 420, ["dtf", "dtg"], {}),
            ("DZ-MTS-LCHEST-001", "Front Upper Left Print Zone", "FRONT", 100, 120, ["dtf", "dtg"], {}),
            ("DZ-MTS-RCHEST-001", "Front Upper Right Print Zone", "FRONT", 100, 120, ["dtf", "dtg"], {}),
        ],
        "blockers": [
            ("ENG-MTS-001", "Industrial production pattern per S/M/L/XL"),
            ("ENG-MTS-002", "Validated industrial grading / grade rules"),
            ("ENG-MTS-003", "Production-approved measurement specification and tolerances"),
            ("ENG-MTS-004", "Genuine apparel 3D/source model tied to final pattern"),
            ("ENG-MTS-005", "Fit/sample approval"),
            ("ENG-MTS-006", "Validated production material specification"),
            ("ENG-MTS-007", "Production Lavender color standard / lot approval"),
            ("ENG-MTS-008", "DTF/DTG process and durability validation on production fabric"),
        ],
    },
    "GP002": {
        "product_class": "apparel",
        "size_system": "multi_size",
        "category": "Women's T-Shirt",
        "base_material": "175 GSM 95% combed cotton / 5% elastane single jersey; synthetic reference, not lab validated.",
        "construction_notes": "Fitted/shaped women's T-shirt Golden reference construction; not factory validated.",
        "qc_requirements": {"reference_only": True, "production_engineering_validated": False},
        "requires_3d_source": True,
        "colorway": ("CW-WTS-LAV-001", "Lavender", "#DACADD"),
        "sizes": {
            "XS": ["41.0", "36.0", "59.0", "34.5", "14.5", "13.5", "42.0", "16.5", "8.0", "2.0"],
            "S": ["44.0", "39.0", "61.0", "36.0", "15.5", "14.0", "45.0", "17.0", "8.5", "2.0"],
            "M": ["47.0", "42.0", "63.0", "37.5", "16.5", "14.5", "48.0", "17.5", "9.0", "2.2"],
            "L": ["50.0", "45.0", "65.0", "39.0", "17.5", "15.0", "51.0", "18.0", "9.5", "2.2"],
            "XL": ["53.0", "48.0", "67.0", "40.5", "18.5", "15.5", "54.0", "18.5", "10.0", "2.4"],
        },
        "poms": [
            ("POM-WTS-01", "Half chest / pit-to-pit", "1.0"),
            ("POM-WTS-02", "Half waist", "1.0"),
            ("POM-WTS-03", "Body length HPS", "1.5"),
            ("POM-WTS-04", "Shoulder width", "0.8"),
            ("POM-WTS-05", "Sleeve length", "0.8"),
            ("POM-WTS-06", "Sleeve opening half", "0.7"),
            ("POM-WTS-07", "Bottom opening half", "1.0"),
            ("POM-WTS-08", "Neck width", "0.5"),
            ("POM-WTS-09", "Front neck drop", "0.5"),
            ("POM-WTS-10", "Back neck drop", "0.4"),
        ],
        "zones": [
            ("DZ-WTS-FRONT-001", "Front Main Print Zone", "FRONT", 240, 320, ["dtf", "dtg"], {}),
            ("DZ-WTS-LCHEST-001", "Front Upper Left Print Zone", "FRONT", 80, 100, ["dtf", "dtg"], {}),
            ("DZ-WTS-RCHEST-001", "Front Upper Right Print Zone", "FRONT", 80, 100, ["dtf", "dtg"], {}),
            ("DZ-WTS-BACK-001", "Back Print Zone", "BACK", 260, 340, ["dtf", "dtg"], {}),
        ],
        "materials": [
            ("MAT-WTS-BODY-001", "main_body", "Main body fabric", "95% combed cotton / 5% elastane", "175"),
            ("MAT-WTS-RIB-001", "neck_rib", "Neck rib", "95% cotton / 5% elastane", "210"),
        ],
        "blockers": [
            ("ENG-WTS-001", "Industrial production pattern for XS/S/M/L/XL"),
            ("ENG-WTS-002", "Validated women's industrial grading / grade rules"),
            ("ENG-WTS-003", "Production-approved women's measurement specification and tolerances"),
            ("ENG-WTS-004", "Genuine apparel 3D/source model tied to final production pattern"),
            ("ENG-WTS-005", "Women's fit block and fit/sample approval"),
            ("ENG-WTS-006", "Fabric composition/GSM/stretch-recovery/shrinkage/colorfastness/lot validation"),
            ("ENG-WTS-007", "Production Lavender color standard / lab dip / dye-lot approval"),
            ("ENG-WTS-008", "DTF/DTG print, cure, stretch and wash-durability validation on production fabric"),
        ],
    },
    "GP003": {
        "product_class": "apparel",
        "size_system": "multi_size",
        "category": "Day Dress",
        "base_material": "Golden Day Dress reference material; exact production validation remains unresolved.",
        "construction_notes": "Dress-specific Golden reference construction; detailed production engineering remains unresolved.",
        "qc_requirements": {"reference_only": True, "production_engineering_validated": False},
        "requires_3d_source": True,
        "colorway": ("CW-DDR-BIV-001", "Blush Ivory", ""),
        "sizes": {},
        "poms": [],
        "zones": [],
        "blockers": [("ENG-DDR-REFERENCE", "Production Engineering limitations remain unresolved in the frozen reference package.")],
        "decoration_not_applicable": True,
    },
    "GP004": {
        "product_class": "accessory",
        "size_system": "one_size_accessory",
        "category": "Canvas Bag",
        "base_material": "320 GSM 100% cotton canvas; synthetic Golden reference.",
        "construction_notes": "Canvas Bag Golden accessory construction; not production validated.",
        "qc_requirements": {"reference_only": True, "production_engineering_validated": False},
        "requires_3d_source": False,
        "colorway": ("CW-CBG-LAV-001", "Lavender", ""),
        "sizes": {"ONE SIZE": ["38.0", "40.0", "10.0", "38.0", "64.0", "3.0", "28.0", "8.0", "8.0"]},
        "poms": [
            ("POM-CBG-01", "Bag Body Width", None),
            ("POM-CBG-02", "Bag Body Height", None),
            ("POM-CBG-03", "Finished Depth / Gusset", None),
            ("POM-CBG-04", "Top Opening Width", None),
            ("POM-CBG-05", "Handle Total Length", None),
            ("POM-CBG-06", "Handle Width", None),
            ("POM-CBG-07", "Handle Drop", None),
            ("POM-CBG-08", "Handle Attachment Inset", None),
            ("POM-CBG-09", "Reinforcement Height", "0.5"),
        ],
        "zones": [
            ("DZ-CBG-FRONT-001", "Front Decoration Zone", "FRONT", 140, 220, ["dtf", "dtg"], {"x": 0.395, "y": 0.47, "width": 0.21, "height": 0.30}),
            ("DZ-CBG-BACK-001", "Back Decoration Zone", "BACK", 140, 220, ["dtf", "dtg"], {"x": 0.395, "y": 0.47, "width": 0.21, "height": 0.30}),
        ],
        "materials": [("MAT-CBG-CANVAS-001", "main_body", "Cotton canvas", "100% cotton canvas", "320")],
        "blockers": [
            ("ENG-CBG-001", "Industrial bag Patterns/templates"),
            ("ENG-CBG-002", "Production dimensions/tolerances"),
            ("ENG-CBG-003", "Validated canvas material specification"),
            ("ENG-CBG-004", "Handle load testing"),
            ("ENG-CBG-005", "Seam-strength validation"),
            ("ENG-CBG-006", "DTF/DTG process/durability testing"),
            ("ENG-CBG-007", "Production sample / workmanship approval"),
            ("ENG-CBG-008", "Production color / lot validation"),
        ],
    },
    "GP005": {
        "product_class": "headwear",
        "size_system": "one_size_accessory",
        "category": "Cap",
        "base_material": "260 GSM 100% cotton twill; synthetic Golden reference.",
        "construction_notes": "Cap Golden headwear construction; hidden/rear construction remains unresolved.",
        "qc_requirements": {"reference_only": True, "production_engineering_validated": False},
        "requires_3d_source": False,
        "colorway": ("CW-CAP-WIV-001", "Warm Ivory", ""),
        "sizes": {"ONE SIZE": ["58.0", "16.5", "18.0", "7.0", "13.0", "6.5", "3.0", "1.5"]},
        "poms": [
            ("POM-CAP-01", "Head opening circumference", None),
            ("POM-CAP-02", "Crown height front", None),
            ("POM-CAP-03", "Visor width", None),
            ("POM-CAP-04", "Visor projection", None),
            ("POM-CAP-05", "Front panel usable width", None),
            ("POM-CAP-06", "Front panel usable height", None),
            ("POM-CAP-07", "Sweatband height", None),
            ("POM-CAP-08", "Top button diameter", None),
        ],
        "zones": [
            ("DZ-CAP-FRONT-001", "Front Center Embroidery Zone", "FRONT", 110, 55, ["embroidery"], {"x": 0.35, "y": 0.38, "width": 0.30, "height": 0.12}),
        ],
        "materials": [("MAT-CAP-TWILL-001", "main_body", "Cotton twill", "100% cotton twill", "260")],
        "blockers": [
            ("ENG-CAP-001", "Industrial cap pattern/templates"),
            ("ENG-CAP-002", "Production dimensions/tolerances"),
            ("ENG-CAP-003", "Validated twill material specification"),
            ("ENG-CAP-004", "Rear closure / hidden construction validation"),
            ("ENG-CAP-005", "Fit/sample approval"),
            ("ENG-CAP-006", "Production color / lot validation"),
            ("ENG-CAP-007", "Embroidery digitization / machine setup validation"),
            ("ENG-CAP-008", "Embroidery durability / production sample validation"),
        ],
    },
}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _scan_contract_hashes(inner_zip_bytes):
    found = set()
    with zipfile.ZipFile(io.BytesIO(inner_zip_bytes), "r") as inner:
        bad = inner.testzip()
        if bad:
            raise ValidationError(f"Golden inner package CRC failure: {bad}")
        for member in inner.infolist():
            if member.is_dir():
                continue
            digest = _sha256(inner.read(member))
            if digest in {MACHINE_CONTRACT_SHA256, IMAGE_ROLE_CONTRACT_SHA256}:
                found.add(digest)
    return found


def verify_golden_package_source(source_path):
    """Directly verify actual canonical Golden inner ZIP bytes without rewriting them."""
    path = Path(source_path)
    if not path.exists():
        raise ValidationError("Golden package source path does not exist.")

    blobs = {}
    transport_entries = []
    if path.is_dir():
        for child in path.iterdir():
            if child.is_file() and child.suffix.lower() == ".zip":
                transport_entries.append(child.name)
                blobs[child.name] = child.read_bytes()
    else:
        if path.suffix.lower() != ".zip":
            raise ValidationError("Golden package source must be the outer transport ZIP or a directory containing canonical inner ZIPs.")
        with zipfile.ZipFile(path, "r") as outer:
            bad = outer.testzip()
            if bad:
                raise ValidationError(f"Golden outer bundle CRC failure: {bad}")
            for member in outer.infolist():
                if member.is_dir():
                    continue
                name = Path(member.filename).name
                if name.lower().endswith(".zip"):
                    transport_entries.append(name)
                    blobs[name] = outer.read(member)

    expected_names = {row["filename"] for row in EXPECTED_PRODUCTS.values()}
    actual_names = set(transport_entries)
    if actual_names != expected_names:
        raise ValidationError({"package_source": f"Expected exactly canonical Golden product ZIPs {sorted(expected_names)}; found {sorted(actual_names)}."})
    if any("review_r" in name.lower() or "gp006" in name.lower() for name in actual_names):
        raise ValidationError("Review packages or GP006 must not be substituted for frozen Golden v1.0 packages.")

    contract_hashes = set()
    products = {}
    for product_ref, expected in EXPECTED_PRODUCTS.items():
        blob = blobs[expected["filename"]]
        digest = _sha256(blob)
        if digest != expected["sha256"]:
            raise ValidationError({product_ref: f"Golden package SHA-256 mismatch: expected {expected['sha256']}, got {digest}."})
        with zipfile.ZipFile(io.BytesIO(blob), "r") as inner:
            bad = inner.testzip()
            if bad:
                raise ValidationError({product_ref: f"Golden package CRC failure: {bad}"})
        contract_hashes |= _scan_contract_hashes(blob)
        products[product_ref] = {"filename": expected["filename"], "sha256": digest, "verified_directly": True}

    return {
        "verified_directly": True,
        "product_count": len(products),
        "products": products,
        "gp006_present": False,
        "machine_contract_verified_directly": MACHINE_CONTRACT_SHA256 in contract_hashes,
        "image_role_contract_verified_directly": IMAGE_ROLE_CONTRACT_SHA256 in contract_hashes,
    }


def _assert_seed_guard():
    if os.environ.get("FABINZI_ALLOW_REFERENCE_DEMO_SEED") != "1":
        raise ValidationError("Reference demo seeding is disabled. Set FABINZI_ALLOW_REFERENCE_DEMO_SEED=1 explicitly in a controlled non-production environment.")


def _ensure_exact(model, lookup, defaults):
    obj, created = model.objects.get_or_create(**lookup, defaults=defaults)
    if not created:
        for field, expected in defaults.items():
            actual = getattr(obj, f"{field}_id", None) if field.endswith("_id") is False and hasattr(expected, "pk") else getattr(obj, field)
            if hasattr(expected, "pk"):
                actual = getattr(obj, f"{field}_id")
                expected = expected.pk
            if actual != expected:
                raise ValidationError(f"Reference import conflict for {model._meta.label} {lookup}: field {field} differs from frozen fixture/source identity.")
    return obj, created


def _demo_identities():
    User = get_user_model()
    designer_user, created = User.objects.get_or_create(username="fabinzi-reference-designer", defaults={"email": "designer@reference.fabinzi.invalid"})
    if created:
        designer_user.set_unusable_password()
        designer_user.save(update_fields=["password"])
    manufacturer_user, created = User.objects.get_or_create(username="fabinzi-reference-manufacturer", defaults={"email": "manufacturer@reference.fabinzi.invalid"})
    if created:
        manufacturer_user.set_unusable_password()
        manufacturer_user.save(update_fields=["password"])
    customer_user, created = User.objects.get_or_create(username="fabinzi-reference-customer", defaults={"email": "customer@reference.fabinzi.invalid"})
    if created:
        customer_user.set_unusable_password()
        customer_user.save(update_fields=["password"])

    designer_org, created = Organization.objects.get_or_create(
        kind=Organization.Kind.DESIGNER,
        email="designer@reference.fabinzi.invalid",
        defaults={"display_name": "FABINZI Demo Studio", "verification_status": Organization.VerificationStatus.ACTIVE, "created_by": designer_user},
    )
    if not created and (designer_org.display_name != "FABINZI Demo Studio" or designer_org.created_by_id != designer_user.pk):
        raise ValidationError("Reference Designer Organization identity conflicts with an existing non-reference record.")
    DesignerProfile.objects.get_or_create(organization=designer_org, defaults={"studio_name": "FABINZI Demo Studio"})
    Membership.objects.get_or_create(organization=designer_org, user=designer_user, defaults={"role": Membership.Role.OWNER})

    manufacturer_org, created = Organization.objects.get_or_create(
        kind=Organization.Kind.MANUFACTURER,
        email="manufacturer@reference.fabinzi.invalid",
        defaults={"display_name": "FABINZI Demo Manufacturing", "verification_status": Organization.VerificationStatus.ACTIVE, "created_by": manufacturer_user},
    )
    if not created and (manufacturer_org.display_name != "FABINZI Demo Manufacturing" or manufacturer_org.created_by_id != manufacturer_user.pk):
        raise ValidationError("Reference Manufacturer Organization identity conflicts with an existing non-reference record.")
    ManufacturerProfile.objects.get_or_create(
        organization=manufacturer_org,
        defaults={"primary_contact_person": "SYNTHETIC DEMO CONTACT", "capability_summary": {"reference_demo": True, "not_factory_validation": True}},
    )
    Membership.objects.get_or_create(organization=manufacturer_org, user=manufacturer_user, defaults={"role": Membership.Role.OWNER})
    return designer_user, designer_org, manufacturer_user, manufacturer_org, customer_user


def _ensure_reference_package(dataset, product_ref):
    expected = EXPECTED_PRODUCTS[product_ref]
    lookup = {"dataset": dataset, "product_ref": product_ref}
    defaults = {
        "product_name": expected["name"],
        "canonical_filename": expected["filename"],
        "package_sha256": expected["sha256"],
        "source_design_ref": expected["design_ref"],
        "source_gdv_ref": expected["gdv_ref"],
        "status": ReferencePackage.Status.APPROVED_REFERENCE,
        "golden_reference_complete": True,
        "public_reference_allowed": True,
        "production_engineering_validated": False,
        "synthetic_reference": True,
    }
    package, created = ReferencePackage.objects.get_or_create(**lookup, defaults=defaults)
    if not created:
        for field, expected_value in defaults.items():
            if getattr(package, field) != expected_value:
                raise ValidationError(f"Frozen Golden provenance conflict for {product_ref}: {field} does not match expected source identity/state.")
    return package


def _seed_product(*, dataset, product_ref, designer_org, actor, direct_binary_verified):
    expected = EXPECTED_PRODUCTS[product_ref]
    fixture = GOLDEN_SCHEMA_FIXTURES[product_ref]
    package = _ensure_reference_package(dataset, product_ref)

    design, created = GarmentDesign.objects.get_or_create(
        symbolic_ref=expected["design_ref"],
        defaults={
            "organization": designer_org,
            "title": expected["name"],
            "description": REFERENCE_NOTICE,
            "category": fixture["category"],
            "status": GarmentDesign.Status.DRAFT,
            "created_by": actor,
        },
    )
    if not created and design.organization_id != designer_org.pk:
        raise ValidationError(f"Golden Design symbolic reference {expected['design_ref']} is already owned by a different Organization.")
    version, created = GarmentDesignVersion.objects.get_or_create(
        symbolic_ref=expected["gdv_ref"],
        defaults={
            "design": design,
            "version_number": 1,
            "status": GarmentDesignVersion.Status.DRAFT,
            "summary": REFERENCE_NOTICE,
            "base_material": fixture["base_material"],
            "construction_notes": fixture["construction_notes"],
            "technical_specs": {"reference_only": True, "source_package_sha256": expected["sha256"]},
            "product_class": fixture["product_class"],
            "size_system": fixture["size_system"],
            "decoration_applicability": GarmentDesignVersion.DecorationApplicability.NOT_APPLICABLE if fixture.get("decoration_not_applicable") else GarmentDesignVersion.DecorationApplicability.CONFIGURED,
            "requires_3d_source": fixture["requires_3d_source"],
            "technical_policy": {"reference_only": True, "not_for_production": True, "direct_binary_verified_at_import": bool(direct_binary_verified)},
            "qc_requirements": fixture["qc_requirements"],
            "production_engineering_validated": False,
            "production_engineering_notes": "Golden reference only; production engineering validation is intentionally false.",
            "created_by": actor,
        },
    )
    if not created and (version.design_id != design.pk or version.version_number != 1):
        raise ValidationError(f"Golden GDV symbolic reference {expected['gdv_ref']} conflicts with an existing version.")

    color_ref, color_name, hex_color = fixture["colorway"]
    DesignColorway.objects.get_or_create(version=version, symbolic_ref=color_ref, defaults={"name": color_name, "hex_color": hex_color})

    size_rows = {}
    for order, (size_label, values) in enumerate(fixture.get("sizes", {}).items()):
        size_rows[size_label], _ = SizeChartRow.objects.get_or_create(version=version, size_label=size_label, defaults={"measurements": {}, "sort_order": order})

    points = []
    for order, (ref, name, tolerance) in enumerate(fixture.get("poms", [])):
        point, _ = DesignPointOfMeasure.objects.get_or_create(
            version=version,
            symbolic_ref=ref,
            defaults={"name": name, "unit": DesignPointOfMeasure.Unit.CM, "tolerance_plus": tolerance, "tolerance_minus": tolerance, "required": True, "sort_order": order},
        )
        points.append(point)
    for size_label, values in fixture.get("sizes", {}).items():
        row = size_rows[size_label]
        for point, value in zip(points, values):
            DesignPOMValue.objects.get_or_create(point=point, size=row, defaults={"value": value})

    for order, row in enumerate(fixture.get("materials", [])):
        ref, role, name, composition, gsm = row
        DesignMaterial.objects.get_or_create(version=version, symbolic_ref=ref, defaults={"role": role, "name": name, "composition": composition, "gsm": gsm, "specifications": {"reference_only": True}, "sort_order": order})

    for ref, name, surface, width, height, methods, geometry in fixture.get("zones", []):
        DecorationZone.objects.get_or_create(
            symbolic_ref=ref,
            defaults={
                "version": version,
                "name": name,
                "surface": surface,
                "method": DecorationZone.Method.EMBROIDERY if methods == ["embroidery"] else DecorationZone.Method.PRINT,
                "allowed_methods": methods,
                "placement": geometry,
                "max_width_mm": width,
                "max_height_mm": height,
                "reference_only": True,
                "notes": "Synthetic Golden reference dimension/geometry; not production engineering validation.",
            },
        )
    for code, description in fixture.get("blockers", []):
        TechnicalBlocker.objects.get_or_create(version=version, code=code, defaults={"description": description, "status": TechnicalBlocker.Status.OPEN, "reference_only": True})

    provenance, provenance_created = DesignReferenceProvenance.objects.get_or_create(
        package=package,
        defaults={
            "design": design,
            "version": version,
            "source_symbolic_ids": {
                "design_ref": expected["design_ref"],
                "gdv_ref": expected["gdv_ref"],
                "evidence_class": "direct_binary_verified_source" if direct_binary_verified else "contract_fixture_metadata_not_binary_proof",
            },
            "import_implementation_version": IMPORT_IMPLEMENTATION_VERSION,
            "imported_by": actor,
        },
    )
    if not provenance_created and (provenance.design_id != design.pk or provenance.version_id != version.pk):
        raise ValidationError(f"Immutable Golden provenance conflict for {product_ref}.")
    return package, design, version


@transaction.atomic
def seed_fabinzi_reference_demo(*, source_path=None, contract_fixture=False, actor=None, request=None):
    _assert_seed_guard()
    if bool(source_path) == bool(contract_fixture):
        raise ValidationError("Choose exactly one reference source: a directly verifiable Golden package source path OR explicit --contract-fixture mode.")
    direct_evidence = None
    if source_path:
        direct_evidence = verify_golden_package_source(source_path)
        if not direct_evidence["verified_directly"]:
            raise ValidationError("Direct Golden binary verification did not complete.")

    designer_user, designer_org, manufacturer_user, manufacturer_org, customer_user = _demo_identities()
    actor = actor or designer_user
    dataset, created = ReferenceDataset.objects.get_or_create(
        dataset_name=DATASET_NAME,
        dataset_version=DATASET_VERSION,
        defaults={
            "machine_contract_identity": MACHINE_CONTRACT_IDENTITY,
            "machine_contract_version": MACHINE_CONTRACT_VERSION,
            "machine_contract_sha256": MACHINE_CONTRACT_SHA256,
            "image_role_contract_identity": IMAGE_ROLE_CONTRACT_IDENTITY,
            "image_role_contract_version": IMAGE_ROLE_CONTRACT_VERSION,
            "image_role_contract_sha256": IMAGE_ROLE_CONTRACT_SHA256,
            "reference_notice": REFERENCE_NOTICE,
        },
    )
    if not created:
        expected_contract = (MACHINE_CONTRACT_SHA256, IMAGE_ROLE_CONTRACT_SHA256)
        if (dataset.machine_contract_sha256, dataset.image_role_contract_sha256) != expected_contract:
            raise ValidationError("Reference Dataset frozen contract identity/hash conflict.")

    products = {}
    for product_ref in EXPECTED_PRODUCTS:
        package, design, version = _seed_product(dataset=dataset, product_ref=product_ref, designer_org=designer_org, actor=actor, direct_binary_verified=bool(direct_evidence))
        products[product_ref] = {"package_id": package.pk, "design_id": design.pk, "version_id": version.pk}

    record_audit_event(
        actor=actor,
        action="reference.golden.imported",
        instance=dataset,
        metadata={
            "dataset_version": DATASET_VERSION,
            "product_refs": sorted(products),
            "direct_binary_verified": bool(direct_evidence),
            "fixture_mode": bool(contract_fixture),
            "not_for_production": True,
        },
        request=request,
    )
    return {
        "dataset_id": dataset.pk,
        "products": products,
        "direct_binary_evidence": direct_evidence,
        "fixture_mode": bool(contract_fixture),
        "demo_designer_organization_id": designer_org.pk,
        "demo_manufacturer_organization_id": manufacturer_org.pk,
        "demo_customer_user_id": customer_user.pk,
    }
