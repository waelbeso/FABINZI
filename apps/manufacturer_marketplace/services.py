from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.artwork.models import DesignedProduct
from apps.audit.services import record_audit_event
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access
from .models import ManufacturerCapability, ManufacturerListing, ManufacturerPortfolioAsset, ManufacturerQuote, ManufacturerSelection, RFQ, RFQInvitation

MANUFACTURER_MANAGE_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER]
MANUFACTURER_QUOTE_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.PRODUCTION_MANAGER]
DESIGNER_RFQ_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER]
DESIGNER_SELECT_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGN_MANAGER]


def _require_active_org(org, kind):
    if org.kind != kind or org.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError(f"An approved active {kind.title()} business is required.")


def get_or_create_listing(*, organization, actor, request=None):
    _require_active_org(organization, Organization.Kind.MANUFACTURER)
    require_org_access(actor, organization, roles=MANUFACTURER_MANAGE_ROLES)
    listing, created = ManufacturerListing.objects.get_or_create(organization=organization)
    if created:
        record_audit_event(actor=actor, action="manufacturer_marketplace.listing.created", instance=listing, request=request)
    return listing


@transaction.atomic
def update_listing(*, listing, actor, data, request=None):
    require_org_access(actor, listing.organization, roles=MANUFACTURER_MANAGE_ROLES)
    for field in ["headline_en","headline_ar","overview_en","overview_ar","public_email","public_phone","accepts_rfq","sample_orders","min_order_quantity","lead_time_min_days","lead_time_max_days","available_monthly_capacity","materials","production_methods","markets","certifications"]:
        if field in data:
            setattr(listing, field, data[field])
    if "available_monthly_capacity" in data:
        listing.last_capacity_update = timezone.now()
    listing.full_clean(); listing.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.listing.updated", instance=listing, request=request)
    return listing


@transaction.atomic
def publish_listing(*, listing, actor, request=None):
    require_org_access(actor, listing.organization, roles=MANUFACTURER_MANAGE_ROLES)
    _require_active_org(listing.organization, Organization.Kind.MANUFACTURER)
    if not (listing.headline_en or listing.headline_ar):
        raise ValidationError("At least one marketplace headline is required.")
    if not listing.capabilities.filter(is_active=True).exists():
        raise ValidationError("At least one active manufacturing capability is required.")
    listing.status = ManufacturerListing.Status.PUBLISHED
    if not listing.published_at:
        listing.published_at = timezone.now()
    listing.save(update_fields=["status","published_at","updated_at"])
    record_audit_event(actor=actor, action="manufacturer_marketplace.listing.published", instance=listing, request=request)
    return listing


@transaction.atomic
def add_capability(*, listing, actor, capability_type, name, description="", methods=None, min_quantity=None, max_quantity=None, lead_time_days=None, request=None):
    require_org_access(actor, listing.organization, roles=MANUFACTURER_MANAGE_ROLES)
    capability = ManufacturerCapability(listing=listing, capability_type=capability_type, name=name, description=description, methods=methods or [], min_quantity=min_quantity, max_quantity=max_quantity, lead_time_days=lead_time_days)
    capability.full_clean(); capability.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.capability.added", instance=capability, metadata={"listing_id": listing.pk}, request=request)
    return capability


@transaction.atomic
def add_portfolio_asset(*, listing, actor, media_asset, caption="", sort_order=0, request=None):
    require_org_access(actor, listing.organization, roles=MANUFACTURER_MANAGE_ROLES)
    if media_asset.uploaded_by_id and media_asset.uploaded_by_id != actor.pk and not actor.is_staff:
        raise PermissionDenied("This media asset is not owned by the current user.")
    asset = ManufacturerPortfolioAsset(listing=listing, media_asset=media_asset, caption=caption, sort_order=sort_order)
    asset.full_clean(); asset.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.portfolio.added", instance=asset, metadata={"listing_id": listing.pk}, request=request)
    return asset


@transaction.atomic
def create_rfq(*, designer_organization, actor, designed_product, title, quantity, size_breakdown=None, color_requirements=None, requested_methods=None, target_unit_price=None, currency="EGP", desired_delivery_date=None, delivery_country="EG", delivery_city="", notes="", request=None):
    _require_active_org(designer_organization, Organization.Kind.DESIGNER)
    require_org_access(actor, designer_organization, roles=DESIGNER_RFQ_ROLES)
    if designed_product.organization_id != designer_organization.pk or designed_product.status != DesignedProduct.Status.PUBLISHED:
        raise ValidationError("RFQs require a published Designed Product owned by the Designer business.")
    rfq = RFQ(designer_organization=designer_organization, designed_product=designed_product, source=RFQ.Source.DESIGNER_SOURCING, title=title, quantity=quantity, size_breakdown=size_breakdown or {}, color_requirements=color_requirements or [], requested_methods=requested_methods or [], target_unit_price=target_unit_price, currency=currency.upper(), desired_delivery_date=desired_delivery_date, delivery_country=delivery_country.upper(), delivery_city=delivery_city, notes=notes, created_by=actor)
    rfq.full_clean(); rfq.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.rfq.created", instance=rfq, request=request)
    return rfq


@transaction.atomic
def open_rfq(*, rfq, actor, manufacturer_ids, request=None):
    if rfq.source != RFQ.Source.DESIGNER_SOURCING:
        raise PermissionDenied("Customer Order manufacturing routing is FABINZI-controlled.")
    require_org_access(actor, rfq.designer_organization, roles=DESIGNER_RFQ_ROLES)
    if rfq.status != RFQ.Status.DRAFT:
        raise ValidationError("Only draft RFQs can be opened.")
    manufacturers = Organization.objects.filter(pk__in=set(manufacturer_ids), kind=Organization.Kind.MANUFACTURER, verification_status=Organization.VerificationStatus.ACTIVE, marketplace_listing__status=ManufacturerListing.Status.PUBLISHED, marketplace_listing__accepts_rfq=True)
    if not manufacturers.exists():
        raise ValidationError("Select at least one eligible published Manufacturer.")
    for manufacturer in manufacturers:
        invitation, created = RFQInvitation.objects.get_or_create(rfq=rfq, manufacturer=manufacturer)
        if created:
            for membership in manufacturer.memberships.filter(is_active=True, role__in=MANUFACTURER_QUOTE_ROLES).select_related("user"):
                Notification.objects.create(recipient=membership.user, type="manufacturer_rfq", title_en="New manufacturing RFQ", title_ar="طلب عرض تصنيع جديد", body_en=rfq.title, body_ar=rfq.title, destination="/manufacturer/marketplace/")
    rfq.status = RFQ.Status.OPEN; rfq.opened_at = timezone.now(); rfq.save(update_fields=["status","opened_at","updated_at"])
    record_audit_event(actor=actor, action="manufacturer_marketplace.rfq.opened", instance=rfq, metadata={"invitations": rfq.invitations.count()}, request=request)
    return rfq


def mark_invitation_viewed(*, invitation, actor):
    require_org_access(actor, invitation.manufacturer, roles=MANUFACTURER_QUOTE_ROLES)
    if invitation.status == RFQInvitation.Status.INVITED:
        invitation.status = RFQInvitation.Status.VIEWED; invitation.viewed_at = timezone.now(); invitation.save(update_fields=["status","viewed_at"])
    return invitation


def _quote_values(*, unit_price, production_lead_days, setup_fee, sample_fee, shipping_estimate, currency, minimum_order_quantity, sample_lead_days, valid_until, notes):
    raw_values = {
        "unit_price": unit_price,
        "production_lead_days": production_lead_days,
        "setup_fee": setup_fee,
        "sample_fee": sample_fee,
        "shipping_estimate": shipping_estimate,
        "currency": currency.upper(),
        "minimum_order_quantity": minimum_order_quantity,
        "sample_lead_days": sample_lead_days,
        "valid_until": valid_until,
        "notes": notes,
    }
    return {
        field: ManufacturerQuote._meta.get_field(field).to_python(value)
        for field, value in raw_values.items()
    }


def _apply_quote_values(quote, *, unit_price, production_lead_days, setup_fee, sample_fee, shipping_estimate, currency, minimum_order_quantity, sample_lead_days, valid_until, notes):
    values = _quote_values(
        unit_price=unit_price,
        production_lead_days=production_lead_days,
        setup_fee=setup_fee,
        sample_fee=sample_fee,
        shipping_estimate=shipping_estimate,
        currency=currency,
        minimum_order_quantity=minimum_order_quantity,
        sample_lead_days=sample_lead_days,
        valid_until=valid_until,
        notes=notes,
    )
    for field, value in values.items():
        setattr(quote, field, value)
    return quote


@transaction.atomic
def save_quote_draft(*, invitation, actor, unit_price, production_lead_days, setup_fee=0, sample_fee=0, shipping_estimate=0, currency="EGP", minimum_order_quantity=1, sample_lead_days=None, valid_until=None, notes="", request=None):
    require_org_access(actor, invitation.manufacturer, roles=MANUFACTURER_QUOTE_ROLES)
    invitation = RFQInvitation.objects.select_for_update().select_related("rfq", "manufacturer").get(pk=invitation.pk)
    if invitation.rfq.status not in {RFQ.Status.OPEN, RFQ.Status.QUOTED}:
        raise ValidationError("This RFQ is not accepting offers.")
    if invitation.status == RFQInvitation.Status.DECLINED:
        raise ValidationError("A declined invitation cannot be quoted.")
    quote = ManufacturerQuote.objects.select_for_update().filter(invitation=invitation).first()
    if quote and quote.status not in {ManufacturerQuote.Status.DRAFT, ManufacturerQuote.Status.WITHDRAWN}:
        raise ValidationError("Only a draft or withdrawn Manufacturing Offer can be edited.")
    if quote is None:
        quote = ManufacturerQuote(invitation=invitation, unit_price=unit_price, production_lead_days=production_lead_days, created_by=actor)
    _apply_quote_values(quote, unit_price=unit_price, production_lead_days=production_lead_days, setup_fee=setup_fee, sample_fee=sample_fee, shipping_estimate=shipping_estimate, currency=currency, minimum_order_quantity=minimum_order_quantity, sample_lead_days=sample_lead_days, valid_until=valid_until, notes=notes)
    quote.status = ManufacturerQuote.Status.DRAFT
    quote.full_clean(); quote.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.quote.draft_saved", instance=quote, metadata={"rfq_id": invitation.rfq_id}, request=request)
    return quote


@transaction.atomic
def submit_quote(*, invitation, actor, unit_price, production_lead_days, setup_fee=0, sample_fee=0, shipping_estimate=0, currency="EGP", minimum_order_quantity=1, sample_lead_days=None, valid_until=None, notes="", request=None):
    """Canonical first Submitted transition; V2-3 quota is consumed exactly once."""
    require_org_access(actor, invitation.manufacturer, roles=MANUFACTURER_QUOTE_ROLES)
    original_invitation = invitation
    original_rfq = invitation.rfq
    locked_invitation = RFQInvitation.objects.select_for_update().select_related("rfq", "manufacturer").get(pk=invitation.pk)
    if locked_invitation.rfq.status not in {RFQ.Status.OPEN, RFQ.Status.QUOTED}:
        raise ValidationError("This RFQ is not accepting quotes.")
    if locked_invitation.status == RFQInvitation.Status.DECLINED:
        raise ValidationError("A declined invitation cannot be quoted.")
    quote = ManufacturerQuote.objects.select_for_update().filter(invitation=locked_invitation).first()
    if quote and quote.status == ManufacturerQuote.Status.SUBMITTED:
        incoming_values = _quote_values(
            unit_price=unit_price,
            production_lead_days=production_lead_days,
            setup_fee=setup_fee,
            sample_fee=sample_fee,
            shipping_estimate=shipping_estimate,
            currency=currency,
            minimum_order_quantity=minimum_order_quantity,
            sample_lead_days=sample_lead_days,
            valid_until=valid_until,
            notes=notes,
        )
        if any(getattr(quote, field) != value for field, value in incoming_values.items()):
            raise ValidationError("Submitted Manufacturing Offer values are immutable.")
        original_invitation.status = locked_invitation.status
        original_invitation.responded_at = locked_invitation.responded_at
        original_rfq.status = locked_invitation.rfq.status
        quote.invitation = original_invitation
        return quote
    if quote and quote.status not in {ManufacturerQuote.Status.DRAFT, ManufacturerQuote.Status.WITHDRAWN}:
        raise ValidationError("Only draft or withdrawn quotes can be submitted.")
    if quote is None:
        quote = ManufacturerQuote(invitation=locked_invitation, unit_price=unit_price, production_lead_days=production_lead_days, created_by=actor)
    _apply_quote_values(quote, unit_price=unit_price, production_lead_days=production_lead_days, setup_fee=setup_fee, sample_fee=sample_fee, shipping_estimate=shipping_estimate, currency=currency, minimum_order_quantity=minimum_order_quantity, sample_lead_days=sample_lead_days, valid_until=valid_until, notes=notes)
    quote.status = ManufacturerQuote.Status.SUBMITTED
    quote.submitted_at = timezone.now()
    quote.full_clean(); quote.save()

    from apps.subscriptions.services import consume_manufacturer_offer
    consume_manufacturer_offer(quote=quote)

    locked_invitation.status = RFQInvitation.Status.QUOTED; locked_invitation.responded_at = timezone.now(); locked_invitation.save(update_fields=["status","responded_at"])
    if locked_invitation.rfq.status == RFQ.Status.OPEN:
        locked_invitation.rfq.status = RFQ.Status.QUOTED; locked_invitation.rfq.save(update_fields=["status","updated_at"])
    original_invitation.status = locked_invitation.status
    original_invitation.responded_at = locked_invitation.responded_at
    original_rfq.status = locked_invitation.rfq.status
    quote.invitation = original_invitation
    for membership in locked_invitation.rfq.designer_organization.memberships.filter(is_active=True, role__in=DESIGNER_RFQ_ROLES).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="manufacturer_quote", title_en="Manufacturing quote received", title_ar="تم استلام عرض تصنيع", body_en=locked_invitation.manufacturer.display_name, body_ar=locked_invitation.manufacturer.display_name, destination="/designer/rfqs/")
    record_audit_event(actor=actor, action="manufacturer_marketplace.quote.submitted", instance=quote, metadata={"rfq_id": locked_invitation.rfq_id}, request=request)
    return quote


@transaction.atomic
def decline_invitation(*, invitation, actor, request=None):
    require_org_access(actor, invitation.manufacturer, roles=MANUFACTURER_QUOTE_ROLES)
    if invitation.rfq.status not in {RFQ.Status.OPEN, RFQ.Status.QUOTED}:
        raise ValidationError("This RFQ is closed to responses.")
    invitation.status = RFQInvitation.Status.DECLINED; invitation.responded_at = timezone.now(); invitation.save(update_fields=["status","responded_at"])
    record_audit_event(actor=actor, action="manufacturer_marketplace.rfq.declined", instance=invitation, metadata={"rfq_id": invitation.rfq_id}, request=request)
    return invitation


@transaction.atomic
def select_quote(*, quote, actor, request=None):
    rfq = quote.invitation.rfq
    if rfq.source != RFQ.Source.DESIGNER_SOURCING:
        raise PermissionDenied("Customer Order production assignment is FABINZI-controlled.")
    require_org_access(actor, rfq.designer_organization, roles=DESIGNER_SELECT_ROLES)
    if quote.status != ManufacturerQuote.Status.SUBMITTED:
        raise ValidationError("Only submitted quotes can be selected.")
    if rfq.status not in {RFQ.Status.OPEN, RFQ.Status.QUOTED}:
        raise ValidationError("RFQ is not selectable.")
    if hasattr(rfq, "selection"):
        raise ValidationError("A Manufacturer has already been selected for this RFQ.")
    selection = ManufacturerSelection(rfq=rfq, quote=quote, manufacturer=quote.invitation.manufacturer, selected_by=actor)
    selection.full_clean(); selection.save()
    quote.status = ManufacturerQuote.Status.ACCEPTED; quote.save(update_fields=["status","updated_at"])
    ManufacturerQuote.objects.filter(invitation__rfq=rfq, status=ManufacturerQuote.Status.SUBMITTED).exclude(pk=quote.pk).update(status=ManufacturerQuote.Status.DECLINED)
    rfq.status = RFQ.Status.SELECTED; rfq.selected_at = timezone.now(); rfq.save(update_fields=["status","selected_at","updated_at"])
    for membership in selection.manufacturer.memberships.filter(is_active=True, role__in=MANUFACTURER_QUOTE_ROLES).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="manufacturer_selected", title_en="Your manufacturing quote was selected", title_ar="تم اختيار عرض التصنيع الخاص بكم", body_en=rfq.title, body_ar=rfq.title, destination="/manufacturer/marketplace/")
    record_audit_event(actor=actor, action="manufacturer_marketplace.quote.selected", instance=selection, metadata={"rfq_id": rfq.pk,"quote_id":quote.pk}, request=request)
    return selection


@transaction.atomic
def cancel_rfq(*, rfq, actor, request=None):
    if rfq.source != RFQ.Source.DESIGNER_SOURCING:
        raise PermissionDenied("Customer Order routing is controlled by FABINZI operations.")
    require_org_access(actor, rfq.designer_organization, roles=DESIGNER_SELECT_ROLES)
    if rfq.status in {RFQ.Status.SELECTED, RFQ.Status.CLOSED, RFQ.Status.CANCELLED}:
        raise ValidationError("This RFQ can no longer be cancelled.")
    rfq.status = RFQ.Status.CANCELLED; rfq.closed_at = timezone.now(); rfq.save(update_fields=["status","closed_at","updated_at"])
    ManufacturerQuote.objects.filter(invitation__rfq=rfq, status=ManufacturerQuote.Status.SUBMITTED).update(status=ManufacturerQuote.Status.WITHDRAWN)
    record_audit_event(actor=actor, action="manufacturer_marketplace.rfq.cancelled", instance=rfq, request=request)
    return rfq
