from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from apps.platform_ops.maneg_views import _context, _render
from .models import PublicInquiry
from .services import add_inquiry_message, transition_public_inquiry


def _require(request, permission):
    if not request.user.has_perm(permission):
        raise PermissionDenied("Your staff account does not have permission for this V2-5 operation.")


def public_inquiry_queue(request):
    _require(request, "public_inquiries.view_publicinquiry")
    status = request.GET.get("status", "")
    qs = PublicInquiry.objects.select_related("target_organization", "sender_user").order_by("-created_at")
    if status in PublicInquiry.Status.values:
        qs = qs.filter(status=status)
    return _render(
        request,
        "maneg/v2_5_public_inquiries.html",
        **_context(
            request,
            section="organizations",
            title_en="Public inquiries",
            title_ar="الاستفسارات العامة",
            inquiries=qs[:200],
            selected_status=status,
            statuses=PublicInquiry.Status.choices,
        ),
    )


def public_inquiry_detail(request, pk):
    _require(request, "public_inquiries.view_publicinquiry")
    inquiry = get_object_or_404(
        PublicInquiry.objects.select_related(
            "target_organization",
            "sender_user",
            "garment_design",
            "artwork",
            "ready_product",
            "manufacturer_product_approval__store_product",
        ).prefetch_related("messages", "attachments__media_asset"),
        pk=pk,
    )
    if request.method == "POST":
        _require(request, "public_inquiries.change_publicinquiry")
        action = request.POST.get("action")
        try:
            if action == "respond":
                add_inquiry_message(
                    inquiry=inquiry,
                    actor=request.user,
                    body=request.POST.get("body"),
                    request=request,
                    professional=True,
                )
            elif action in {"handling", "close", "spam"}:
                target = {
                    "handling": PublicInquiry.Status.HANDLING,
                    "close": PublicInquiry.Status.CLOSED,
                    "spam": PublicInquiry.Status.SPAM,
                }[action]
                transition_public_inquiry(
                    inquiry=inquiry,
                    actor=request.user,
                    target_status=target,
                    request=request,
                    staff_notes=request.POST.get("staff_notes", ""),
                )
            else:
                raise ValidationError("Unsupported public-inquiry staff action.")
            messages.success(request, "Public inquiry updated.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-5-public-inquiry-detail", args=[inquiry.pk]))
    return _render(
        request,
        "maneg/v2_5_public_inquiry_detail.html",
        **_context(
            request,
            section="organizations",
            title_en="Public inquiry",
            title_ar="الاستفسار العام",
            inquiry=inquiry,
        ),
    )
