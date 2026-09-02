from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.design.models import GarmentDesignVersion
from apps.design.services import evaluate_version_eligibility
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access
from .models import ArtworkPlacement, ArtworkVersion, DesignedProduct
from .services import add_product_placement, create_designed_product, evaluate_designed_product_eligibility, publish_designed_product


def _designer_orgs(user):
    return Organization.objects.filter(
        kind=Organization.Kind.DESIGNER,
        verification_status=Organization.VerificationStatus.ACTIVE,
        memberships__user=user,
        memberships__is_active=True,
    ).distinct()


def _float(value, field):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid normalized number."}) from exc


@login_required
def designer_ready_product_composer(request):
    organizations = _designer_orgs(request.user)
    garment_versions = GarmentDesignVersion.objects.filter(
        design__organization__in=organizations,
        status=GarmentDesignVersion.Status.APPROVED,
    ).select_related("design__organization")
    garment_versions = [row for row in garment_versions if evaluate_version_eligibility(row)["commercial_eligible"]]
    artwork_versions = ArtworkVersion.objects.filter(
        artwork__status="approved",
        status=ArtworkVersion.Status.APPROVED,
        technical_check_status=ArtworkVersion.TechnicalCheckStatus.PASS,
    ).select_related("artwork__organization")

    if request.method == "POST":
        try:
            garment_version = get_object_or_404(GarmentDesignVersion, pk=request.POST.get("garment_version_id"))
            organization = garment_version.design.organization
            if organization not in organizations:
                raise ValidationError("Ready Designed Product must be created by the canonical Garment Design Organization.")
            require_org_access(
                request.user,
                organization,
                roles=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER],
            )
            artwork_version = get_object_or_404(
                ArtworkVersion,
                pk=request.POST.get("artwork_version_id"),
                artwork__status="approved",
                status=ArtworkVersion.Status.APPROVED,
                technical_check_status=ArtworkVersion.TechnicalCheckStatus.PASS,
            )
            product = create_designed_product(
                organization=organization,
                actor=request.user,
                garment_version=garment_version,
                artwork_version=artwork_version,
                title=request.POST.get("title") or f"{garment_version.design.title} + {artwork_version.artwork.title}",
                description=request.POST.get("description", ""),
                request=request,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            return redirect("designer-ready-product-composer-detail-v2-4", pk=product.pk)

    return render(
        request,
        "designer/ready_product_composer_v2_4.html",
        {"organizations": organizations, "garment_versions": garment_versions, "artwork_versions": artwork_versions},
    )


@login_required
def designer_ready_product_composer_detail(request, pk):
    product = get_object_or_404(DesignedProduct.objects.select_related("organization", "garment_version__design", "artwork_version__artwork"), pk=pk)
    require_org_access(
        request.user,
        product.organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER],
    )
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "add_placement":
                zone = get_object_or_404(product.garment_version.decoration_zones, pk=request.POST.get("zone_id"))
                transform = {
                    "x": _float(request.POST.get("x"), "x"),
                    "y": _float(request.POST.get("y"), "y"),
                    "width": _float(request.POST.get("width"), "width"),
                    "height": _float(request.POST.get("height"), "height"),
                    "rotation": _float(request.POST.get("rotation") or 0, "rotation"),
                }
                add_product_placement(
                    product=product,
                    actor=request.user,
                    decoration_zone=zone,
                    transform=transform,
                    production_method=request.POST.get("production_method"),
                    request=request,
                )
            elif action == "publish":
                publish_designed_product(product=product, actor=request.user, request=request)
            else:
                raise ValidationError("Unsupported Ready Designed Product action.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            messages.success(request, "Ready Designed Product updated.")
        return redirect("designer-ready-product-composer-detail-v2-4", pk=product.pk)

    return render(
        request,
        "designer/ready_product_composer_detail_v2_4.html",
        {
            "product": product,
            "eligibility": evaluate_designed_product_eligibility(product),
            "zones": product.garment_version.decoration_zones.all(),
            "production_methods": ArtworkPlacement.ProductionMethod.choices,
        },
    )
