from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    DesignMaterial,
    DesignPOMValue,
    DesignPatternRequirement,
    DesignPointOfMeasure,
    GarmentDesignVersion,
    SizeChartRow,
    TechnicalBlocker,
)


# Direct semantic evidence from the supplied frozen GP003 Human Tech Pack.
# This intentionally does NOT claim that the canonical GP003 ZIP bytes were
# inspected. The package hash/byte gate remains separate in golden_reference.py.
GP003_SIZES = {
    "XS": ["43.0", "35.0", "115.0", "35.0", "8.5", "16.0", "108.0", "27.0", "8.5", "2.3"],
    "S": ["45.5", "37.5", "116.0", "36.0", "9.0", "16.5", "110.0", "27.5", "8.7", "2.5"],
    "M": ["48.0", "40.0", "117.0", "37.0", "9.5", "17.0", "112.0", "28.0", "8.9", "2.7"],
    "L": ["50.5", "42.5", "118.0", "38.0", "10.0", "17.5", "114.0", "28.5", "9.1", "2.9"],
    "XL": ["53.0", "45.0", "119.0", "39.0", "10.5", "18.0", "116.0", "29.0", "9.3", "3.1"],
}

GP003_POMS = [
    ("POM-DDR-01", "Half chest / bust", "1.0"),
    ("POM-DDR-02", "Half waist", "1.0"),
    ("POM-DDR-03", "Body length HPS", "1.5"),
    ("POM-DDR-04", "Shoulder width", "0.8"),
    ("POM-DDR-05", "Sleeve length", "0.6"),
    ("POM-DDR-06", "Sleeve opening half", "0.6"),
    ("POM-DDR-07", "Bottom opening half", "1.5"),
    ("POM-DDR-08", "Neck width", "0.5"),
    ("POM-DDR-09", "Front neck drop", "0.5"),
    ("POM-DDR-10", "Back neck drop", "0.4"),
]

GP003_MATERIALS = [
    ("MAT-DDR-SHELL-001", "main_shell", "Woven crepe shell", "100% polyester", "150"),
    ("MAT-DDR-LINING-001", "lining", "Lightweight woven lining", "100% polyester", "75"),
    ("MAT-DDR-INT-001", "interfacing", "Fusible interfacing", "Polyester fusible", "40"),
]

GP003_BLOCKERS = [
    ("ENG-DDR-001", "Validated industrial dress pattern source missing"),
    ("ENG-DDR-002", "Validated dress grading missing"),
    ("ENG-DDR-003", "Material composition/GSM/behavior not factory validated"),
    ("ENG-DDR-004", "Fit sample / wear approval missing"),
    ("ENG-DDR-005", "Production measurements and tolerances not approved"),
    ("ENG-DDR-006", "Production color standard / lab dip missing"),
    ("ENG-DDR-007", "Zipper, tie and construction engineering not validated"),
    ("ENG-DDR-008", "Genuine apparel 3D source missing"),
]


def _require_reference_version(gdv_ref):
    try:
        version = GarmentDesignVersion.objects.select_related(
            "design", "reference_provenance__package"
        ).get(symbolic_ref=gdv_ref)
    except GarmentDesignVersion.DoesNotExist as exc:
        raise ValidationError(f"Reference GDV {gdv_ref} must be seeded before enrichment.") from exc
    provenance = getattr(version, "reference_provenance", None)
    if not provenance or provenance.package.product_ref not in {"GP001", "GP002", "GP003", "GP004", "GP005"}:
        raise ValidationError("Reference enrichment may only operate on immutable Golden provenance records.")
    return version


def _ensure_pattern_slots(version):
    for size in version.size_rows.all():
        DesignPatternRequirement.objects.get_or_create(
            version=version,
            size=size,
            defaults={
                "required": True,
                "declared_scale_1_to_1": False,
                "pattern_asset": None,
                "notes": "Genuine engineering source missing; no fake production Pattern/DXF is created by the reference importer.",
            },
        )


@transaction.atomic
def enrich_source_supported_reference_mapping():
    """Complete source-supported schema mapping without fabricating missing binaries.

    The five canonical Golden package identities are created by the base importer.
    This enrichment adds the normalized pattern slots required by the Creator
    technical schema and fills GP003's directly inspected Human Tech Pack sizing,
    POM/material/blocker semantics. It is deterministic and idempotent.
    """
    versions = {
        ref: _require_reference_version(ref)
        for ref in (
            "GDV-MTS-001-V1",
            "GDV-WTS-001-V1",
            "GDV-DDR-001-V1",
            "GDV-CBG-001-V1",
            "GDV-CAP-001-V1",
        )
    }

    gp003 = versions["GDV-DDR-001-V1"]
    colorway = gp003.colorways.filter(symbolic_ref="CW-DDR-BIV-001").first()
    if colorway and not colorway.hex_color:
        colorway.hex_color = "#E0CAC1"
        colorway.save(update_fields=["hex_color"])

    size_rows = {}
    for order, (label, values) in enumerate(GP003_SIZES.items()):
        row, created = SizeChartRow.objects.get_or_create(
            version=gp003,
            size_label=label,
            defaults={"measurements": {}, "sort_order": order},
        )
        if not created and row.sort_order != order:
            row.sort_order = order
            row.save(update_fields=["sort_order"])
        size_rows[label] = row

    points = []
    for order, (symbolic_ref, name, tolerance) in enumerate(GP003_POMS):
        point, _ = DesignPointOfMeasure.objects.get_or_create(
            version=gp003,
            symbolic_ref=symbolic_ref,
            defaults={
                "name": name,
                "unit": DesignPointOfMeasure.Unit.CM,
                "tolerance_plus": tolerance,
                "tolerance_minus": tolerance,
                "required": True,
                "sort_order": order,
            },
        )
        points.append(point)

    for label, values in GP003_SIZES.items():
        for point, value in zip(points, values):
            DesignPOMValue.objects.get_or_create(
                point=point,
                size=size_rows[label],
                defaults={"value": value},
            )

    for order, (ref, role, name, composition, gsm) in enumerate(GP003_MATERIALS):
        DesignMaterial.objects.get_or_create(
            version=gp003,
            symbolic_ref=ref,
            defaults={
                "role": role,
                "name": name,
                "composition": composition,
                "gsm": gsm,
                "specifications": {
                    "reference_only": True,
                    "source_evidence": "supplied_frozen_gp003_human_tech_pack",
                    "production_validated": False,
                },
                "sort_order": order,
            },
        )

    # Replace the coarse bootstrap placeholder with the eight explicit blockers
    # directly supported by the supplied frozen GP003 Human Tech Pack.
    gp003.technical_blockers.filter(code="ENG-DDR-REFERENCE").delete()
    for code, description in GP003_BLOCKERS:
        TechnicalBlocker.objects.get_or_create(
            version=gp003,
            code=code,
            defaults={
                "description": description,
                "status": TechnicalBlocker.Status.OPEN,
                "reference_only": True,
            },
        )

    policy = dict(gp003.technical_policy or {})
    policy.update(
        {
            "reference_only": True,
            "not_for_production": True,
            "gp003_human_tech_pack_semantics_inspected": True,
            "gp003_package_bytes_verified": False,
            "source_semantic_evidence": "FABINZI_GRD_DDR_001_Tech_Pack_v1.0",
        }
    )
    gp003.technical_policy = policy
    gp003.save(update_fields=["technical_policy"])

    for version in versions.values():
        _ensure_pattern_slots(version)

    return {
        "version_refs": sorted(versions),
        "gp003_sizes": list(GP003_SIZES),
        "gp003_pom_count": len(GP003_POMS),
        "gp003_blocker_count": len(GP003_BLOCKERS),
        "package_binary_verification_claimed": False,
    }
