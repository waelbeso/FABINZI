import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.artwork.models import ArtworkAsset
from apps.audit.services import record_audit_event
from apps.checkout.models import CartItem, CustomerOrder, OrderItem
from apps.design.models import DesignAsset, GarmentDesignVersion
from apps.design.services import evaluate_version_eligibility
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ, RFQInvitation
from apps.organizations.models import OnboardingApplication, Organization
from apps.public_profiles.models import ManufacturerCapabilityVerification
from apps.public_profiles.services import verified_canonical_capabilities
from apps.storefront.models import CustomizationElement
from .models import ProductionJob, ProductionSpecification

CANONICAL_GARMENT = ManufacturerCapabilityVerification.CanonicalCode.GARMENT_MANUFACTURING
CANONICAL_DECORATION = {
    "dtf": ManufacturerCapabilityVerification.CanonicalCode.DTF,
    "dtg": ManufacturerCapabilityVerification.CanonicalCode.DTG,
    "embroidery": ManufacturerCapabilityVerification.CanonicalCode.EMBROIDERY,
}


def _require_staff(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_staff", False):
        raise PermissionDenied("FABINZI operational staff access is required.")


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def snapshot_sha256(snapshot):
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def required_canonical_capabilities(order_item):
    """Derive only from explicit order evidence; never map generic legacy capability names."""
    required = {CANONICAL_GARMENT}
    production = dict(order_item.production_snapshot or {})
    methods = []
    if order_item.purchase_kind == CartItem.Kind.READY_DESIGNED:
        methods.extend(row.get("production_method") for row in production.get("placements", []) if isinstance(row, dict))
    elif order_item.purchase_kind == CartItem.Kind.STUDIO:
        customization = dict(order_item.customization_snapshot or production.get("customization") or {})
        methods.extend(row.get("production_method") for row in customization.get("elements", []) if isinstance(row, dict))
    for method in methods:
        if not method:
            continue
        code = CANONICAL_DECORATION.get(str(method).lower())
        if not code:
            raise ValidationError("Operational routing requires an explicit canonical DTF, DTG, or Embroidery production method; generic legacy print/embroidery inference is forbidden.")
        required.add(code)
    return sorted(required)


def _verified_rows(manufacturer):
    return list(verified_canonical_capabilities(manufacturer))


def manufacturer_operationally_eligible(manufacturer, *, required_codes):
    if manufacturer.kind != Organization.Kind.MANUFACTURER:
        return False
    if manufacturer.verification_status != Organization.VerificationStatus.ACTIVE:
        return False
    try:
        if manufacturer.onboarding_application.status != OnboardingApplication.Status.APPROVED:
            return False
    except OnboardingApplication.DoesNotExist:
        return False
    verified = {row.canonical_code for row in _verified_rows(manufacturer)}
    return set(required_codes).issubset(verified)


def eligible_manufacturers(order_item):
    required = required_canonical_capabilities(order_item)
    candidates = Organization.objects.filter(
        kind=Organization.Kind.MANUFACTURER,
        verification_status=Organization.VerificationStatus.ACTIVE,
        onboarding_application__status=OnboardingApplication.Status.APPROVED,
    ).order_by("id")
    # Deliberately no public profile/listing status, accepts_rfq, public product approval,
    # marketplace discoverability, or remaining-offer-quota predicate.
    return [manufacturer for manufacturer in candidates if manufacturer_operationally_eligible(manufacturer, required_codes=required)]


@transaction.atomic
def create_customer_order_routing(*, order_item, actor, request=None):
    _require_staff(actor)
    order_item = OrderItem.objects.select_for_update().select_related(
        "order__purchase", "order__designer_organization", "store_product__designed_product__garment_version", "variant"
    ).get(pk=order_item.pk)
    if order_item.order.status != CustomerOrder.Status.CONFIRMED:
        raise ValidationError("Only a confirmed CustomerOrder can enter production routing.")
    existing = RFQ.objects.filter(order_item=order_item, source=RFQ.Source.CUSTOMER_ORDER).first()
    if existing:
        return existing
    required = required_canonical_capabilities(order_item)
    production = dict(order_item.production_snapshot or {})
    routing_snapshot = {
        "customer_purchase_id": order_item.order.purchase_id,
        "customer_order_id": order_item.order_id,
        "order_item_id": order_item.pk,
        "purchase_kind": order_item.purchase_kind,
        "store_product_id": order_item.store_product_id,
        "variant_id": order_item.variant_id,
        "garment_version_id": production.get("garment_version_id") or order_item.store_product.designed_product.garment_version_id,
        "required_canonical_capabilities": required,
        "public_marketplace_visibility_required": False,
        "remaining_offer_quota_required_for_routing": False,
    }
    rfq = RFQ(
        designer_organization=order_item.order.designer_organization,
        designed_product=order_item.store_product.designed_product,
        source=RFQ.Source.CUSTOMER_ORDER,
        order_item=order_item,
        routing_snapshot=routing_snapshot,
        routed_at=timezone.now(),
        title=f"Customer Order {order_item.order.number}",
        quantity=order_item.quantity,
        size_breakdown={order_item.size: order_item.quantity} if order_item.size else {},
        color_requirements=[order_item.color_name] if order_item.color_name else [],
        requested_methods=required,
        currency=order_item.order.currency,
        delivery_country=(order_item.order.shipping_snapshot or {}).get("country", "EG"),
        delivery_city=(order_item.order.shipping_snapshot or {}).get("city", ""),
        status=RFQ.Status.OPEN,
        opened_at=timezone.now(),
        created_by=actor,
    )
    rfq.full_clean(); rfq.save()
    invited = []
    for manufacturer in eligible_manufacturers(order_item):
        RFQInvitation.objects.create(rfq=rfq, manufacturer=manufacturer)
        invited.append(manufacturer.pk)
    record_audit_event(actor=actor, action="v2_7.customer_order.routed", instance=rfq, metadata={"order_item_id": order_item.pk, "manufacturer_ids": invited, "required_capabilities": required}, request=request)
    return rfq

