from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from apps.artwork.models import ArtworkAsset
from apps.design.models import DesignAsset
from apps.operations.models import ProductionAsset, ProductionJob, ProductionSpecification
from apps.operations.services import require_manufacturer_job_access
from apps.operations.v2_7 import verify_specification_integrity
from apps.organizations.manufacturer_context import MANUFACTURER_TECHNICAL_VIEW_ROLES
from apps.storefront.models import CustomizationElement
from .models import MediaAsset
from .services import private_media_response


def _job_for_actor(actor, job_id):
    job = get_object_or_404(
        ProductionJob.objects.select_related(
            "manufacturer",
            "order__item__store_product__designed_product__garment_version",
            "order__item__store_product__designed_product__artwork_version",
            "order__item__studio_project",
        ),
        pk=job_id,
    )
    try:
        require_manufacturer_job_access(actor, job, roles=MANUFACTURER_TECHNICAL_VIEW_ROLES)
    except PermissionDenied as exc:
        raise Http404 from exc
    return job


def _operational_spec_media(job, asset_type, pk):
    try:
        specification = job.production_specification
    except ProductionSpecification.DoesNotExist:
        return None
    if not verify_specification_integrity(specification):
        raise Http404
    if asset_type == "job":
        record = get_object_or_404(
            ProductionAsset.objects.select_related("media_asset"),
            pk=pk,
            job=job,
            media_asset__access=MediaAsset.Access.PRIVATE,
        )
        return record.media_asset
    if asset_type != "spec":
        raise Http404
    allowed = {int(value) for value in (specification.authorized_media_asset_ids or [])}
    if int(pk) not in allowed:
        raise Http404
    manifest_ids = {
        int(row.get("media_asset_id"))
        for row in (specification.snapshot.get("authorized_private_media") or [])
        if isinstance(row, dict) and row.get("media_asset_id") is not None
    }
    if int(pk) not in manifest_ids:
        raise Http404
    return get_object_or_404(MediaAsset, pk=pk, access=MediaAsset.Access.PRIVATE)


def _resolve_legacy_job_media(job, asset_type, pk):
    product = job.order.item.store_product.designed_product
    if asset_type == "job":
        record = get_object_or_404(ProductionAsset.objects.select_related("media_asset"), pk=pk, job=job, media_asset__access=MediaAsset.Access.PRIVATE)
        return record.media_asset
    if asset_type == "design":
        record = get_object_or_404(
            DesignAsset.objects.select_related("media_asset"), pk=pk, version_id=product.garment_version_id,
            kind__in=[DesignAsset.Kind.PATTERN, DesignAsset.Kind.TECH_PACK, DesignAsset.Kind.THREE_D, DesignAsset.Kind.TECHNICAL],
            media_asset__access=MediaAsset.Access.PRIVATE,
        )
        return record.media_asset
    if asset_type == "artwork":
        record = get_object_or_404(ArtworkAsset.objects.select_related("media_asset"), pk=pk, version_id=product.artwork_version_id, kind=ArtworkAsset.Kind.SOURCE, media_asset__access=MediaAsset.Access.PRIVATE)
        return record.media_asset
    project_id = job.order.item.studio_project_id
    if not project_id:
        raise Http404
    if asset_type == "studio":
        element = get_object_or_404(CustomizationElement.objects.select_related("media_asset"), pk=pk, customization__project_id=project_id, kind=CustomizationElement.Kind.IMAGE, media_asset__access=MediaAsset.Access.PRIVATE)
        if not (element.media_asset.metadata or {}).get("studio_private_upload") or element.media_asset.uploaded_by_id != job.order.customer_id:
            raise Http404
        return element.media_asset
    if asset_type == "studio-artwork":
        source = get_object_or_404(ArtworkAsset.objects.select_related("media_asset", "version"), pk=pk, kind=ArtworkAsset.Kind.SOURCE, media_asset__access=MediaAsset.Access.PRIVATE)
        if not CustomizationElement.objects.filter(customization__project_id=project_id, kind=CustomizationElement.Kind.ARTWORK, artwork_version_id=source.version_id).exists():
            raise Http404
        return source.media_asset
    raise Http404


def _resolve_job_media(job, asset_type, pk):
    if ProductionSpecification.objects.filter(job=job).exists():
        return _operational_spec_media(job, asset_type, pk)
    try:
        rfq = job.order.item.manufacturing_rfq
    except Exception:
        rfq = None
    if rfq is not None and rfq.source == rfq.Source.CUSTOMER_ORDER:
        raise Http404
    # Explicit legacy Designer-sourcing compatibility path only.
    return _resolve_legacy_job_media(job, asset_type, pk)


@login_required
def manufacturer_production_media(request, job_id, asset_type, pk):
    job = _job_for_actor(request.user, job_id)
    asset = _resolve_job_media(job, asset_type, pk)
    if asset is None:
        raise Http404
    payload = private_media_response(asset)
    if isinstance(payload, str):
        response = HttpResponseRedirect(payload)
    else:
        response = FileResponse(payload, content_type=asset.mime_type)
        safe_name = asset.original_filename.replace(chr(34), "")
        response["Content-Disposition"] = f'inline; filename="{safe_name}"'
        response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "no-referrer"
    return response
