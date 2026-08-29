from django import template

register = template.Library()

_AR = {
    "draft": "مسودة", "pending": "قيد الانتظار", "pending_payment": "بانتظار الدفع",
    "active": "نشط", "inactive": "غير نشط", "submitted": "مرسل للمراجعة",
    "revision_required": "مطلوب تعديل", "approved": "معتمد", "rejected": "مرفوض",
    "suspended": "موقوف", "open": "مفتوح", "under_review": "قيد المراجعة",
    "action_required": "إجراء مطلوب", "resolved": "تم الحل", "dismissed": "مغلق / مرفوض",
    "takedown": "إزالة", "restored": "مستعاد", "claim_rejected": "تم رفض المطالبة",
    "published": "منشور", "hidden": "مخفي", "archived": "مؤرشف", "paused": "متوقف مؤقتاً",
    "confirmed": "مؤكد", "payment_failed": "فشل الدفع", "cancelled": "ملغى", "refunded": "مسترد",
    "awaiting_assignment": "بانتظار إسناد المصنع", "queued": "في قائمة الانتظار",
    "in_production": "قيد الإنتاج", "qc_pending": "بانتظار الجودة", "qc_failed": "فشل الجودة",
    "ready_for_fulfillment": "جاهز للتنفيذ", "waiting_production": "بانتظار الإنتاج",
    "ready_to_pack": "جاهز للتعبئة", "packed": "معبأ", "shipped": "تم الشحن",
    "delivered": "تم التسليم", "failed": "فشل", "returned": "مرتجع",
    "requested": "مطلوب", "verified": "موثّق", "paid": "مدفوع",
    "success": "ناجح", "failure": "فشل", "never": "لم يُختبر",
    "enabled": "مفعّل", "disabled": "معطّل", "configured": "مُعدّ", "not_configured": "غير مُعدّ",
    "designer": "مصمم", "manufacturer": "مصنّع", "owner": "مالك", "manager": "مدير",
    "design_manager": "مدير التصميم", "accountant": "محاسب", "production_manager": "مدير الإنتاج",
    "operator": "مشغّل", "qc": "مراقبة الجودة", "staff": "فريق المنصة",
    "all": "الجميع", "customers": "العملاء", "designers": "المصممون", "manufacturers": "المصنّعون",
    "info": "معلومات", "warning": "تحذير", "maintenance": "صيانة", "critical": "حرج",
    "banner": "شريط تحذير فقط", "restrict": "تقييد الواجهات",
    "cod": "الدفع عند الاستلام", "paymob": "Paymob", "stripe": "Stripe", "mailgun": "Mailgun",
    "twilio": "Twilio", "amazon_s3": "Amazon S3", "cloudflare_images": "Cloudflare Images", "sentry": "Sentry",
}

_SENSITIVE = (
    "password", "secret", "token", "credential", "authorization", "api_key", "apikey",
    "webhook", "dsn", "database_url", "redis_url", "encryption", "private_key", "access_key",
)


def _sensitive_key(value):
    key = str(value or "").lower()
    return any(token in key for token in _SENSITIVE)


@register.filter(name="maneg_label")
def maneg_label(value, language="en"):
    raw = "" if value is None else str(value)
    if str(language).startswith("ar"):
        return _AR.get(raw, raw.replace("_", " "))
    return raw.replace("_", " ").capitalize()


@register.filter(name="maneg_tone")
def maneg_tone(value):
    value = str(value or "")
    if value in {"active", "approved", "published", "verified", "paid", "success", "delivered", "ready_for_fulfillment", "ready_to_pack", "packed", "shipped"}:
        return "success"
    if value in {"rejected", "suspended", "failed", "failure", "payment_failed", "qc_failed", "critical", "cancelled"}:
        return "danger"
    if value in {"pending", "submitted", "pending_payment", "revision_required", "requested", "warning", "under_review", "action_required", "qc_pending"}:
        return "warning"
    return "neutral"


@register.filter(name="mask_email")
def mask_email(value):
    value = str(value or "")
    if "@" not in value:
        return "—" if not value else value[:2] + "•••"
    local, domain = value.split("@", 1)
    return (local[:1] or "•") + "•••@" + domain


def _safe_scalar(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return text if len(text) <= 180 else text[:177] + "…"


def _flatten(data, prefix=""):
    rows = []
    if not isinstance(data, dict):
        return [{"key": prefix or "value", "value": _safe_scalar(data)}]
    for key, value in data.items():
        key_text = str(key)
        full = f"{prefix}.{key_text}" if prefix else key_text
        label = full.replace("_", " ")
        if _sensitive_key(key_text):
            rows.append({"key": label, "value": "Hidden"})
        elif isinstance(value, dict):
            rows.extend(_flatten(value, full))
        elif isinstance(value, (list, tuple)):
            safe_parts = []
            for index, item in enumerate(value[:12]):
                if isinstance(item, dict):
                    nested = _flatten(item, f"{full}[{index}]")
                    rows.extend(nested)
                elif isinstance(item, (list, tuple)):
                    safe_parts.append("[structured data]")
                else:
                    safe_parts.append(_safe_scalar(item))
            if safe_parts:
                rows.append({"key": label, "value": ", ".join(safe_parts)})
        else:
            rows.append({"key": label, "value": _safe_scalar(value)})
    return rows


@register.filter(name="safe_metadata")
def safe_metadata(value):
    return _flatten(value or {})


@register.filter(name="has_perm_name")
def has_perm_name(user, perm):
    return bool(user and user.has_perm(str(perm)))
