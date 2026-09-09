import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.organizations.designer_context import designer_context
from .models import Notification, NotificationPreference

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _redirect_target(name, organization=None):
    if organization is None:
        return redirect(name)
    from django.urls import reverse

    return redirect(f"{reverse(name)}?org={organization.pk}")


def _notification_center(request, *, template_name, redirect_name, extra_context=None, organization=None):
    preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all_read":
            Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=timezone.now())
            messages.success(request, "تم تعليم جميع الإشعارات كمقروءة." if request.LANGUAGE_CODE == "ar" else "All notifications marked as read.")
            return _redirect_target(redirect_name, organization)
        if action == "preferences":
            email_enabled = request.POST.get("email_enabled") == "on"
            sms_enabled = request.POST.get("sms_enabled") == "on"
            phone = request.POST.get("phone_e164", "").strip()
            if email_enabled and not request.user.email:
                messages.error(request, "أضف بريدًا إلكترونيًا إلى حسابك قبل تفعيل إشعارات البريد." if request.LANGUAGE_CODE == "ar" else "Add an email address to your account before enabling email notifications.")
            elif sms_enabled and not E164.fullmatch(phone):
                messages.error(request, "أدخل رقم الهاتف بصيغة دولية صحيحة مثل +201000000000." if request.LANGUAGE_CODE == "ar" else "Enter a valid international phone number such as +201000000000.")
            else:
                preference.email_enabled = email_enabled
                preference.sms_enabled = sms_enabled
                preference.phone_e164 = phone
                preference.save(update_fields=["email_enabled", "sms_enabled", "phone_e164", "updated_at"])
                messages.success(request, "تم حفظ تفضيلات الإشعارات." if request.LANGUAGE_CODE == "ar" else "Notification preferences saved.")
                return _redirect_target(redirect_name, organization)

    notifications = Notification.objects.filter(recipient=request.user)[:100]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    context = {"notifications": notifications, "preference": preference, "unread_count": unread_count}
    if extra_context:
        context.update(extra_context)
    return render(request, template_name, context)


@login_required
def notification_center(request):
    return _notification_center(
        request,
        template_name="notifications/center.html",
        redirect_name="notifications",
    )


@login_required
def designer_notification_center(request):
    context = designer_context(request, required=True)
    organization = context["designer_organization"]
    return _notification_center(
        request,
        template_name="designer/notifications.html",
        redirect_name="designer-notifications",
        extra_context=context,
        organization=organization,
    )


@login_required
def manufacturer_notification_center(request):
    from apps.organizations.manufacturer_context import require_active_manufacturer_context

    context = require_active_manufacturer_context(request)
    response = _notification_center(
        request,
        template_name="manufacturer/notifications.html",
        redirect_name="manufacturer-notifications",
        extra_context=context,
        organization=context["manufacturer_organization"],
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
