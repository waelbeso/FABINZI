from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.organizations.designer_context import DESIGNER_MANAGE_ROLES, require_active_designer_context
from apps.organizations.manufacturer_context import MANUFACTURER_MANAGE_ROLES, require_active_manufacturer_context
from .models import PublicInquiry
from .services import add_inquiry_message, transition_public_inquiry


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


def _context(request, kind):
    if kind == PublicInquiry.TargetKind.DESIGNER:
        context = require_active_designer_context(request, roles=DESIGNER_MANAGE_ROLES)
        return context, context["designer_organization"]
    context = require_active_manufacturer_context(request, roles=MANUFACTURER_MANAGE_ROLES)
    return context, context["manufacturer_organization"]


def _list(request, kind):
    context, organization = _context(request, kind)
    context["public_inquiries"] = PublicInquiry.objects.filter(target_organization=organization).order_by("-created_at")[:100]
    template = "public_inquiries/designer_portal_list.html" if kind == PublicInquiry.TargetKind.DESIGNER else "public_inquiries/manufacturer_portal_list.html"
    return render(request, template, context)


def _detail(request, kind, pk):
    context, organization = _context(request, kind)
    inquiry = get_object_or_404(
        PublicInquiry.objects.select_related("target_organization", "sender_user", "garment_design", "artwork", "ready_product", "manufacturer_product_approval__store_product").prefetch_related("messages", "attachments__media_asset"),
        pk=pk,
        target_organization=organization,
    )
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "respond":
                add_inquiry_message(inquiry=inquiry, actor=request.user, body=request.POST.get("body"), request=request, professional=True)
            elif action == "handling":
                transition_public_inquiry(inquiry=inquiry, actor=request.user, target_status=PublicInquiry.Status.HANDLING, request=request)
            elif action == "close":
                transition_public_inquiry(inquiry=inquiry, actor=request.user, target_status=PublicInquiry.Status.CLOSED, request=request)
            else:
                raise ValidationError("Unsupported inquiry action.")
            messages.success(request, "Inquiry updated inside FABINZI.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
        route = "designer-public-inquiry-detail" if kind == PublicInquiry.TargetKind.DESIGNER else "manufacturer-public-inquiry-detail"
        return redirect(f"{reverse(route, args=[inquiry.pk])}?org={organization.pk}")
    context["inquiry"] = inquiry
    template = "public_inquiries/designer_portal_detail.html" if kind == PublicInquiry.TargetKind.DESIGNER else "public_inquiries/manufacturer_portal_detail.html"
    return render(request, template, context)


@login_required
def designer_inquiries(request):
    return _list(request, PublicInquiry.TargetKind.DESIGNER)


@login_required
def designer_inquiry_detail(request, pk):
    return _detail(request, PublicInquiry.TargetKind.DESIGNER, pk)


@login_required
def manufacturer_inquiries(request):
    return _list(request, PublicInquiry.TargetKind.MANUFACTURER)


@login_required
def manufacturer_inquiry_detail(request, pk):
    return _detail(request, PublicInquiry.TargetKind.MANUFACTURER, pk)
