from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.http import HttpResponseRedirect

from apps.manufacturer_marketplace.models import ManufacturerCapability
from apps.organizations.models import Organization, PublicProfileRevision
from apps.organizations.public_profile_services import start_public_profile_review, review_public_profile_revision
from apps.platform_ops.maneg_views import _context, _render
from apps.storefront.models import StoreProduct
from .models import ManufacturerCapabilityVerification, ManufacturerPublicProductApproval, ProfessionalPublicState
from .services import approve_manufacturer_product, revoke_manufacturer_product, verify_manufacturer_capability, revoke_manufacturer_capability_verification


def _require(request, permission):
    if not request.user.has_perm(permission):
        raise PermissionDenied("Your staff account does not have permission for this V2-5 operation.")


def public_profile_queue(request):
    _require(request, "organizations.view_publicprofilerevision")
    revisions = PublicProfileRevision.objects.filter(
        status__in=[PublicProfileRevision.Status.SUBMITTED, PublicProfileRevision.Status.UNDER_REVIEW]
    ).select_related("organization", "reviewed_by").order_by("submitted_at", "id")[:100]
    pending_states = ProfessionalPublicState.objects.filter(
        visibility=ProfessionalPublicState.Visibility.PENDING_APPROVAL
    ).select_related("organization").order_by("updated_at")[:100]
    return _render(
        request,
        "maneg/v2_5_public_profiles.html",
        **_context(
            request,
            section="organizations",
            title_en="Public profile moderation",
            title_ar="مراجعة الملفات العامة",
            revisions=revisions,
            pending_states=pending_states,
        ),
    )


def public_profile_revision_detail(request, pk):
    _require(request, "organizations.view_publicprofilerevision")
    revision = get_object_or_404(PublicProfileRevision.objects.select_related("organization", "reviewed_by"), pk=pk)
    if request.method == "POST":
        _require(request, "organizations.change_publicprofilerevision")
        action = request.POST.get("action")
        try:
            if action == "start":
                start_public_profile_review(revision=revision, reviewer=request.user, request=request)
            elif action in {"approve", "changes_required", "reject"}:
                decision = {
                    "approve": PublicProfileRevision.Status.APPROVED,
                    "changes_required": PublicProfileRevision.Status.CHANGES_REQUIRED,
                    "reject": PublicProfileRevision.Status.REJECTED,
                }[action]
                review_public_profile_revision(
                    revision=revision,
                    reviewer=request.user,
                    decision=decision,
                    notes=request.POST.get("notes", ""),
                    request=request,
                )
            else:
                raise ValidationError("Unsupported public-profile moderation action.")
            messages.success(request, "Public-profile moderation state updated.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-5-public-profile-detail", args=[revision.pk]))
    return _render(
        request,
        "maneg/v2_5_public_profile_detail.html",
        **_context(
            request,
            section="organizations",
            title_en="Public profile revision",
            title_ar="مراجعة الملف العام",
            revision=revision,
        ),
    )


def manufacturer_public_controls(request):
    _require(request, "public_profiles.view_manufacturercapabilityverification")
    _require(request, "public_profiles.view_manufacturerpublicproductapproval")
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "verify_capability":
                _require(request, "public_profiles.change_manufacturercapabilityverification")
                capability = get_object_or_404(ManufacturerCapability, pk=request.POST.get("capability_id"))
                verify_manufacturer_capability(
                    capability=capability,
                    canonical_code=request.POST.get("canonical_code"),
                    reviewer=request.user,
                    notes=request.POST.get("notes", ""),
                    request=request,
                )
            elif action == "revoke_capability":
                _require(request, "public_profiles.change_manufacturercapabilityverification")
                verification = get_object_or_404(ManufacturerCapabilityVerification, pk=request.POST.get("verification_id"))
                revoke_manufacturer_capability_verification(
                    verification=verification,
                    reviewer=request.user,
                    notes=request.POST.get("notes", ""),
                    request=request,
                )
            elif action == "approve_product":
                _require(request, "public_profiles.change_manufacturerpublicproductapproval")
                manufacturer = get_object_or_404(Organization, pk=request.POST.get("manufacturer_id"), kind=Organization.Kind.MANUFACTURER)
                product = get_object_or_404(StoreProduct.objects.select_related("storefront", "designed_product"), pk=request.POST.get("store_product_id"))
                approve_manufacturer_product(
                    manufacturer=manufacturer,
                    store_product=product,
                    reviewer=request.user,
                    notes=request.POST.get("notes", ""),
                    request=request,
                )
            elif action == "revoke_product":
                _require(request, "public_profiles.change_manufacturerpublicproductapproval")
                approval = get_object_or_404(ManufacturerPublicProductApproval, pk=request.POST.get("approval_id"))
                revoke_manufacturer_product(
                    approval=approval,
                    reviewer=request.user,
                    notes=request.POST.get("notes", ""),
                    request=request,
                )
            else:
                raise ValidationError("Unsupported Manufacturer public-control action.")
            messages.success(request, "Manufacturer public-control state updated.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-5-manufacturer-public-controls"))

    capabilities = ManufacturerCapability.objects.filter(
        listing__organization__verification_status=Organization.VerificationStatus.ACTIVE,
        is_active=True,
    ).select_related("listing__organization").prefetch_related("public_verifications").order_by("listing__organization__display_name", "id")[:200]
    approvals = ManufacturerPublicProductApproval.objects.select_related(
        "manufacturer", "store_product__storefront", "store_product__designed_product"
    ).order_by("-updated_at")[:200]
    manufacturers = Organization.objects.filter(
        kind=Organization.Kind.MANUFACTURER,
        verification_status=Organization.VerificationStatus.ACTIVE,
    ).order_by("display_name")[:200]
    products = StoreProduct.objects.select_related("storefront", "designed_product").order_by("-updated_at")[:200]
    return _render(
        request,
        "maneg/v2_5_manufacturer_public_controls.html",
        **_context(
            request,
            section="organizations",
            title_en="Manufacturer public controls",
            title_ar="ضوابط الملف العام للمصنّع",
            capabilities=capabilities,
            approvals=approvals,
            manufacturers=manufacturers,
            products=products,
            canonical_choices=ManufacturerCapabilityVerification.CanonicalCode.choices,
        ),
    )
