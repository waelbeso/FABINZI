import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.artwork.designer_services import (
    add_validated_product_placement,
    delete_artwork_asset,
    delete_product_placement,
    update_artwork_definition,
    update_artwork_version_definition,
)
from apps.artwork.forms import ArtworkForm
from apps.artwork.models import (
    Artwork,
    ArtworkAsset,
    ArtworkPlacement,
    ArtworkVersion,
    DesignedProduct,
    IPCase,
    IPCaseEvidence,
    IPDeclaration,
)
from apps.artwork.public import public_artwork_queryset
from apps.artwork.services import (
    add_artwork_asset,
    add_ip_case_evidence,
    create_artwork,
    create_artwork_revision,
    create_designed_product,
    publish_designed_product,
    set_ip_declaration,
    submit_artwork_version,
)
from apps.design.designer_services import (
    delete_decoration_zone,
    delete_design_asset,
    delete_size_row,
    save_decoration_zone,
    save_size_row,
    update_version_definition,
)
from apps.design.forms import GarmentDesignForm
from apps.design.models import (
    DecorationZone,
    DesignAsset,
    GarmentDesign,
    GarmentDesignVersion,
    SizeChartRow,
)
from apps.design.services import (
    add_asset,
    create_design,
    create_revision,
    submit_version,
)
from apps.finance.models import FinanceAccount, LedgerEntry, OrderFinance, PayoutProfile, SettlementRequest
from apps.finance.services import (
    account_balance,
    cancel_settlement,
    request_settlement,
    update_payout_profile,
)
from apps.manufacturer_marketplace.models import ManufacturerListing, ManufacturerQuote, RFQ
from apps.manufacturer_marketplace.services import cancel_rfq, create_rfq, open_rfq, select_quote
from apps.media.designer_services import create_private_designer_asset
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord, ProductionJob
from apps.storefront.designer_services import (
    hide_store_product,
    pause_storefront,
    update_store_product,
    update_storefront_details,
    update_variant,
)
from apps.storefront.models import ProductVariant, StoreProduct, Storefront
from apps.storefront.services import (
    add_product_image,
    add_variant,
    create_store_product,
    create_storefront,
    publish_store_product,
    publish_storefront,
)
from .designer_context import (
    DESIGNER_APPROVAL_ROLES,
    DESIGNER_CREATIVE_ROLES,
    DESIGNER_FINANCE_ROLES,
    DESIGNER_MANAGE_ROLES,
    designer_context,
)
from .designer_services import (
    secure_add_or_update_member,
    secure_deactivate_member,
    update_active_designer_profile,
)
from .forms import DesignerOnboardingForm, OrganizationForm
from .models import Membership, OnboardingApplication, Organization
from .services import create_designer_onboarding, submit_application

User = get_user_model()


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _error_text(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(exc.messages)
    return str(exc)


def _parse_pairs(value):
    result = {}
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValidationError("Use one Key = Value entry per line.")
        key, val = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValidationError("Each entry requires a name before '='.")
        result[key] = val.strip()
    return result


def _pairs_text(value):
    return "\n".join(f"{key} = {val}" for key, val in (value or {}).items())


def _parse_list(value):
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def _positive_int(value, default=1):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _optional_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid whole number.") from exc


def _optional_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid monetary amount.") from exc


def _with_designer_context(request, extra=None, *, required=True):
    context = designer_context(request, required=required)
    if extra:
        context.update(extra)
    return context


def _require_active(request, *, roles=None):
    context = _with_designer_context(request)
    organization = context["designer_organization"]
    membership = context["designer_membership"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An approved active Designer organization is required.")
    if roles and membership.role not in set(roles):
        raise PermissionDenied("Your Designer role does not allow this action.")
    return context


def _redirect_with_org(name, organization, **kwargs):
    from django.urls import reverse
    url = reverse(name, kwargs=kwargs)
    return redirect(f"{url}?org={organization.pk}")


def _application_state_context(context):
    application = context.get("designer_application")
    organization = context.get("designer_organization")
    status = application.status if application else None
    return {
        "application": application,
        "organization": organization,
        "application_status": status,
        "can_edit_application": bool(application and status in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}),
        "can_submit_application": bool(application and status in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}),
    }


@login_required
def designer_portal(request):
    context = _with_designer_context(request, required=False)
    membership = context["designer_membership"]
    if not membership:
        if request.method == "POST":
            org_form = OrganizationForm(request.POST, prefix="org")
            profile_form = DesignerOnboardingForm(request.POST, prefix="profile")
            if org_form.is_valid() and profile_form.is_valid():
                profile_data = profile_form.cleaned_data.copy()
                profile_data.pop("accept_terms", None)
                profile_data["terms_accepted"] = True
                profile_data["terms_accepted_at"] = timezone.now()
                application = create_designer_onboarding(
                    user=request.user,
                    organization_data=org_form.cleaned_data.copy(),
                    profile_data=profile_data,
                    request=request,
                )
                request.session["designer_organization_id"] = application.organization_id
                messages.success(request, _localized(request, "Designer onboarding draft created.", "تم إنشاء مسودة انضمام المصمم."))
                return redirect("designer")
        else:
            org_form = OrganizationForm(prefix="org")
            profile_form = DesignerOnboardingForm(prefix="profile")
        context.update({"org_form": org_form, "profile_form": profile_form})
        return render(request, "designer/onboarding.html", context)

    organization = context["designer_organization"]
    application = context["designer_application"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        context.update(_application_state_context(context))
        return render(request, "designer/access_state.html", context)

    design_counts = dict(
        GarmentDesign.objects.filter(organization=organization)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    artwork_counts = dict(
        Artwork.objects.filter(organization=organization)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    product_counts = dict(
        DesignedProduct.objects.filter(organization=organization)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    published_store_products = StoreProduct.objects.filter(
        storefront__organization=organization,
        status=StoreProduct.Status.PUBLISHED,
    ).count()
    rfqs = RFQ.objects.filter(designer_organization=organization)
    open_rfq_count = rfqs.filter(status__in=[RFQ.Status.OPEN, RFQ.Status.QUOTED]).count()
    quote_decision_count = rfqs.filter(status=RFQ.Status.QUOTED, selection__isnull=True).count()
    active_fulfillment_count = FulfillmentRecord.objects.filter(
        order__designer_organization=organization,
    ).exclude(status__in=[FulfillmentRecord.Status.DELIVERED, FulfillmentRecord.Status.CANCELLED, FulfillmentRecord.Status.RETURNED]).count()

    attention = []
    for design in GarmentDesign.objects.filter(organization=organization, status=GarmentDesign.Status.REVISION_REQUIRED).only("id", "title")[:5]:
        attention.append({"label": design.title, "detail": _localized(request, "Garment design needs revision", "تصميم الملابس يحتاج إلى تعديل"), "url": f"/designer/designs/{design.pk}/?org={organization.pk}"})
    for artwork in Artwork.objects.filter(organization=organization, status=Artwork.Status.REVISION_REQUIRED).only("id", "title")[:5]:
        attention.append({"label": artwork.title, "detail": _localized(request, "Artwork needs revision", "العمل الفني يحتاج إلى تعديل"), "url": f"/designer/artworks/{artwork.pk}/?org={organization.pk}"})
    for rfq in rfqs.filter(status=RFQ.Status.QUOTED, selection__isnull=True).only("id", "title")[:5]:
        attention.append({"label": rfq.title, "detail": _localized(request, "Manufacturing quotes await a decision", "عروض التصنيع تنتظر قرارًا"), "url": f"/designer/rfqs/{rfq.pk}/?org={organization.pk}"})

    finance_rows = []
    if context["designer_can_finance"]:
        for account in FinanceAccount.objects.filter(organization=organization).order_by("currency"):
            finance_rows.append({"account": account, "balance": account_balance(account)})
        if not hasattr(organization, "finance_payout_profile"):
            attention.append({"label": _localized(request, "Payout setup", "إعداد التحويلات"), "detail": _localized(request, "Add your payout profile when you are ready to request settlements.", "أضف ملف التحويل عندما تكون مستعدًا لطلب تسوية."), "url": f"/designer/finance/?org={organization.pk}"})

    context.update({
        "design_counts": design_counts,
        "artwork_counts": artwork_counts,
        "product_counts": product_counts,
        "published_store_products": published_store_products,
        "open_rfq_count": open_rfq_count,
        "quote_decision_count": quote_decision_count,
        "active_fulfillment_count": active_fulfillment_count,
        "attention": attention,
        "finance_rows": finance_rows,
        "application": application,
    })
    return render(request, "designer/dashboard.html", context)


@login_required
def designer_profile(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    profile = organization.designer_profile
    if request.method == "POST":
        if not context["designer_can_manage"]:
            raise PermissionDenied
        social_links = {
            key: request.POST.get(key, "").strip()
            for key in ("instagram", "behance", "linkedin")
            if request.POST.get(key, "").strip()
        }
        try:
            update_active_designer_profile(
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
                },
                profile_data={
                    "studio_name": request.POST.get("studio_name", "").strip(),
                    "portfolio_url": request.POST.get("portfolio_url", "").strip(),
                    "social_links": social_links,
                },
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(request, _localized(request, "Designer profile updated.", "تم تحديث ملف المصمم."))
            return _redirect_with_org("designer-profile", organization)
    context.update({"profile": profile, "social_links": profile.social_links or {}})
    return render(request, "designer/profile.html", context)


@login_required
def designer_team(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    if request.method == "POST":
        if not context["designer_can_manage"]:
            raise PermissionDenied
        action = request.POST.get("action")
        try:
            if action == "upsert":
                email = request.POST.get("email", "").strip()
                user = get_object_or_404(User, email__iexact=email)
                role = request.POST.get("role", "")
                secure_add_or_update_member(
                    organization=organization,
                    actor=request.user,
                    user=user,
                    role=role,
                    request=request,
                )
                messages.success(request, _localized(request, "Team member updated.", "تم تحديث عضو الفريق."))
            elif action == "deactivate":
                membership = get_object_or_404(Membership, pk=request.POST.get("membership_id"), organization=organization)
                secure_deactivate_member(membership=membership, actor=request.user, request=request)
                messages.success(request, _localized(request, "Team member deactivated.", "تم إيقاف عضو الفريق."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("designer-team", organization)
    members = organization.memberships.select_related("user").order_by("joined_at", "id")
    allowed_roles = [choice for choice in Membership.Role.choices if choice[0] in {Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER, Membership.Role.ACCOUNTANT}]
    context.update({"members": members, "allowed_roles": allowed_roles})
    return render(request, "designer/team.html", context)


@login_required
def designer_design_list(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    qs = GarmentDesign.objects.filter(organization=organization)
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(category__icontains=q))
    if status_filter in GarmentDesign.Status.values:
        qs = qs.filter(status=status_filter)
    else:
        status_filter = ""
    if request.method == "POST":
        if context["designer_membership"].role not in DESIGNER_CREATIVE_ROLES:
            raise PermissionDenied
        form = GarmentDesignForm(request.POST)
        if form.is_valid():
            try:
                design = create_design(organization=organization, actor=request.user, request=request, **form.cleaned_data)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _error_text(exc))
            else:
                return _redirect_with_org("designer-design-detail", organization, pk=design.pk)
    else:
        form = GarmentDesignForm()
    page_obj = Paginator(qs.order_by("-updated_at"), 20).get_page(request.GET.get("page"))
    context.update({"page_obj": page_obj, "designs": page_obj.object_list, "search_query": q, "status_filter": status_filter, "status_choices": GarmentDesign.Status.choices, "form": form})
    return render(request, "designer/design_list.html", context)


@login_required
def designer_design_detail(request, pk):
    context = _require_active(request)
    organization = context["designer_organization"]
    design = get_object_or_404(GarmentDesign.objects.prefetch_related("versions"), pk=pk, organization=organization)
    selected_version_id = request.GET.get("version") or request.POST.get("version_id")
    version_qs = design.versions.prefetch_related("size_rows", "decoration_zones", "assets__media_asset", "reviews")
    version = get_object_or_404(version_qs, pk=selected_version_id) if selected_version_id else version_qs.order_by("-version_number").first()
    if not version:
        raise PermissionDenied("Garment Design has no version.")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "save_version":
                update_version_definition(version=version, actor=request.user, data={
                    "summary": request.POST.get("summary", "").strip(),
                    "base_material": request.POST.get("base_material", "").strip(),
                    "construction_notes": request.POST.get("construction_notes", "").strip(),
                    "technical_specs": _parse_pairs(request.POST.get("technical_specs", "")),
                }, request=request)
                messages.success(request, _localized(request, "Technical definition saved.", "تم حفظ التعريف الفني."))
            elif action == "create_revision":
                new_version = create_revision(design=design, actor=request.user, request=request)
                messages.success(request, _localized(request, "New revision created.", "تم إنشاء مراجعة جديدة."))
                return redirect(f"/designer/designs/{design.pk}/?org={organization.pk}&version={new_version.pk}")
            elif action == "submit_version":
                submit_version(version=version, actor=request.user, request=request)
                messages.success(request, _localized(request, "Version submitted for technical review.", "تم إرسال النسخة للمراجعة الفنية."))
            elif action == "save_size":
                row = get_object_or_404(SizeChartRow, pk=request.POST.get("row_id"), version=version) if request.POST.get("row_id") else None
                save_size_row(version=version, actor=request.user, row=row, size_label=request.POST.get("size_label", ""), measurements=_parse_pairs(request.POST.get("measurements", "")), notes=request.POST.get("notes", ""), sort_order=request.POST.get("sort_order", 0), request=request)
                messages.success(request, _localized(request, "Size row saved.", "تم حفظ صف المقاس."))
            elif action == "delete_size":
                delete_size_row(row=get_object_or_404(SizeChartRow, pk=request.POST.get("row_id"), version=version), actor=request.user, request=request)
            elif action == "save_zone":
                zone = get_object_or_404(DecorationZone, pk=request.POST.get("zone_id"), version=version) if request.POST.get("zone_id") else None
                save_decoration_zone(version=version, actor=request.user, zone=zone, name=request.POST.get("name", ""), method=request.POST.get("method", DecorationZone.Method.BOTH), placement={"x": request.POST.get("x", ""), "y": request.POST.get("y", "")}, max_width_mm=request.POST.get("max_width_mm", ""), max_height_mm=request.POST.get("max_height_mm", ""), notes=request.POST.get("notes", ""), request=request)
                messages.success(request, _localized(request, "Decoration Zone saved.", "تم حفظ منطقة الزخرفة."))
            elif action == "delete_zone":
                delete_decoration_zone(zone=get_object_or_404(DecorationZone, pk=request.POST.get("zone_id"), version=version), actor=request.user, request=request)
            elif action == "upload_asset":
                kind = request.POST.get("kind", "")
                asset_media = create_private_designer_asset(upload=request.FILES.get("file"), owner=request.user, organization=organization, purpose=f"design_{kind}")
                add_asset(version=version, actor=request.user, media_asset=asset_media, kind=kind, label=request.POST.get("label", ""), request=request)
                messages.success(request, _localized(request, "Design asset attached privately.", "تم إرفاق ملف التصميم بشكل خاص."))
            elif action == "delete_asset":
                delete_design_asset(asset=get_object_or_404(DesignAsset, pk=request.POST.get("asset_id"), version=version), actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return redirect(f"/designer/designs/{design.pk}/?org={organization.pk}&version={version.pk}")

    context.update({
        "design": design,
        "version": version,
        "versions": design.versions.order_by("-version_number"),
        "technical_specs_text": _pairs_text(version.technical_specs),
        "design_asset_kinds": DesignAsset.Kind.choices,
        "zone_methods": DecorationZone.Method.choices,
        "can_edit_version": version.status == GarmentDesignVersion.Status.DRAFT and context["designer_membership"].role in DESIGNER_CREATIVE_ROLES,
    })
    return render(request, "designer/design_detail.html", context)


@login_required
def designer_artworks(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    qs = Artwork.objects.filter(organization=organization).prefetch_related("versions")
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if status_filter in Artwork.Status.values:
        qs = qs.filter(status=status_filter)
    else:
        status_filter = ""
    if request.method == "POST":
        if context["designer_membership"].role not in DESIGNER_CREATIVE_ROLES:
            raise PermissionDenied
        form = ArtworkForm(request.POST)
        if form.is_valid():
            try:
                artwork = create_artwork(organization=organization, actor=request.user, request=request, **form.cleaned_data)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _error_text(exc))
            else:
                return _redirect_with_org("designer-artwork-detail", organization, pk=artwork.pk)
    else:
        form = ArtworkForm()
    page_obj = Paginator(qs.order_by("-updated_at"), 20).get_page(request.GET.get("page"))
    context.update({"page_obj": page_obj, "artworks": page_obj.object_list, "form": form, "search_query": q, "status_filter": status_filter, "status_choices": Artwork.Status.choices})
    return render(request, "designer/artwork_list.html", context)


@login_required
def designer_artwork_detail(request, pk):
    context = _require_active(request)
    organization = context["designer_organization"]
    artwork = get_object_or_404(Artwork, pk=pk, organization=organization)
    selected_version_id = request.GET.get("version") or request.POST.get("version_id")
    version_qs = artwork.versions.prefetch_related("assets__media_asset", "reviews")
    version = get_object_or_404(version_qs, pk=selected_version_id) if selected_version_id else version_qs.order_by("-version_number").first()
    if not version:
        raise PermissionDenied("Artwork has no version.")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "save_artwork":
                update_artwork_definition(artwork=artwork, version=version, actor=request.user, data={"title": request.POST.get("title", "").strip(), "description": request.POST.get("description", "").strip(), "tags": _parse_list(request.POST.get("tags", ""))}, request=request)
                update_artwork_version_definition(version=version, actor=request.user, data={"color_profile": request.POST.get("color_profile", "").strip(), "production_notes": request.POST.get("production_notes", "").strip()}, request=request)
                messages.success(request, _localized(request, "Artwork definition saved.", "تم حفظ تعريف العمل الفني."))
            elif action == "create_revision":
                new_version = create_artwork_revision(artwork=artwork, actor=request.user, request=request)
                return redirect(f"/designer/artworks/{artwork.pk}/?org={organization.pk}&version={new_version.pk}")
            elif action == "upload_asset":
                kind = request.POST.get("kind", "")
                media = create_private_designer_asset(upload=request.FILES.get("file"), owner=request.user, organization=organization, purpose=f"artwork_{kind}")
                add_artwork_asset(version=version, actor=request.user, media_asset=media, kind=kind, label=request.POST.get("label", ""), request=request)
                messages.success(request, _localized(request, "Artwork asset attached privately for workflow use.", "تم إرفاق ملف العمل الفني بشكل خاص للاستخدام في سير العمل."))
            elif action == "delete_asset":
                delete_artwork_asset(asset=get_object_or_404(ArtworkAsset, pk=request.POST.get("asset_id"), version=version), actor=request.user, request=request)
            elif action == "ip_declaration":
                set_ip_declaration(version=version, actor=request.user, rights_basis=request.POST.get("rights_basis", ""), rights_holder_name=request.POST.get("rights_holder_name", "").strip(), third_party_content=request.POST.get("third_party_content") == "on", details=request.POST.get("details", "").strip(), accepts_ip_policy=request.POST.get("accepts_ip_policy") == "on", request=request)
                messages.success(request, _localized(request, "IP declaration saved.", "تم حفظ إقرار الملكية الفكرية."))
            elif action == "submit_version":
                submit_artwork_version(version=version, actor=request.user, request=request)
                messages.success(request, _localized(request, "Artwork submitted for review.", "تم إرسال العمل الفني للمراجعة."))
            elif action == "add_case_evidence":
                case = get_object_or_404(IPCase.objects.filter(Q(artwork__organization=organization) | Q(designed_product__organization=organization)).distinct(), pk=request.POST.get("case_id"))
                media = create_private_designer_asset(upload=request.FILES.get("file"), owner=request.user, organization=organization, purpose="ip_case_evidence")
                add_ip_case_evidence(case=case, actor=request.user, media_asset=media, description=request.POST.get("description", ""), request=request)
                messages.success(request, _localized(request, "Evidence attached privately.", "تم إرفاق الدليل بشكل خاص."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return redirect(f"/designer/artworks/{artwork.pk}/?org={organization.pk}&version={version.pk}")

    try:
        declaration = version.ip_declaration
    except IPDeclaration.DoesNotExist:
        declaration = None
    ip_cases = IPCase.objects.filter(Q(artwork=artwork) | Q(designed_product__artwork_version__artwork=artwork)).select_related("designed_product").distinct()[:20]
    marketplace_public = public_artwork_queryset().filter(pk=artwork.pk).exists()
    context.update({
        "artwork": artwork,
        "version": version,
        "versions": artwork.versions.order_by("-version_number"),
        "declaration": declaration,
        "rights_basis_choices": IPDeclaration.RightsBasis.choices,
        "asset_kinds": ArtworkAsset.Kind.choices,
        "ip_cases": ip_cases,
        "marketplace_public": marketplace_public,
        "can_edit_version": version.status == ArtworkVersion.Status.DRAFT and context["designer_membership"].role in DESIGNER_CREATIVE_ROLES,
    })
    return render(request, "designer/artwork_detail.html", context)


@login_required
def designer_products(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    if request.method == "POST":
        if context["designer_membership"].role not in DESIGNER_CREATIVE_ROLES:
            raise PermissionDenied
        try:
            garment = get_object_or_404(GarmentDesignVersion, pk=request.POST.get("garment_version"), design__organization=organization, status=GarmentDesignVersion.Status.APPROVED)
            artwork_version = get_object_or_404(ArtworkVersion, pk=request.POST.get("artwork_version"), artwork__organization=organization, artwork__status=Artwork.Status.APPROVED, status=ArtworkVersion.Status.APPROVED)
            product = create_designed_product(organization=organization, actor=request.user, garment_version=garment, artwork_version=artwork_version, title=request.POST.get("title", "").strip(), description=request.POST.get("description", "").strip(), request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            return _redirect_with_org("designer-product-detail", organization, pk=product.pk)
    qs = DesignedProduct.objects.filter(organization=organization).select_related("garment_version__design", "artwork_version__artwork").prefetch_related("placements")
    context.update({
        "products": qs,
        "approved_garments": GarmentDesignVersion.objects.filter(design__organization=organization, status=GarmentDesignVersion.Status.APPROVED).select_related("design"),
        "approved_artworks": ArtworkVersion.objects.filter(artwork__organization=organization, artwork__status=Artwork.Status.APPROVED, status=ArtworkVersion.Status.APPROVED).select_related("artwork"),
    })
    return render(request, "designer/product_list.html", context)


@login_required
def designer_product_detail(request, pk):
    context = _require_active(request)
    organization = context["designer_organization"]
    product = get_object_or_404(DesignedProduct.objects.select_related("garment_version__design", "artwork_version__artwork").prefetch_related("placements__decoration_zone", "store_products__storefront"), pk=pk, organization=organization)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_placement":
                zone = get_object_or_404(DecorationZone, pk=request.POST.get("decoration_zone"), version=product.garment_version)
                add_validated_product_placement(product=product, actor=request.user, decoration_zone=zone, transform={"x": request.POST.get("x", .5), "y": request.POST.get("y", .5), "scale": request.POST.get("scale", .35), "rotation": request.POST.get("rotation", 0)}, production_method=request.POST.get("production_method", ""), request=request)
                messages.success(request, _localized(request, "Artwork placement added.", "تمت إضافة موضع العمل الفني."))
            elif action == "delete_placement":
                delete_product_placement(placement=get_object_or_404(ArtworkPlacement, pk=request.POST.get("placement_id"), product=product), actor=request.user, request=request)
            elif action == "publish":
                publish_designed_product(product=product, actor=request.user, request=request)
                messages.success(request, _localized(request, "Designed Product published.", "تم نشر المنتج المصمم."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("designer-product-detail", organization, pk=product.pk)
    context.update({"product": product, "zones": product.garment_version.decoration_zones.all(), "production_methods": [("print", "Print"), ("embroidery", "Embroidery")]})
    return render(request, "designer/product_detail.html", context)


@login_required
def designer_rfqs(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    if request.method == "POST":
        try:
            product = get_object_or_404(DesignedProduct, pk=request.POST.get("designed_product"), organization=organization, status=DesignedProduct.Status.PUBLISHED)
            rfq = create_rfq(
                designer_organization=organization,
                actor=request.user,
                designed_product=product,
                title=request.POST.get("title", "").strip(),
                quantity=_positive_int(request.POST.get("quantity")),
                size_breakdown=_parse_pairs(request.POST.get("size_breakdown", "")),
                color_requirements=_parse_list(request.POST.get("colors", "")),
                requested_methods=request.POST.getlist("requested_methods"),
                target_unit_price=_optional_decimal(request.POST.get("target_unit_price")),
                currency=request.POST.get("currency", "EGP"),
                desired_delivery_date=request.POST.get("desired_delivery_date") or None,
                delivery_country=request.POST.get("delivery_country", "EG"),
                delivery_city=request.POST.get("delivery_city", ""),
                notes=request.POST.get("notes", ""),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            return _redirect_with_org("designer-rfq-detail", organization, pk=rfq.pk)
    qs = RFQ.objects.filter(designer_organization=organization).select_related("designed_product").annotate(quote_count=Count("invitations__quote"))
    context.update({"rfqs": qs, "products": DesignedProduct.objects.filter(organization=organization, status=DesignedProduct.Status.PUBLISHED), "status_choices": RFQ.Status.choices})
    return render(request, "designer/rfq_list.html", context)


@login_required
def designer_rfq_detail(request, pk):
    context = _require_active(request)
    organization = context["designer_organization"]
    rfq = get_object_or_404(RFQ.objects.select_related("designed_product").prefetch_related("invitations__manufacturer", "invitations__quote"), pk=pk, designer_organization=organization)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "open":
                open_rfq(rfq=rfq, actor=request.user, manufacturer_ids=request.POST.getlist("manufacturers"), request=request)
                messages.success(request, _localized(request, "RFQ opened to selected manufacturers.", "تم فتح طلب عرض التصنيع للمصنعين المحددين."))
            elif action == "select_quote":
                quote = get_object_or_404(ManufacturerQuote, pk=request.POST.get("quote_id"), invitation__rfq=rfq)
                select_quote(quote=quote, actor=request.user, request=request)
                messages.success(request, _localized(request, "Manufacturer quote selected.", "تم اختيار عرض المصنع."))
            elif action == "cancel":
                cancel_rfq(rfq=rfq, actor=request.user, request=request)
                messages.success(request, _localized(request, "RFQ cancelled.", "تم إلغاء طلب عرض التصنيع."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("designer-rfq-detail", organization, pk=rfq.pk)
    manufacturers = ManufacturerListing.objects.filter(status=ManufacturerListing.Status.PUBLISHED, accepts_rfq=True, organization__verification_status=Organization.VerificationStatus.ACTIVE).select_related("organization").prefetch_related("capabilities")
    quotes = ManufacturerQuote.objects.filter(invitation__rfq=rfq).select_related("invitation__manufacturer").order_by("unit_price", "id")
    try:
        selection = rfq.selection
    except Exception:
        selection = None
    context.update({"rfq": rfq, "manufacturers": manufacturers, "quotes": quotes, "selection": selection})
    return render(request, "designer/rfq_detail.html", context)


@login_required
def designer_store(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    store = Storefront.objects.filter(organization=organization).prefetch_related("products__variants", "products__images").first()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "create" and not store:
                store = create_storefront(organization=organization, actor=request.user, slug=request.POST.get("slug", "").strip(), name_en=request.POST.get("name_en", "").strip(), name_ar=request.POST.get("name_ar", "").strip(), about_en=request.POST.get("about_en", "").strip(), about_ar=request.POST.get("about_ar", "").strip(), request=request)
            elif action == "update" and store:
                update_storefront_details(storefront=store, actor=request.user, data={"name_en": request.POST.get("name_en", "").strip(), "name_ar": request.POST.get("name_ar", "").strip(), "about_en": request.POST.get("about_en", "").strip(), "about_ar": request.POST.get("about_ar", "").strip()}, request=request)
            elif action == "publish" and store:
                publish_storefront(storefront=store, actor=request.user, request=request)
            elif action == "pause" and store:
                pause_storefront(storefront=store, actor=request.user, request=request)
            elif action == "create_product" and store:
                designed = get_object_or_404(DesignedProduct, pk=request.POST.get("designed_product"), organization=organization, status=DesignedProduct.Status.PUBLISHED)
                product = create_store_product(storefront=store, actor=request.user, designed_product=designed, slug=request.POST.get("slug", "").strip(), title_en=request.POST.get("title_en", "").strip(), title_ar=request.POST.get("title_ar", "").strip(), description_en=request.POST.get("description_en", "").strip(), description_ar=request.POST.get("description_ar", "").strip(), base_price=request.POST.get("base_price"), currency=request.POST.get("currency", "EGP"), customization_enabled=request.POST.get("customization_enabled") == "on", fulfillment_mode=request.POST.get("fulfillment_mode", StoreProduct.FulfillmentMode.MADE_TO_ORDER), lead_time_days=_optional_int(request.POST.get("lead_time_days")), request=request)
                return _redirect_with_org("designer-store-product", organization, pk=product.pk)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("designer-store", organization)
    context.update({"store": store, "designed_products": DesignedProduct.objects.filter(organization=organization, status=DesignedProduct.Status.PUBLISHED), "fulfillment_modes": StoreProduct.FulfillmentMode.choices})
    return render(request, "designer/store.html", context)


def _eligible_public_images(organization):
    return MediaAsset.objects.filter(
        access=MediaAsset.Access.PUBLIC,
        mime_type__startswith="image/",
    ).filter(
        Q(design_assets__version__design__organization=organization)
        | Q(artwork_assets__version__artwork__organization=organization)
        | Q(storefront_logos__organization=organization)
    ).distinct().order_by("-created_at")


@login_required
def designer_store_product(request, pk):
    context = _require_active(request)
    organization = context["designer_organization"]
    product = get_object_or_404(StoreProduct.objects.select_related("storefront", "designed_product").prefetch_related("variants", "images__media_asset"), pk=pk, storefront__organization=organization)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "update":
                update_store_product(product=product, actor=request.user, data={"title_en": request.POST.get("title_en", "").strip(), "title_ar": request.POST.get("title_ar", "").strip(), "description_en": request.POST.get("description_en", "").strip(), "description_ar": request.POST.get("description_ar", "").strip(), "base_price": request.POST.get("base_price"), "currency": request.POST.get("currency", "EGP").upper(), "fulfillment_mode": request.POST.get("fulfillment_mode", StoreProduct.FulfillmentMode.MADE_TO_ORDER), "lead_time_days": _optional_int(request.POST.get("lead_time_days")), "customization_enabled": request.POST.get("customization_enabled") == "on"}, request=request)
            elif action == "hide":
                hide_store_product(product=product, actor=request.user, request=request)
            elif action == "publish":
                publish_store_product(product=product, actor=request.user, request=request)
            elif action == "add_variant":
                add_variant(product=product, actor=request.user, sku=request.POST.get("sku", "").strip(), size=request.POST.get("size", "").strip(), color_name=request.POST.get("color_name", "").strip(), color_hex=request.POST.get("color_hex", "").strip(), price_adjustment=request.POST.get("price_adjustment") or 0, stock_quantity=_optional_int(request.POST.get("stock_quantity")), request=request)
            elif action == "update_variant":
                variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant_id"), product=product)
                update_variant(variant=variant, actor=request.user, data={"sku": request.POST.get("sku", "").strip(), "size": request.POST.get("size", "").strip(), "color_name": request.POST.get("color_name", "").strip(), "color_hex": request.POST.get("color_hex", "").strip(), "price_adjustment": request.POST.get("price_adjustment") or 0, "stock_quantity": _optional_int(request.POST.get("stock_quantity")), "is_active": request.POST.get("is_active") == "on"}, request=request)
            elif action == "add_image":
                media = get_object_or_404(_eligible_public_images(organization), pk=request.POST.get("media_asset"))
                add_product_image(product=product, actor=request.user, media_asset=media, alt_en=request.POST.get("alt_en", ""), alt_ar=request.POST.get("alt_ar", ""), request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("designer-store-product", organization, pk=product.pk)
    context.update({"product": product, "fulfillment_modes": StoreProduct.FulfillmentMode.choices, "public_images": _eligible_public_images(organization)[:100]})
    return render(request, "designer/store_product.html", context)


@login_required
def designer_fulfillment(request):
    context = _require_active(request)
    organization = context["designer_organization"]
    records = FulfillmentRecord.objects.filter(order__designer_organization=organization).select_related(
        "order",
        "order__purchase",
        "order__item__store_product",
        "order__production_job__manufacturer",
    ).order_by("-updated_at")
    context.update({"records": records})
    return render(request, "designer/fulfillment.html", context)


@login_required
def designer_finance(request):
    context = _require_active(request, roles=DESIGNER_FINANCE_ROLES)
    organization = context["designer_organization"]
    profile = PayoutProfile.objects.filter(organization=organization).first()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "payout_profile":
                profile = update_payout_profile(organization=organization, actor=request.user, method=request.POST.get("method", PayoutProfile.Method.BANK), account_holder=request.POST.get("account_holder", "").strip(), destination_hint=request.POST.get("destination_hint", "").strip(), submit=request.POST.get("submit_for_verification") == "on", request=request)
                messages.success(request, _localized(request, "Payout profile saved.", "تم حفظ ملف التحويل."))
            elif action == "settlement":
                request_settlement(organization=organization, actor=request.user, amount=request.POST.get("amount"), currency=request.POST.get("currency", "EGP"), request=request)
                messages.success(request, _localized(request, "Settlement request submitted.", "تم إرسال طلب التسوية."))
            elif action == "cancel_settlement":
                settlement = get_object_or_404(SettlementRequest, pk=request.POST.get("settlement_id"), organization=organization)
                cancel_settlement(settlement=settlement, actor=request.user, request=request)
                messages.success(request, _localized(request, "Settlement request cancelled.", "تم إلغاء طلب التسوية."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        return _redirect_with_org("designer-finance", organization)

    accounts = list(FinanceAccount.objects.filter(organization=organization).order_by("currency"))
    rows = [{"account": account, "balance": account_balance(account)} for account in accounts]
    account_ids = [account.pk for account in accounts]
    order_finance = OrderFinance.objects.filter(designer_account_id__in=account_ids).select_related("order").order_by("-recognized_at")[:100]
    ledger = LedgerEntry.objects.filter(account_id__in=account_ids).select_related("order_finance", "settlement").order_by("-created_at")[:150]
    settlements = SettlementRequest.objects.filter(organization=organization).select_related("payout_profile").order_by("-requested_at")[:100]
    context.update({"finance_rows": rows, "payout_profile": profile, "order_finance": order_finance, "ledger": ledger, "settlements": settlements, "payout_methods": PayoutProfile.Method.choices})
    return render(request, "designer/finance.html", context)
