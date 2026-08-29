import pytest
from django.urls import reverse

from apps.artwork.models import ArtworkPlacement
from apps.organizations.templatetags.manufacturer_portal import (
    manufacturer_measurement_rows,
    manufacturer_transform_rows,
)
from apps.storefront.models import CustomizationElement

from .test_manufacturer_portal_acceptance import assigned_job, manufacturer


def test_manufacturer_technical_helpers_preserve_measurements_and_normalized_coordinates():
    measurements = {
        "chest_cm": 52,
        "length_cm": 70,
        "custom_drop_mm": 147.25,
        "panel": {"unknown_depth_cm": 3.5},
    }
    en_rows = manufacturer_measurement_rows(measurements, "en")
    ar_rows = manufacturer_measurement_rows(measurements, "ar")

    assert {row["key"] for row in en_rows} == {
        "chest_cm",
        "length_cm",
        "custom_drop_mm",
        "panel.unknown_depth_cm",
    }
    assert next(row for row in en_rows if row["key"] == "chest_cm") == {
        "key": "chest_cm",
        "label": "Chest",
        "value": "52",
        "unit": "cm",
    }
    assert next(row for row in ar_rows if row["key"] == "chest_cm") == {
        "key": "chest_cm",
        "label": "الصدر",
        "value": "52",
        "unit": "سم",
    }
    unknown = next(row for row in en_rows if row["key"] == "custom_drop_mm")
    assert unknown["label"] == "Custom drop"
    assert unknown["value"] == "147.25"
    assert unknown["unit"] == "mm"
    nested_unknown = next(row for row in en_rows if row["key"] == "panel.unknown_depth_cm")
    assert nested_unknown["label"] == "Panel / Unknown depth"
    assert nested_unknown["value"] == "3.5"

    persisted_transform = {
        "x": 0.12345,
        "y": 0.38,
        "scale": 0.275,
        "rotation": -12.5,
    }
    en_transform = manufacturer_transform_rows(persisted_transform, "en")
    ar_transform = manufacturer_transform_rows(persisted_transform, "ar")
    en_values = {row["key"]: row["value"] for row in en_transform}
    ar_values = {row["key"]: row["value"] for row in ar_transform}

    assert en_values == {
        "x": "12.345%",
        "y": "38%",
        "scale": "27.5%",
        "rotation": "-12.5°",
    }
    assert ar_values == en_values
    assert next(row for row in ar_transform if row["key"] == "scale")["label"] == "المقياس"
    assert next(row for row in ar_transform if row["key"] == "rotation")["label"] == "الدوران"


@pytest.mark.django_db
def test_manufacturer_production_detail_humanizes_persisted_measurements_and_transforms_en_ar(client):
    user, org, _, _ = manufacturer("tech-present")
    production = assigned_job(org, prefix="tech-present-design")
    row = production["garment"].size_rows.get(size_label="M")
    row.measurements = {
        "chest_cm": 52,
        "length_cm": 70,
        "custom_drop_mm": 147.25,
    }
    row.save(update_fields=["measurements"])

    ArtworkPlacement.objects.create(
        product=production["product"],
        decoration_zone=production["zone"],
        production_method="print",
        transform={"x": 0.5, "y": 0.38, "scale": 0.35, "rotation": 0},
    )
    CustomizationElement.objects.create(
        customization=production["customization"],
        decoration_zone=production["zone"],
        kind=CustomizationElement.Kind.TEXT,
        text="Persisted Studio text",
        production_method="print",
        transform={"x": 0.62, "y": 0.41, "scale": 0.275, "rotation": -12.5},
    )

    client.force_login(user)
    url = reverse("manufacturer-production-detail", args=[production["job"].pk])

    en = client.get(url, {"org": org.pk, "lang": "en"})
    assert en.status_code == 200
    en_html = en.content.decode()
    assert "Chest" in en_html
    assert "Length" in en_html
    assert "Custom drop" in en_html
    assert "147.25" in en_html
    assert 'data-transform-source="designed-product"' in en_html
    assert 'data-transform-source="studio"' in en_html
    assert "50%" in en_html
    assert "38%" in en_html
    assert "35%" in en_html
    assert "62%" in en_html
    assert "41%" in en_html
    assert "27.5%" in en_html
    assert "-12.5°" in en_html
    assert "{&#x27;chest_cm&#x27;" not in en_html
    assert "{'chest_cm':" not in en_html
    assert "{&#x27;x&#x27;" not in en_html
    assert "{'x':" not in en_html

    ar = client.get(url, {"org": org.pk, "lang": "ar"})
    assert ar.status_code == 200
    ar_html = ar.content.decode()
    assert "الصدر" in ar_html
    assert "الطول" in ar_html
    assert "سم" in ar_html
    assert "Custom drop" in ar_html
    assert "147.25" in ar_html
    assert 'data-transform-source="designed-product"' in ar_html
    assert 'data-transform-source="studio"' in ar_html
    for persisted_display in ("50%", "38%", "35%", "62%", "41%", "27.5%", "-12.5°"):
        assert persisted_display in ar_html
    assert "المقياس" in ar_html
    assert "الدوران" in ar_html
    assert "{&#x27;chest_cm&#x27;" not in ar_html
    assert "{&#x27;x&#x27;" not in ar_html
