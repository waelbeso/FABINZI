from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.finance.models import FinanceAccount, PayoutProfile, SettlementRequest
from apps.finance.services import (
    account_balance,
    cancel_settlement,
    request_settlement,
    update_payout_profile,
)
from apps.manufacturer_marketplace.models import (
    ManufacturerCapability,
    ManufacturerListing,
    ManufacturerQuote,
    RFQ,
    RFQInvitation,
)
from apps.manufacturer_marketplace.services import mark_invitation_viewed, submit_quote
from apps.notifications.models import Notification
from apps.operations.models import (
    FulfillmentRecord,
    ProductionAsset,
    ProductionJob,
    ProductionMilestone,
    QCInspection,
)
from apps.operations.services import (
    pack_order,
    record_qc,
    request_qc,
    ship_order,
    start_production,
    update_milestone,
)
from apps.storefront.models import CustomizationElement
from .forms import ManufacturerOnboardingForm, OrganizationForm
from .manufacturer_context import (
    MANUFACTURER_FINANCE_ROLES,
    MANUFACTURER_MANAGE_ROLES,
    MANUFACTURER_PRODUCTION_ROLES,
    MANUFACTURER_QC_ROLES,
    MANUFACTURER_QUOTE_ROLES,
    MANUFACTURER_TECHNICAL_VIEW_ROLES,
    manufacturer_context,
)
from .manufacturer_services import (
    create_manufacturer_capability,
    deactivate_manufacturer_capability,
    secure_manufacturer_member_deactivate,
    secure_manufacturer_member_upsert,
    update_active_manufacturer_profile,
    update_manufacturer_capability,
)
from .models import Membership, OnboardingApplication, Organization
from .services import create_manufacturer_onboarding, submit_application

User = get_user_model()


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _error_text(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(exc.messages)
    return str(exc)


def _optional_int(value):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid whole number.") from exc
    if number < 0:
        raise ValidationError("Enter zero or a positive whole number.")
    return number


def _optional_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid monetary amount.") from exc


def _with_context(request, extra=None, *, required=True):
    context = manufacturer_context(request, required=required)
    if extra:
        context.update(extra)
    return context


def _require_active(request, *, roles=None):
    context = _with_context(request)
    organization = context["manufacturer_organization"]
    membership = context["manufacturer_membership"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An approved active Manufacturer organization is required.")
    if roles and membership.role not in set(roles):
        raise PermissionDenied("Your Manufacturer role does not allow this action.")
    return context


def _redirect_with_org(name, organization, **kwargs):
    from django.urls import reverse

    url = reverse(name, kwargs=kwargs)
    return redirect(f"{url}?org={organization.pk}")


def _render(request, template, context, *, status=200):
    context = dict(context)
    context["seo_robots"] = "noindex, nofollow, noarchive"
    context["page_seo"] = {
        "title": _localized(request, "Manufacturer workspace · FABINZI", "مساحة المصنع · FABINZI"),
        "description": _localized(
            request,
            "Secure FABINZI Manufacturer workspace.",
            "مساحة FABINZI الآمنة لشركاء التصنيع.",
        ),
    }
    response = render(request, template, context, status=status)
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Cache-Control"] = "private, no-store"
    return response


def _application_state_context(context):
    application = context.get("manufacturer_application")
    organization = context.get("manufacturer_organization")
    status = application.status if application else None
    return {
        "application": application,
        "organization": organization,
        "application_status": status,
        "can_edit_application": bool(
            application
            and status
            in {
                OnboardingApplication.Status.DRAFT,
                OnboardingApplication.Status.REVISION_REQUIRED,
            }
        ),
        "can_submit_application": bool(
            application
            and status
            in {
                OnboardingApplication.Status.DRAFT,
                OnboardingApplication.Status.REVISION_REQUIRED,
            }
        ),
    }


def _active_job_queryset(organization):
    return (
        ProductionJob.objects.filter(manufacturer=organization)
        .select_related(
            "manufacturer",
            "order",
            "order__item",
            "order__item__variant",
            "order__item__store_product",
            "order__item__store_product__designed_product",
            "order__item__store_product__designed_product__garment_version",
            "order__item__store_product__designed_product__garment_version__design",
            "order__item__store_product__designed_product__artwork_version",
            "order__item__store_product__designed_product__artwork_version__artwork",
            "order__fulfillment",
        )
        .prefetch_related("milestones", "qc_inspections", "assets__media_asset")
    )


@login_required
def manufacturer_portal(request):
    context = _with_context(request, required=False)
    membership = context["manufacturer_membership"]
    if not membership:
        if request.method == "POST":
            org_form = OrganizationForm(request.POST, prefix="org")
            profile_form = ManufacturerOnboardingForm(request.POST, prefix="profile")
            if org_form.is_valid() and profile_form.is_valid():
                profile_data = profile_form.cleaned_data.copy()
                profile_data.pop("accept_terms", None)
                profile_data["terms_accepted"] = True
                profile_data["terms_accepted_at"] = timezone.now()
                application = create_manufacturer_onboarding(
                    user=request.user,
                    organization_data=org_form.cleaned_data.copy(),
                    profile_data=profile_data,
                    request=request,
                )
                request.session["manufacturer_organization_id"] = application.organization_id
                messages.success(
                    request,
                    _localized(
                        request,
                        "Manufacturer onboarding draft created.",
                        "تم إنشاء مسودة انضمام المصنع.",
                    ),
                )
                return redirect("manufacturer")
        else:
            org_form = OrganizationForm(prefix="org")
            profile_form = ManufacturerOnboardingForm(prefix="profile")
        context.update({"org_form": org_form, "profile_form": profile_form})
        return _render(request, "manufacturer/onboarding.html", context)

    organization = context["manufacturer_organization"]
    application = context["manufacturer_application"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        context.update(_application_state_context(context))
        return _render(request, "manufacturer/access_state.html", context)

    invitations = RFQInvitation.objects.filter(manufacturer=organization)
    quotes = ManufacturerQuote.objects.filter(invitation__manufacturer=organization)
    jobs = ProductionJob.objects.filter(manufacturer=organization)
    fulfillments = FulfillmentRecord.objects.filter(
        order__production_job__manufacturer=organization
    )
    settlements = SettlementRequest.objects.filter(organization=organization)

    metrics = {
        "open_invitations": invitations.filter(
            rfq__status__in=[RFQ.Status.OPEN, RFQ.Status.QUOTED],
            status__in=[RFQInvitation.Status.INVITED, RFQInvitation.Status.VIEWED],
        ).count(),
        "submitted_quotes": quotes.filter(status=ManufacturerQuote.Status.SUBMITTED).count(),
        "selected_quotes": quotes.filter(status=ManufacturerQuote.Status.ACCEPTED).count(),
        "assigned_jobs": jobs.exclude(status=ProductionJob.Status.CANCELLED).count(),
        "qc_required": jobs.filter(status=ProductionJob.Status.QC_PENDING).count(),
        "ready_to_ship": fulfillments.filter(
            status__in=[FulfillmentRecord.Status.READY_TO_PACK, FulfillmentRecord.Status.PACKED]
        ).count(),
        "open_settlements": settlements.filter(
            status__in=[SettlementRequest.Status.REQUESTED, SettlementRequest.Status.APPROVED]
        ).count(),
    }

    attention = []
    if context["manufacturer_can_quote"]:
        for invitation in invitations.filter(
            rfq__status__in=[RFQ.Status.OPEN, RFQ.Status.QUOTED],
            status__in=[RFQInvitation.Status.INVITED, RFQInvitation.Status.VIEWED],
        ).select_related("rfq")[:5]:
            attention.append(
                {
                    "label": invitation.rfq.title,
                    "detail": _localized(
                        request,
                        "Manufacturing RFQ awaits your response",
                        "طلب تصنيع ينتظر ردك",
                    ),
                    "url": f"/manufacturer/opportunities/{invitation.pk}/?org={organization.pk}",
                }
            )
    if context["manufacturer_can_production"]:
        for job in jobs.filter(
            status__in=[ProductionJob.Status.QUEUED, ProductionJob.Status.QC_FAILED]
        ).select_related("order")[:5]:
            attention.append(
                {
                    "label": str(job.order.number),
                    "detail": _localized(
                        request,
                        "Production job requires action",
                        "مهمة إنتاج تتطلب إجراءً",
                    ),
                    "url": f"/manufacturer/production/{job.pk}/?org={organization.pk}",
                }
            )
        for fulfillment in fulfillments.filter(
            status__in=[FulfillmentRecord.Status.READY_TO_PACK, FulfillmentRecord.Status.PACKED]
        ).select_related("order")[:5]:
            attention.append(
                {
                    "label": str(fulfillment.order.number),
                    "detail": _localized(
                        request,
                        "Fulfillment is waiting for packing or shipment",
                        "التنفيذ ينتظر التعبئة أو الشحن",
                    ),
                    "url": f"/manufacturer/production/{fulfillment.order.production_job.pk}/shipment/?org={organization.pk}",
                }
            )
    if context["manufacturer_can_finance"] and not PayoutProfile.objects.filter(
        organization=organization
    ).exists():
        attention.append(
            {
                "label": _localized(request, "Payout setup", "إعداد التحويلات"),
                "detail": _localized(
                    request,
                    "Add a payout profile before requesting a settlement.",
                    "أضف ملف التحويل قبل طلب التسوية.",
                ),
                "url": f"/manufacturer/finance/?org={organization.pk}",
            }
        )

    recent_notifications = Notification.objects.filter(recipient=request.user)[:6]
    context.update(
        {
            "application": application,
            "metrics": metrics,
            "attention": attention[:10],
            "recent_notifications": recent_notifications,
        }
    )
    return _render(request, "manufacturer/dashboard.html", context)


@login_required
def manufacturer_profile(request):
    context = _require_active(request)
    organization = context["manufacturer_organization"]
    profile = organization.manufacturer_profile
    if request.method == "POST":
        if not context["manufacturer_can_manage"]:
            raise PermissionDenied
        try:
            update_active_manufacturer_profile(
                organization=organization,
                actor=request.user,
                organization_data={
                    "display_name": request.POST.get("display_name", "").strip(),
                    "email": request.POST.get("email", "").strip(),
                    "phone": request.POST.get("phone", "").strip(),
                    "website": request.POST.get("website", "").strip(),
                    "address_line1": request.POST.get("address_line1", "").strip(),
                    "address_line2": request.POST.get("address_line2", "").strip(),
                    "city": request.POST.get("city", "").strip(),
                    "region": request.POST.get("region", "").strip(),
                    "country": request.POST.get("country", "EG").strip().upper(),
                    "legal_name": request.POST.get("legal_name", "").strip(),
                },
                profile_data={
                    "google_maps_url": request.POST.get("google_maps_url", "").strip(),
                    "primary_contact_person": request.POST.get("primary_contact_person", "").strip(),
                    "contact_job_title": request.POST.get("contact_job_title", "").strip(),
                    "whatsapp": request.POST.get("whatsapp", "").strip(),
                    "commercial_registration": request.POST.get("commercial_registration", "").strip(),
                    "tax_number": request.POST.get("tax_number", "").strip(),
                },
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                _localized(request, "Manufacturer profile updated.", "تم تحديث ملف المصنع."),
            )
            return _redirect_with_org("manufacturer-profile", organization)
    context.update({"profile": profile})
    return _render(request, "manufacturer/profile.html", context)


@login_required
def manufacturer_team(request):
    context = _require_active(request)
    organization = context["manufacturer_organization"]
    if request.method == "POST":
        if not context["manufacturer_can_manage"]:
            raise PermissionDenied
        action = request.POST.get("action")
        try:
            if action == "upsert":
                email = request.POST.get("email", "").strip()
                user = get_object_or_404(User, email__iexact=email)
                secure_manufacturer_member_upsert(
                    organization=organization,
                    actor=request.user,
                    user=user,
                    role=request.POST.get("role", ""),
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Team member updated.", "تم تحديث عضو الفريق."),
                )
            elif action == "deactivate":
                membership = get_object_or_404(
                    Membership,
                    pk=request.POST.get("membership_id"),
                    organization=organization,
                )
                secure_manufacturer_member_deactivate(
                    membership=membership,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Team member deactivated.", "تم إيقاف عضو الفريق."),
                )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("manufacturer-team", organization)

    members = organization.memberships.select_related("user").order_by("joined_at", "id")
    allowed_roles = [
        choice
        for choice in Membership.Role.choices
        if choice[0]
        in {
            Membership.Role.OWNER,
            Membership.Role.MANAGER,
            Membership.Role.PRODUCTION_MANAGER,
            Membership.Role.OPERATOR,
            Membership.Role.QC,
            Membership.Role.ACCOUNTANT,
        }
    ]
    context.update({"members": members, "allowed_roles": allowed_roles})
    return _render(request, "manufacturer/team.html", context)


@login_required
def manufacturer_capabilities(request):
    context = _require_active(request)
    organization = context["manufacturer_organization"]
    listing = ManufacturerListing.objects.filter(organization=organization).first()
    if request.method == "POST":
        if not context["manufacturer_can_manage"]:
            raise PermissionDenied
        action = request.POST.get("action")
        try:
            if action in {"create", "update"}:
                data = {
                    "capability_type": request.POST.get("capability_type", ""),
                    "name": request.POST.get("name", "").strip(),
                    "description": request.POST.get("description", "").strip(),
                    "methods": [
                        value.strip()
                        for value in request.POST.get("methods", "").replace("\n", ",").split(",")
                        if value.strip()
                    ],
                    "min_quantity": _optional_int(request.POST.get("min_quantity")),
                    "max_quantity": _optional_int(request.POST.get("max_quantity")),
                    "lead_time_days": _optional_int(request.POST.get("lead_time_days")),
                }
                if action == "create":
                    create_manufacturer_capability(
                        organization=organization,
                        actor=request.user,
                        request=request,
                        **data,
                    )
                else:
                    capability = get_object_or_404(
                        ManufacturerCapability,
                        pk=request.POST.get("capability_id"),
                        listing__organization=organization,
                    )
                    update_manufacturer_capability(
                        capability=capability,
                        actor=request.user,
                        data=data,
                        request=request,
                    )
                messages.success(
                    request,
                    _localized(request, "Capability saved.", "تم حفظ القدرة التصنيعية."),
                )
            elif action == "deactivate":
                capability = get_object_or_404(
                    ManufacturerCapability,
                    pk=request.POST.get("capability_id"),
                    listing__organization=organization,
                )
                deactivate_manufacturer_capability(
                    capability=capability,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Capability deactivated.", "تم إيقاف القدرة التصنيعية."),
                )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("manufacturer-capabilities", organization)

    capabilities = (
        listing.capabilities.order_by("capability_type", "name") if listing else []
    )
    context.update(
        {
            "listing": listing,
            "capabilities": capabilities,
            "capability_types": ManufacturerCapability.CapabilityType.choices,
        }
    )
    return _render(request, "manufacturer/capabilities.html", context)


@login_required
def manufacturer_opportunities(request):
    context = _require_active(request, roles=MANUFACTURER_QUOTE_ROLES)
    organization = context["manufacturer_organization"]
    invitations = (
        RFQInvitation.objects.filter(manufacturer=organization)
        .select_related("rfq", "rfq__designer_organization", "rfq__designed_product")
        .order_by("-sent_at")
    )
    status_filter = request.GET.get("status", "").strip()
    if status_filter in RFQInvitation.Status.values:
        invitations = invitations.filter(status=status_filter)
    else:
        status_filter = ""
    context.update(
        {
            "invitations": invitations,
            "status_filter": status_filter,
            "status_choices": RFQInvitation.Status.choices,
        }
    )
    return _render(request, "manufacturer/opportunities.html", context)


@login_required
def manufacturer_rfq_detail(request, pk):
    context = _require_active(request, roles=MANUFACTURER_QUOTE_ROLES)
    organization = context["manufacturer_organization"]
    invitation = get_object_or_404(
        RFQInvitation.objects.select_related(
            "rfq",
            "rfq__designer_organization",
            "rfq__designed_product",
            "rfq__designed_product__garment_version__design",
        ),
        pk=pk,
        manufacturer=organization,
    )
    mark_invitation_viewed(invitation=invitation, actor=request.user)
    quote = ManufacturerQuote.objects.filter(invitation=invitation).first()
    if request.method == "POST":
        if not context["manufacturer_can_quote"]:
            raise PermissionDenied
        try:
            quote = submit_quote(
                invitation=invitation,
                actor=request.user,
                unit_price=_optional_decimal(request.POST.get("unit_price")),
                production_lead_days=_optional_int(request.POST.get("production_lead_days")),
                setup_fee=_optional_decimal(request.POST.get("setup_fee")) or Decimal("0"),
                sample_fee=_optional_decimal(request.POST.get("sample_fee")) or Decimal("0"),
                shipping_estimate=_optional_decimal(request.POST.get("shipping_estimate")) or Decimal("0"),
                currency=request.POST.get("currency", invitation.rfq.currency).strip().upper(),
                minimum_order_quantity=_optional_int(request.POST.get("minimum_order_quantity")) or 1,
                sample_lead_days=_optional_int(request.POST.get("sample_lead_days")),
                valid_until=request.POST.get("valid_until") or None,
                notes=request.POST.get("notes", "").strip(),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                _localized(request, "Manufacturing quote submitted.", "تم إرسال عرض التصنيع."),
            )
            return _redirect_with_org("manufacturer-quote-detail", organization, pk=quote.pk)
    context.update({"invitation": invitation, "rfq": invitation.rfq, "quote": quote})
    return _render(request, "manufacturer/rfq_detail.html", context)


@login_required
def manufacturer_quotes(request):
    context = _require_active(request, roles=MANUFACTURER_QUOTE_ROLES)
    organization = context["manufacturer_organization"]
    quotes = (
        ManufacturerQuote.objects.filter(invitation__manufacturer=organization)
        .select_related("invitation__rfq", "invitation__rfq__designer_organization")
        .order_by("-updated_at")
    )
    context.update({"quotes": quotes})
    return _render(request, "manufacturer/quotes.html", context)


@login_required
def manufacturer_quote_detail(request, pk):
    context = _require_active(request, roles=MANUFACTURER_QUOTE_ROLES)
    organization = context["manufacturer_organization"]
    quote = get_object_or_404(
        ManufacturerQuote.objects.select_related(
            "invitation__rfq",
            "invitation__rfq__designer_organization",
            "invitation__rfq__designed_product",
        ),
        pk=pk,
        invitation__manufacturer=organization,
    )
    context.update({"quote": quote, "rfq": quote.invitation.rfq})
    return _render(request, "manufacturer/quote_detail.html", context)


@login_required
def manufacturer_production(request):
    context = _require_active(request, roles=MANUFACTURER_TECHNICAL_VIEW_ROLES)
    organization = context["manufacturer_organization"]
    jobs = _active_job_queryset(organization)
    status_filter = request.GET.get("status", "").strip()
    if status_filter in ProductionJob.Status.values:
        jobs = jobs.filter(status=status_filter)
    else:
        status_filter = ""
    context.update(
        {
            "jobs": jobs.order_by("-updated_at"),
            "status_filter": status_filter,
            "status_choices": ProductionJob.Status.choices,
        }
    )
    return _render(request, "manufacturer/production_list.html", context)


def _production_context(request, job):
    item = job.order.item
    product = item.store_product.designed_product
    garment_version = product.garment_version
    artwork_version = product.artwork_version
    design_assets = garment_version.assets.filter(
        kind__in=["pattern", "tech_pack", "3d", "technical"],
        media_asset__access="private",
    ).select_related("media_asset")
    artwork_sources = artwork_version.assets.filter(
        kind="source", media_asset__access="private"
    ).select_related("media_asset")
    size_rows = garment_version.size_rows.all()
    if item.size:
        selected_size_rows = size_rows.filter(size_label=item.size)
    else:
        selected_size_rows = size_rows.none()
    studio_elements = []
    if item.studio_project_id:
        studio_elements = list(
            CustomizationElement.objects.filter(
                customization__project_id=item.studio_project_id
            )
            .select_related(
                "decoration_zone",
                "media_asset",
                "artwork_version",
                "artwork_version__artwork",
            )
            .prefetch_related("artwork_version__assets__media_asset")
            .order_by("sort_order", "id")
        )
    fulfillment = getattr(job.order, "fulfillment", None)
    return {
        "job": job,
        "order": job.order,
        "item": item,
        "product": product,
        "garment_version": garment_version,
        "artwork_version": artwork_version,
        "placements": product.placements.select_related("decoration_zone").all(),
        "selected_size_rows": selected_size_rows,
        "design_assets": design_assets,
        "artwork_sources": artwork_sources,
        "studio_elements": studio_elements,
        "production_assets": job.assets.select_related("media_asset").all(),
        "fulfillment": fulfillment,
        "qc_inspections": job.qc_inspections.select_related("inspected_by").all(),
    }


@login_required
def manufacturer_production_detail(request, pk):
    context = _require_active(request, roles=MANUFACTURER_TECHNICAL_VIEW_ROLES)
    organization = context["manufacturer_organization"]
    job = get_object_or_404(_active_job_queryset(organization), pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "start":
                start_production(job=job, actor=request.user, request=request)
                messages.success(
                    request,
                    _localized(request, "Production started.", "تم بدء الإنتاج."),
                )
            elif action == "milestone":
                milestone = get_object_or_404(
                    ProductionMilestone,
                    pk=request.POST.get("milestone_id"),
                    job=job,
                )
                update_milestone(
                    milestone=milestone,
                    actor=request.user,
                    status=request.POST.get("status", ""),
                    notes=request.POST.get("notes", "").strip(),
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Production milestone updated.", "تم تحديث مرحلة الإنتاج."),
                )
            elif action == "request_qc":
                request_qc(job=job, actor=request.user, request=request)
                messages.success(
                    request,
                    _localized(request, "Job sent to quality control.", "تم إرسال المهمة لمراقبة الجودة."),
                )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("manufacturer-production-detail", organization, pk=job.pk)
    context.update(_production_context(request, job))
    return _render(request, "manufacturer/production_detail.html", context)


@login_required
def manufacturer_qc(request, pk):
    context = _require_active(request, roles=MANUFACTURER_QC_ROLES)
    organization = context["manufacturer_organization"]
    job = get_object_or_404(_active_job_queryset(organization), pk=pk)
    if request.method == "POST":
        checklist = {
            "inspection_reference": request.POST.get("inspection_reference", "").strip()
        }
        checklist = {key: value for key, value in checklist.items() if value}
        try:
            record_qc(
                job=job,
                actor=request.user,
                decision=request.POST.get("decision", ""),
                checklist=checklist,
                notes=request.POST.get("notes", "").strip(),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                _localized(request, "QC inspection recorded.", "تم تسجيل فحص الجودة."),
            )
            return _redirect_with_org("manufacturer-production-detail", organization, pk=job.pk)
    context.update(_production_context(request, job))
    context["qc_decisions"] = QCInspection.Decision.choices
    return _render(request, "manufacturer/qc.html", context)


@login_required
def manufacturer_ready_to_ship(request, pk):
    context = _require_active(request, roles=MANUFACTURER_PRODUCTION_ROLES)
    organization = context["manufacturer_organization"]
    job = get_object_or_404(_active_job_queryset(organization), pk=pk)
    fulfillment = getattr(job.order, "fulfillment", None)
    if not fulfillment:
        raise PermissionDenied("This job does not have a fulfillment record.")
    if request.method == "POST":
        try:
            pack_order(fulfillment=fulfillment, actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                _localized(
                    request,
                    "Order packed and ready to ship.",
                    "تمت تعبئة الطلب وأصبح جاهزًا للشحن.",
                ),
            )
            return _redirect_with_org("manufacturer-shipment", organization, pk=job.pk)
    context.update(_production_context(request, job))
    return _render(request, "manufacturer/ready_to_ship.html", context)


@login_required
def manufacturer_shipment(request, pk):
    context = _require_active(request, roles=MANUFACTURER_PRODUCTION_ROLES)
    organization = context["manufacturer_organization"]
    job = get_object_or_404(_active_job_queryset(organization), pk=pk)
    fulfillment = getattr(job.order, "fulfillment", None)
    if not fulfillment:
        raise PermissionDenied("This job does not have a fulfillment record.")
    if request.method == "POST":
        try:
            ship_order(
                fulfillment=fulfillment,
                actor=request.user,
                carrier=request.POST.get("carrier", ""),
                tracking_number=request.POST.get("tracking_number", ""),
                tracking_url=request.POST.get("tracking_url", ""),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                _localized(request, "Shipment recorded.", "تم تسجيل الشحنة."),
            )
            return _redirect_with_org("manufacturer-shipment", organization, pk=job.pk)
    shipping = job.order.shipping_snapshot or {}
    shipping_contact = {
        key: shipping.get(key, "")
        for key in (
            "name",
            "phone",
            "address1",
            "address2",
            "city",
            "region",
            "country",
            "postal_code",
        )
        if shipping.get(key, "")
    }
    context.update(_production_context(request, job))
    context["shipping_contact"] = shipping_contact
    return _render(request, "manufacturer/shipment.html", context)


@login_required
def manufacturer_finance(request):
    context = _require_active(request, roles=MANUFACTURER_FINANCE_ROLES)
    organization = context["manufacturer_organization"]
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action in {"save_payout", "submit_payout"}:
                update_payout_profile(
                    organization=organization,
                    actor=request.user,
                    method=request.POST.get("method", PayoutProfile.Method.BANK),
                    account_holder=request.POST.get("account_holder", ""),
                    destination_hint=request.POST.get("destination_hint", ""),
                    submit=action == "submit_payout",
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Payout profile saved.", "تم حفظ ملف التحويل."),
                )
            elif action == "request_settlement":
                request_settlement(
                    organization=organization,
                    actor=request.user,
                    amount=request.POST.get("amount", "0"),
                    currency=request.POST.get("currency", "EGP"),
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Settlement requested.", "تم طلب التسوية."),
                )
            elif action == "cancel_settlement":
                settlement = get_object_or_404(
                    SettlementRequest,
                    pk=request.POST.get("settlement_id"),
                    organization=organization,
                )
                cancel_settlement(
                    settlement=settlement,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    _localized(request, "Settlement cancelled.", "تم إلغاء التسوية."),
                )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("manufacturer-finance", organization)

    rows = []
    for account in FinanceAccount.objects.filter(organization=organization).order_by("currency"):
        rows.append(
            {
                "account": account,
                "balance": account_balance(account),
                "entries": account.ledger_entries.order_by("-created_at")[:30],
            }
        )
    payout_profile = PayoutProfile.objects.filter(organization=organization).first()
    settlements = SettlementRequest.objects.filter(organization=organization).order_by(
        "-requested_at"
    )[:50]
    context.update(
        {
            "finance_rows": rows,
            "payout_profile": payout_profile,
            "settlements": settlements,
            "payout_methods": PayoutProfile.Method.choices,
        }
    )
    return _render(request, "manufacturer/finance.html", context)
