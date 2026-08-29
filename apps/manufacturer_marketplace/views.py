from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.organizations.models import Membership, Organization
from .models import ManufacturerListing, RFQ, RFQInvitation
from .services import MANUFACTURER_MANAGE_ROLES, get_or_create_listing


def manufacturer_marketplace(request):
    qs = ManufacturerListing.objects.filter(status=ManufacturerListing.Status.PUBLISHED, organization__verification_status=Organization.VerificationStatus.ACTIVE).select_related("organization").prefetch_related("capabilities","portfolio_assets")
    capability = request.GET.get("capability")
    if capability:
        qs = qs.filter(capabilities__capability_type=capability, capabilities__is_active=True).distinct()
    return render(request, "manufacturer_marketplace/marketplace.html", {"listings":qs,"capability_filter":capability or ""})


def manufacturer_public_detail(request, pk):
    listing=get_object_or_404(ManufacturerListing.objects.select_related("organization").prefetch_related("capabilities","portfolio_assets"),pk=pk,status=ManufacturerListing.Status.PUBLISHED,organization__verification_status=Organization.VerificationStatus.ACTIVE)
    return render(request,"manufacturer_marketplace/public_detail.html",{"listing":listing})


@login_required
def manufacturer_marketplace_dashboard(request):
    membership=Membership.objects.filter(user=request.user,is_active=True,organization__kind=Organization.Kind.MANUFACTURER).select_related("organization").first()
    if not membership:
        return render(request,"manufacturer_marketplace/manufacturer_dashboard.html",{"listing":None,"invitations":[]})
    listing=get_or_create_listing(organization=membership.organization,actor=request.user) if membership.role in MANUFACTURER_MANAGE_ROLES else getattr(membership.organization,"marketplace_listing",None)
    invitations=RFQInvitation.objects.filter(manufacturer=membership.organization).select_related("rfq","rfq__designer_organization").order_by("-sent_at")
    return render(request,"manufacturer_marketplace/manufacturer_dashboard.html",{"listing":listing,"invitations":invitations,"organization":membership.organization})


@login_required
def designer_rfq_dashboard(request):
    rfqs=RFQ.objects.filter(designer_organization__memberships__user=request.user,designer_organization__memberships__is_active=True).distinct().prefetch_related("invitations__quote")
    return render(request,"manufacturer_marketplace/designer_rfqs.html",{"rfqs":rfqs})
