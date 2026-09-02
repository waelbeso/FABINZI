from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.models import Organization
from apps.public_profiles.services import approved_manufacturer_products, public_professional_queryset
from .models import PublicInquiry
from .services import add_inquiry_message, can_view_inquiry, designer_public_references, request_email_challenge, submit_public_inquiry, verify_email_challenge


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


def _target(kind, slug):
    org_kind = Organization.Kind.DESIGNER if kind == PublicInquiry.TargetKind.DESIGNER else Organization.Kind.MANUFACTURER
    return get_object_or_404(public_professional_queryset(kind=org_kind), public_state__slug=slug)


def _submission_data(post):
    data = post.copy()
    work_ref = str(post.get("work_ref") or "")
    if ":" in work_ref:
        work_kind, work_id = work_ref.split(":", 1)
        data["work_kind"] = work_kind
        data["work_id"] = work_id
    return data


def _inquiry_form(request, *, kind, slug):
    target = _target(kind, slug)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "send_otp":
                challenge = request_email_challenge(request=request, email=request.POST.get("email"))
                request.session["public_inquiry_challenge"] = str(challenge.reference)
                messages.success(request, "Verification code sent.")
            elif action == "verify_otp":
                reference = request.POST.get("challenge_reference") or request.session.get("public_inquiry_challenge")
                verify_email_challenge(request=request, reference=reference, email=request.POST.get("email"), otp=request.POST.get("otp"))
                messages.success(request, "Email verified for this browser session.")
            elif action == "submit":
                inquiry = submit_public_inquiry(request=request, target_organization=target, data=_submission_data(request.POST), attachment=request.FILES.get("attachment"))
                return redirect("public-inquiry-status", reference=inquiry.reference)
            else:
                raise ValidationError("Unsupported inquiry action.")
        except (ValidationError, PermissionDenied, ValueError) as exc:
            messages.error(request, _error(exc))
    context = {"target": target, "target_kind": kind, "challenge_reference": request.session.get("public_inquiry_challenge", ""), "verified_email_marker": request.session.get("public_inquiry_verified_email") or {}}
    if kind == PublicInquiry.TargetKind.DESIGNER:
        context["designer_references"] = designer_public_references(target)
    else:
        context["manufacturer_products"] = approved_manufacturer_products(target)
    return render(request, "public_inquiries/form.html", context)


def designer_inquiry(request, slug):
    return _inquiry_form(request, kind=PublicInquiry.TargetKind.DESIGNER, slug=slug)


def manufacturer_inquiry(request, slug):
    return _inquiry_form(request, kind=PublicInquiry.TargetKind.MANUFACTURER, slug=slug)


def public_inquiry_status(request, reference):
    inquiry = get_object_or_404(PublicInquiry.objects.select_related("target_organization", "sender_user"), reference=reference)
    if not can_view_inquiry(request, inquiry):
        raise Http404
    if request.method == "POST":
        try:
            add_inquiry_message(inquiry=inquiry, actor=request.user if getattr(request.user, "is_authenticated", False) else None, body=request.POST.get("body"), request=request, professional=False)
            messages.success(request, "Message added inside FABINZI.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
        return redirect("public-inquiry-status", reference=inquiry.reference)
    return render(request, "public_inquiries/status.html", {"inquiry": inquiry})
