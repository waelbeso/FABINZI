from django.db.models import Prefetch

from apps.design.models import DecorationZone
from apps.storefront.models import StoreProduct, Storefront
from .models import Artwork, ArtworkAsset, ArtworkVersion


PUBLIC_METADATA_KEYS = {
    "public_suitability",
    "public_product_types",
    "public_production_methods",
    "suitable_for_print",
    "suitable_for_embroidery",
}


def public_metadata(version):
    metadata = version.metadata or {}
    return {key: metadata[key] for key in PUBLIC_METADATA_KEYS if key in metadata}


def supported_methods(version):
    metadata = public_metadata(version)
    methods = []
    explicit = metadata.get("public_production_methods")
    if isinstance(explicit, list):
        for item in explicit:
            value = str(item).strip().lower()
            if value in {DecorationZone.Method.PRINT, DecorationZone.Method.EMBROIDERY} and value not in methods:
                methods.append(value)
    if metadata.get("suitable_for_print") is True and DecorationZone.Method.PRINT not in methods:
        methods.append(DecorationZone.Method.PRINT)
    if metadata.get("suitable_for_embroidery") is True and DecorationZone.Method.EMBROIDERY not in methods:
        methods.append(DecorationZone.Method.EMBROIDERY)
    return methods


def public_suitability(version):
    metadata = public_metadata(version)
    value = metadata.get("public_suitability")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        clean = [str(item).strip() for item in value if str(item).strip()]
        return " · ".join(clean[:4])
    return ""


def public_product_types(version):
    value = public_metadata(version).get("public_product_types")
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:12]


def public_preview(version):
    previews = getattr(version, "public_previews", None)
    if previews is None:
        previews = version.assets.filter(
            kind=ArtworkAsset.Kind.PREVIEW,
            media_asset__access="public",
            media_asset__mime_type__startswith="image/",
        ).select_related("media_asset")
    return previews[0] if previews else None


def public_artwork_queryset():
    preview_assets = ArtworkAsset.objects.filter(
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset__access="public",
        media_asset__mime_type__startswith="image/",
    ).select_related("media_asset")
    approved_versions = ArtworkVersion.objects.filter(
        status=ArtworkVersion.Status.APPROVED,
    ).prefetch_related(Prefetch("assets", queryset=preview_assets, to_attr="public_previews")).order_by("-version_number")
    return (
        Artwork.objects.filter(status=Artwork.Status.APPROVED)
        .select_related("organization")
        .prefetch_related(Prefetch("versions", queryset=approved_versions, to_attr="public_versions"))
    )


def decorate_public_artwork(artwork):
    versions = getattr(artwork, "public_versions", [])
    version = versions[0] if versions else None
    artwork.public_version = version
    artwork.public_preview = public_preview(version) if version else None
    artwork.public_methods = supported_methods(version) if version else []
    artwork.public_suitability = public_suitability(version) if version else ""
    artwork.public_product_types = public_product_types(version) if version else []
    return artwork


def decorate_public_artworks(rows):
    return [decorate_public_artwork(row) for row in rows if getattr(row, "public_versions", None)]


def eligible_products_for_version(version, limit=8):
    methods = set(supported_methods(version))
    if not methods:
        return []
    products = (
        StoreProduct.objects.filter(
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
            customization_enabled=True,
        )
        .select_related(
            "storefront",
            "designed_product__garment_version__design",
        )
        .prefetch_related(
            "images__media_asset",
            "variants",
            "designed_product__garment_version__decoration_zones",
        )
        .order_by("-featured", "-published_at", "-updated_at")
    )
    product_types = set(public_product_types(version))
    eligible = []
    for product in products:
        category = (product.designed_product.garment_version.design.category or "").strip()
        if product_types and category not in product_types:
            continue
        zones = product.designed_product.garment_version.decoration_zones.all()
        if any(zone.method == DecorationZone.Method.BOTH or zone.method in methods for zone in zones):
            eligible.append(product)
        if len(eligible) >= limit:
            break
    return eligible


def version_eligible_for_zone(version, zone, production_method=None):
    methods = set(supported_methods(version))
    if production_method:
        return production_method in methods and zone.method in {DecorationZone.Method.BOTH, production_method}
    return any(zone.method in {DecorationZone.Method.BOTH, method} for method in methods)
