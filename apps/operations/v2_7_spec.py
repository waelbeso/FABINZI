import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.artwork.models import ArtworkAsset
from apps.audit.services import record_audit_event
from apps.checkout.models import CartItem, OrderItem
from apps.design.models import DesignAsset, GarmentDesignVersion
from apps.design.services import evaluate_version_eligibility
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ
from apps.storefront.models import CustomizationElement
from .models import ProductionJob, ProductionSpecification
from .v2_7_routing import _require_staff, _verified_rows, manufacturer_operationally_eligible, required_canonical_capabilities


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def snapshot_sha256(snapshot):
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()

def _media_row(media, *, source, source_id, role=""):
    return {
        "media_asset_id": media.pk,
        "source": source,
        "source_id": source_id,
        "role": role,
        "filename": media.original_filename,
        "mime_type": media.mime_type,
        "size_bytes": media.size_bytes,
        "checksum_sha256": media.checksum_sha256,
    }


def build_production_specification_snapshot(*, order_item, manufacturer, quote, verification_rows):
    product = order_item.store_product
    designed = product.designed_product
    version = designed.garment_version
    purchase = order_item.order.purchase
    media_manifest = []

    size_row = version.size_rows.filter(size_label=order_item.size).first() if order_item.size else None
    measurements = dict(size_row.measurements or {}) if size_row else {}
    pom = []
    if size_row:
        for value in size_row.pom_values.select_related("point").order_by("point__sort_order", "point_id"):
            pom.append({
                "symbolic_ref": value.point.symbolic_ref,
                "name": value.point.name,
                "unit": value.point.unit,
                "value": str(value.value),
                "tolerance_plus": str(value.point.tolerance_plus) if value.point.tolerance_plus is not None else None,
                "tolerance_minus": str(value.point.tolerance_minus) if value.point.tolerance_minus is not None else None,
            })

    patterns = []
    if size_row:
        for requirement in version.pattern_requirements.filter(size=size_row, required=True).select_related("pattern_asset__media_asset"):
            asset = requirement.pattern_asset
            patterns.append({
                "requirement_id": requirement.pk,
                "declared_scale_1_to_1": requirement.declared_scale_1_to_1,
                "design_asset_id": asset.pk if asset else None,
                "media_asset_id": asset.media_asset_id if asset else None,
            })
            if asset and asset.media_asset.access == asset.media_asset.Access.PRIVATE:
                media_manifest.append(_media_row(asset.media_asset, source="design_pattern", source_id=asset.pk, role=asset.technical_role))

    technical_assets = []
    for asset in version.assets.filter(kind__in=[DesignAsset.Kind.TECH_PACK, DesignAsset.Kind.THREE_D, DesignAsset.Kind.TECHNICAL], media_asset__access="private").select_related("media_asset").order_by("id"):
        technical_assets.append({"design_asset_id": asset.pk, "kind": asset.kind, "technical_role": asset.technical_role, "media_asset_id": asset.media_asset_id})
        media_manifest.append(_media_row(asset.media_asset, source="design", source_id=asset.pk, role=asset.technical_role))

    materials = [{
        "symbolic_ref": row.symbolic_ref, "role": row.role, "name": row.name,
        "composition": row.composition, "gsm": str(row.gsm) if row.gsm is not None else None,
        "specifications": row.specifications,
    } for row in version.materials.order_by("sort_order", "id")]

    ready_evidence = None
    if order_item.purchase_kind == CartItem.Kind.READY_DESIGNED:
        artwork = designed.artwork_version
        sources = []
        for source in artwork.assets.filter(kind=ArtworkAsset.Kind.SOURCE, media_asset__access="private").select_related("media_asset").order_by("id"):
            sources.append({"artwork_asset_id": source.pk, "media_asset_id": source.media_asset_id, "technical_role": source.technical_role})
            media_manifest.append(_media_row(source.media_asset, source="artwork", source_id=source.pk, role=source.technical_role))
        ready_evidence = {
            "artwork_id": artwork.artwork_id,
            "artwork_version_id": artwork.pk,
            "artwork_symbolic_ref": artwork.symbolic_ref,
            "placements": list((order_item.production_snapshot or {}).get("placements", [])),
            "source_assets": sources,
        }

    studio_evidence = None
    if order_item.purchase_kind == CartItem.Kind.STUDIO:
        studio_evidence = dict(order_item.customization_snapshot or (order_item.production_snapshot or {}).get("customization") or {})
        if order_item.studio_project_id:
            for element in CustomizationElement.objects.filter(customization__project_id=order_item.studio_project_id).select_related("media_asset", "artwork_version").prefetch_related("artwork_version__assets__media_asset"):
                if element.media_asset_id and element.media_asset.access == element.media_asset.Access.PRIVATE:
                    media_manifest.append(_media_row(element.media_asset, source="studio", source_id=element.pk, role="customer_image"))
                if element.artwork_version_id:
                    for source in element.artwork_version.assets.filter(kind=ArtworkAsset.Kind.SOURCE, media_asset__access="private"):
                        media_manifest.append(_media_row(source.media_asset, source="studio_artwork", source_id=source.pk, role=source.technical_role))

    verified = [{"verification_id": row.pk, "capability_id": row.capability_id, "canonical_code": row.canonical_code} for row in verification_rows]
    unique_media = {row["media_asset_id"]: row for row in media_manifest}
    offer = {
        "quote_id": quote.pk,
        "invitation_id": quote.invitation_id,
        "status_at_assignment": quote.status,
        "unit_price": str(quote.unit_price),
        "setup_fee": str(quote.setup_fee),
        "sample_fee": str(quote.sample_fee),
        "shipping_estimate": str(quote.shipping_estimate),
        "currency": quote.currency,
        "minimum_order_quantity": quote.minimum_order_quantity,
        "production_lead_days": quote.production_lead_days,
        "sample_lead_days": quote.sample_lead_days,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "submitted_at": quote.submitted_at.isoformat() if quote.submitted_at else None,
    }
    snapshot = {
        "schema": "fabinzi-production-specification-v2-7",
        "lineage": {
            "customer_purchase_id": purchase.pk if purchase else None,
            "customer_purchase_number": str(purchase.number) if purchase else None,
            "customer_order_id": order_item.order_id,
            "customer_order_number": str(order_item.order.number),
            "order_item_id": order_item.pk,
        },
        "commerce": {
            "purchase_kind": order_item.purchase_kind,
            "store_product_id": order_item.store_product_id,
            "product_variant_id": order_item.variant_id,
            "designed_product_id": designed.pk,
            "sku": order_item.sku,
            "size": order_item.size,
            "color_name": order_item.color_name,
            "quantity": order_item.quantity,
            "order_production_snapshot": order_item.production_snapshot,
            "order_customization_snapshot": order_item.customization_snapshot,
        },
        "garment_design": {
            "garment_design_id": version.design_id,
            "garment_design_version_id": version.pk,
            "symbolic_ref": version.symbolic_ref,
            "version_number": version.version_number,
            "technical_schema_version": version.technical_schema_version,
            "product_class": version.product_class,
            "size_system": version.size_system,
            "base_material": version.base_material,
            "construction_notes": version.construction_notes,
            "technical_specs": version.technical_specs,
            "technical_policy": version.technical_policy,
            "qc_requirements": version.qc_requirements,
            "production_engineering_validated_at_assignment": version.production_engineering_validated,
            "ordered_size_measurements": measurements,
            "ordered_size_pom": pom,
            "selected_size_patterns": patterns,
            "materials_bom": materials,
            "technical_assets": technical_assets,
        },
        "ready_designed": ready_evidence,
        "studio": studio_evidence,
        "manufacturing_offer": offer,
        "assignment": {"manufacturer_id": manufacturer.pk, "verified_canonical_capabilities": verified},
        "authorized_private_media": list(unique_media.values()),
    }
    return snapshot, sorted(unique_media), sorted({row["canonical_code"] for row in verified})


@transaction.atomic
def assign_customer_order_manufacturer(*, quote, actor, request=None):
    _require_staff(actor)
    quote = ManufacturerQuote.objects.select_for_update(of=("self",)).select_related("invitation__rfq__order_item__order", "invitation__manufacturer").get(pk=quote.pk)
    rfq = RFQ.objects.select_for_update().get(pk=quote.invitation.rfq_id)
    if rfq.source != RFQ.Source.CUSTOMER_ORDER or not rfq.order_item_id:
        raise PermissionDenied("This FABINZI operational assignment service accepts CustomerOrder routing only.")
    if quote.status != ManufacturerQuote.Status.SUBMITTED:
        raise ValidationError("Only a Submitted Manufacturing Offer can be assigned.")
    order_item = OrderItem.objects.select_related("order__purchase", "store_product__designed_product__garment_version", "variant", "studio_project").get(pk=rfq.order_item_id)
    required = required_canonical_capabilities(order_item)
    manufacturer = quote.invitation.manufacturer
    if not manufacturer_operationally_eligible(manufacturer, required_codes=required):
        raise ValidationError("Manufacturer no longer satisfies the operational eligibility requirements for this assignment.")
    job = ProductionJob.objects.select_for_update().get(order=order_item.order)
    if job.status != ProductionJob.Status.AWAITING_ASSIGNMENT or job.manufacturer_id:
        raise ValidationError("This CustomerOrder already has a production assignment or is no longer assignable.")
    verification_rows = [row for row in _verified_rows(manufacturer) if row.canonical_code in set(required)]
    if {row.canonical_code for row in verification_rows} != set(required):
        raise ValidationError("Required canonical Manufacturer capability verification is incomplete.")
    job.manufacturer = manufacturer
    job.selection = None
    job.status = ProductionJob.Status.QUEUED
    job.assigned_at = timezone.now()
    job.full_clean(); job.save(update_fields=["manufacturer", "selection", "status", "assigned_at", "updated_at"])
    snapshot, media_ids, required_codes = build_production_specification_snapshot(order_item=order_item, manufacturer=manufacturer, quote=quote, verification_rows=verification_rows)
    specification = ProductionSpecification(
        job=job, order_item=order_item, manufacturer=manufacturer, accepted_quote=quote,
        snapshot=snapshot, snapshot_sha256=snapshot_sha256(snapshot),
        authorized_media_asset_ids=media_ids, required_canonical_capabilities=required_codes,
        assigned_by=actor,
    )
    specification.full_clean(); specification.save()
    quote.status = ManufacturerQuote.Status.ACCEPTED; quote.save(update_fields=["status", "updated_at"])
    ManufacturerQuote.objects.filter(invitation__rfq=rfq, status=ManufacturerQuote.Status.SUBMITTED).exclude(pk=quote.pk).update(status=ManufacturerQuote.Status.DECLINED)
    rfq.status = RFQ.Status.SELECTED; rfq.selected_at = timezone.now(); rfq.save(update_fields=["status", "selected_at", "updated_at"])
    record_audit_event(actor=actor, action="v2_7.production_assignment.created", instance=specification, metadata={"rfq_id": rfq.pk, "quote_id": quote.pk, "manufacturer_id": manufacturer.pk, "snapshot_sha256": specification.snapshot_sha256}, request=request)
    return specification


def verify_specification_integrity(specification):
    return snapshot_sha256(specification.snapshot) == specification.snapshot_sha256


@transaction.atomic
def release_customer_order_production(*, job, actor, request=None):
    _require_staff(actor)
    job = ProductionJob.objects.select_for_update().get(pk=job.pk)
    try:
        specification = ProductionSpecification.objects.select_for_update().get(job=job)
    except ProductionSpecification.DoesNotExist as exc:
        raise ValidationError("CustomerOrder production cannot be released without an immutable ProductionSpecification.") from exc
    if not verify_specification_integrity(specification):
        raise ValidationError("ProductionSpecification integrity verification failed.")
    version_id = specification.snapshot.get("garment_design", {}).get("garment_design_version_id")
    version = GarmentDesignVersion.objects.get(pk=version_id)
    eligibility = evaluate_version_eligibility(version)
    if not eligibility.get("production_engineering_validated") or not eligibility.get("production_eligible"):
        specification.release_block_reason = "Canonical GarmentDesignVersion is not production eligible."
        specification.save(update_fields=["release_block_reason"])
        record_audit_event(actor=actor, action="v2_7.production_release.blocked", instance=specification, metadata={"eligibility": eligibility}, request=request)
        raise ValidationError(specification.release_block_reason)
    specification.released_at = specification.released_at or timezone.now()
    specification.released_by = actor
    specification.release_block_reason = ""
    specification.save(update_fields=["released_at", "released_by", "release_block_reason"])
    record_audit_event(actor=actor, action="v2_7.production_release.approved", instance=specification, metadata={"eligibility": eligibility, "snapshot_sha256": specification.snapshot_sha256}, request=request)
    return specification
