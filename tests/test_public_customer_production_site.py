import json
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from PIL import Image

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.platform_ops.views import handler403, handler500
from apps.storefront.models import ProductVariant, StoreProduct, StoreProductImage, Storefront

User = get_user_model()


def _published_product(prefix="seo"):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=f"{prefix} Brand",
        email=f"{prefix}@brand.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    garment = GarmentDesign.objects.create(organization=org, title=f"{prefix} Garment", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment_version = GarmentDesignVersion.objects.create(design=garment, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    artwork = Artwork.objects.create(organization=org, title=f"{prefix} Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment_version, artwork_version=artwork_version, title=f"{prefix} Designed", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = Storefront.objects.create(organization=org, slug=f"{prefix}-store", status=Storefront.Status.PUBLISHED, name_en=f"{prefix} Store", name_ar=f"متجر {prefix}")
    product = StoreProduct.objects.create(
        storefront=store,
        designed_product=designed,
        slug=f"{prefix}-product",
        status=StoreProduct.Status.PUBLISHED,
        title_en=f"{prefix} Product",
        title_ar=f"منتج {prefix}",
        description_en="Published product used for metadata acceptance.",
        description_ar="منتج منشور لاختبار بيانات المشاركة.",
        base_price="725.00",
        currency="EGP",
    )
    ProductVariant.objects.create(product=product, sku=f"{prefix.upper()}-M", size="M", color_name="Black", color_hex="#111111", stock_quantity=3)
    image = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="/static/brand/fabinzi-logo.svg",
        original_filename=f"{prefix}.svg",
        mime_type="image/svg+xml",
        size_bytes=1,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
    )
    StoreProductImage.objects.create(product=product, media_asset=image, alt_en=product.title_en, alt_ar=product.title_ar)
    return product


@pytest.mark.django_db
def test_store_is_primary_public_home_and_discover_preserves_bilingual_aeo(client):
    store = client.get("/")
    assert store.status_code == 200
    store_body = store.content.decode()
    assert "Designer products, one real catalog" in store_body
    assert '<meta name="robots" content="index,follow' in store_body
    assert '<link rel="canonical" href="http://localhost:8000/?lang=en">' in store_body
    assert 'href="/discover/">Discover</a>' in store_body
    assert 'href="/how-it-works/">How it works</a>' in store_body
    assert 'href="/designers/">Designers</a>' in store_body

    discover = client.get("/discover/")
    assert discover.status_code == 200
    body = discover.content.decode()
    assert '<meta name="robots" content="index,follow' in body
    assert '<link rel="canonical" href="http://localhost:8000/discover/?lang=en">' in body
    assert 'hreflang="ar"' in body
    assert 'property="og:image" content="http://localhost:8000/share/fabinzi-1200x630.png"' in body
    assert 'name="twitter:card" content="summary_large_image"' in body
    assert '"@type":"FAQPage"' in body
    assert 'site.webmanifest' in body
    assert 'apple-touch-icon.png' in body

    ar = client.get("/discover/?lang=ar")
    assert ar.status_code == 200
    ar_body = ar.content.decode()
    assert '<html lang="ar" dir="rtl"' in ar_body
    assert 'الفكرة تبدأ عند المصمم' in ar_body
    assert '"inLanguage":"ar"' in ar_body
    assert 'http://localhost:8000/discover/?lang=ar' in ar_body


@pytest.mark.django_db
def test_filtered_root_catalog_is_crawl_safe_and_legacy_store_redirects(client):
    clean = client.get("/")
    assert clean.status_code == 200
    assert '<meta name="robots" content="index,follow' in clean.content.decode()

    legacy = client.get("/store/?q=shirt&sort=price_asc")
    assert legacy.status_code == 301
    assert legacy.headers["Location"].endswith("/?q=shirt&sort=price_asc")

    filtered = client.get("/?q=shirt&sort=price_asc")
    assert filtered.status_code == 200
    body = filtered.content.decode()
    assert '<meta name="robots" content="noindex,follow">' in body
    assert 'name="q" value="shirt"' in body


@pytest.mark.django_db
def test_product_has_dynamic_bilingual_product_metadata(client):
    product = _published_product()
    url = f"/store/{product.storefront.slug}/{product.slug}/"
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert f'<meta property="og:title" content="{product.title_en} | FABINZI">' in body
    assert '<meta property="og:type" content="product">' in body
    assert 'http://localhost:8000/static/brand/fabinzi-logo.svg' in body
    assert '"@type":"Product"' in body
    assert '"priceCurrency":"EGP"' in body
    assert 'https://schema.org/InStock' in body

    ar = client.get(url + "?lang=ar")
    assert ar.status_code == 200
    assert f'<meta property="og:title" content="{product.title_ar} | FABINZI">' in ar.content.decode()


@pytest.mark.django_db
def test_private_customer_surfaces_are_noindex(client):
    customer = User.objects.create_user(username="private-customer", password="password12345")
    client.force_login(customer)
    response = client.get("/app/")
    assert response.status_code == 200
    body = response.content.decode()
    assert '<meta name="robots" content="noindex,nofollow,noarchive">' in body
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert "Live products to explore" in body


@pytest.mark.django_db
def test_brand_identity_endpoints_are_real_binary_assets(client):
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["Content-Type"].startswith("image/x-icon")
    assert bytes(favicon.content[:4]) == b"\x00\x00\x01\x00"

    for path, size in (("/apple-touch-icon.png", (180, 180)), ("/icon-192.png", (192, 192)), ("/icon-512.png", (512, 512)), ("/share/fabinzi-1200x630.png", (1200, 630))):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("image/png")
        image = Image.open(BytesIO(response.content))
        assert image.size == size

    manifest = client.get("/site.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["Content-Type"].startswith("application/manifest+json")
    payload = json.loads(manifest.content)
    icons = payload["icons"]
    assert {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"} in icons
    assert {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"} in icons
    assert {
        "src": "/static/brand/fabinzi-icon.svg",
        "sizes": "any",
        "type": "image/svg+xml",
    } in icons


@pytest.mark.django_db
def test_robots_and_sitemap_enforce_public_private_boundary(client):
    product = _published_product("crawl")
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    text = robots.content.decode()
    assert "Disallow: /cart/" in text
    assert "Disallow: /api/" in text
    assert "Sitemap: http://localhost:8000/sitemap.xml" in text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    xml = sitemap.content.decode()
    assert "/store/crawl-store/crawl-product/" in xml
    assert "hreflang=\"ar\"" in xml
    assert "/cart/" not in xml
    assert "/purchases/" not in xml


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_branded_404_page_is_rendered_in_production_mode(client):
    response = client.get("/this-route-does-not-exist/")
    assert response.status_code == 404
    body = response.content.decode()
    assert "FABINZI" in body
    assert "404" in body


@pytest.mark.django_db
def test_branded_403_and_500_handlers_render_without_domain_mutation():
    factory = RequestFactory()
    request = factory.get("/protected/")
    request.user = AnonymousUser()
    forbidden = handler403(request)
    assert forbidden.status_code == 403
    assert b"FABINZI" in forbidden.content
    assert b"403" in forbidden.content

    error_request = factory.get("/failed/")
    error_request.user = AnonymousUser()
    failed = handler500(error_request)
    assert failed.status_code == 500
    assert b"FABINZI" in failed.content
    assert b"500" in failed.content