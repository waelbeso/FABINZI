import hashlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_ICON = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="1024" height="1024" role="img" aria-label="FABINZI icon">
  <defs>
    <linearGradient id="g" x1="8" y1="6" x2="56" y2="58" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#7C5CFF"/>
      <stop offset="1" stop-color="#5A36E6"/>
    </linearGradient>
  </defs>
  <rect x="3" y="3" width="58" height="58" rx="16" fill="#111827"/>
  <path d="M18 16h29v9H29v8h15v9H29v14H18V16Z" fill="url(#g)"/>
  <path d="M46.5 12.5 53 19l-3.2 3.2-6.5-6.5 3.2-3.2Z" fill="#21D3AE"/>
  <circle cx="48" cy="45" r="2.3" fill="#21D3AE"/>
  <circle cx="53" cy="49" r="2" fill="#21D3AE" opacity=".82"/>
  <circle cx="56" cy="54" r="1.7" fill="#21D3AE" opacity=".62"/>
</svg>
'''

CANONICAL_LOGO = '''<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 3150 1000"
     width="3150" height="1000"
     role="img" aria-label="FABINZI">
  <defs>
    <linearGradient id="g" x1="125" y1="94" x2="875" y2="906" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#7C5CFF"/>
      <stop offset="1" stop-color="#5A36E6"/>
    </linearGradient>
  </defs>

  <!-- Approved FABINZI icon, scaled exactly from the GitHub 64x64 source -->
  <g transform="scale(15.625)">
    <rect x="3" y="3" width="58" height="58" rx="16" fill="#111827"/>
    <path d="M18 16h29v9H29v8h15v9H29v14H18V16Z" fill="url(#g)"/>
    <path d="M46.5 12.5 53 19l-3.2 3.2-6.5-6.5 3.2-3.2Z" fill="#21D3AE"/>
    <circle cx="48" cy="45" r="2.3" fill="#21D3AE"/>
    <circle cx="53" cy="49" r="2" fill="#21D3AE" opacity=".82"/>
    <circle cx="56" cy="54" r="1.7" fill="#21D3AE" opacity=".62"/>
  </g>

  <!-- Live-site wordmark styling -->
  <text x="1289" y="500"
        dominant-baseline="middle"
        font-family="Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
        font-size="421"
        font-weight="900"
        letter-spacing="8.42"
        fill="#111827">FABINZI</text>
</svg>
'''

PALETTE = ("#111827", "#7C5CFF", "#5A36E6", "#21D3AE")


def test_canonical_brand_master_files_are_exact_owner_authorized_payloads():
    logo = (ROOT / "static/brand/fabinzi-logo.svg").read_text(encoding="utf-8")
    icon = (ROOT / "static/brand/fabinzi-icon.svg").read_text(encoding="utf-8")

    assert logo == CANONICAL_LOGO
    assert icon == CANONICAL_ICON
    assert hashlib.sha256(logo.encode()).hexdigest() == "27fd3226825c47717b0899cbdb76bdaf9c38a0d7fea2e88257c8db8bf71b4e1b"
    assert hashlib.sha256(icon.encode()).hexdigest() == "6d5732cfd6014fcb0fa6029241e87d793814ce430934cd632be82289d6219b61"


def test_canonical_brand_palette_is_preserved_in_both_masters():
    for color in PALETTE:
        assert color in CANONICAL_LOGO
        assert color in CANONICAL_ICON


def test_existing_on_dark_logo_is_the_approved_transparent_contrast_asset():
    dark = (ROOT / "static/brand/fabinzi-logo-on-dark.svg").read_text(encoding="utf-8")
    assert 'viewBox="0 0 3260 1000"' in dark
    assert 'fill="#F6F6FB">FABINZI</text>' in dark
    assert "Approved FABINZI mark; only wordmark contrast adapts for dark surfaces." in dark
    assert "<rect" in dark and "#111827" in dark
    assert "background" not in dark.lower()


def test_v2_public_shell_uses_theme_specific_approved_logos_without_white_plate_or_filters():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    public_css = (ROOT / "static/css/public-site.css").read_text(encoding="utf-8")
    shell_css = (ROOT / "static/css/v2-public-shell.css").read_text(encoding="utf-8")
    css = public_css + shell_css

    assert base.count("{% static 'brand/fabinzi-logo.svg' %}") >= 2
    assert base.count("{% static 'brand/fabinzi-logo-on-dark.svg' %}") >= 2
    assert "{% static 'brand/fabinzi-icon.svg' %}" in base
    assert 'type="image/svg+xml"' in base
    assert "{% url 'favicon' %}" not in base
    assert "brand-master-surface" not in base
    assert ".brand-master-surface" not in shell_css
    assert "brand-logo-pair" in base
    assert '[data-theme="dark"] .brand-logo--light{display:none}' in public_css
    assert '[data-theme="dark"] .brand-logo--dark{display:block}' in public_css
    assert '[data-theme="system"] .brand-logo--dark{display:block}' in public_css
    assert "height:auto" in shell_css
    assert "filter:" not in css
    assert "invert(" not in css


def test_public_header_keeps_core_navigation_and_removes_directory_links_only_from_header():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    header = base.split("</header>", 1)[0]
    footer = base.split("<footer", 1)[1]

    assert "{% url 'home' %}" in header
    assert "{% url 'discover' %}" in header
    assert "{% url 'how-it-works' %}" in header
    assert "{% url 'artwork' %}" not in header
    assert "{% url 'designer-directory' %}" not in header
    assert "{% url 'manufacturer-marketplace' %}" not in header
    assert "{% url 'artwork' %}" in footer
    assert "{% url 'designer-directory' %}" in footer
    assert "{% url 'manufacturer-marketplace' %}" in footer


@pytest.mark.django_db
def test_web_app_manifest_uses_exact_canonical_svg_icon(client):
    response = client.get("/site.webmanifest")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/manifest+json")
    assert {
        "src": "/static/brand/fabinzi-icon.svg",
        "sizes": "any",
        "type": "image/svg+xml",
    } in response.json()["icons"]


@pytest.mark.django_db
def test_public_shell_schema_logo_identity_uses_approved_light_and_dark_assets(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "/static/brand/fabinzi-logo.svg" in body
    assert "/static/brand/fabinzi-logo-on-dark.svg" in body
    assert "/static/brand/fabinzi-icon.svg" in body


def test_generated_raster_assets_are_explicitly_legacy_noncanonical_compatibility():
    generated = (ROOT / "apps/platform_ops/brand_assets.py").read_text(encoding="utf-8")
    views = (ROOT / "apps/platform_ops/views.py").read_text(encoding="utf-8")

    assert "Legacy raster compatibility derivatives only" in generated
    assert "Nothing generated by this module is evidence of canonical master equivalence" in generated
    assert "Legacy raster compatibility endpoints only" in views
    assert 'static("brand/fabinzi-icon.svg")' in views
