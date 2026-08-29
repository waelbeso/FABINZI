from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


_ARABIC_LABELS = {
    # Organization / onboarding
    "draft": "مسودة",
    "pending": "قيد الانتظار",
    "active": "نشط",
    "rejected": "مرفوض",
    "suspended": "موقوف",
    "submitted": "مرسل",
    "revision_required": "مطلوب تعديل",
    "approved": "معتمد",
    # Membership roles
    "owner": "مالك",
    "manager": "مدير",
    "designer": "مصمم",
    "design_manager": "مدير التصميم",
    "accountant": "محاسب",
    "production_manager": "مدير الإنتاج",
    "operator": "مشغّل",
    "qc": "مراقبة الجودة",
    # RFQ / quote
    "open": "مفتوح",
    "selected": "تم اختيار المصنع",
    "closed": "مغلق",
    "invited": "مدعو",
    "viewed": "تمت المشاهدة",
    "declined": "مرفوض",
    "quoted": "تم تقديم عرض",
    "withdrawn": "مسحوب",
    "accepted": "مقبول",
    "expired": "منتهي",
    # Production job
    "awaiting_assignment": "بانتظار إسناد المصنع",
    "queued": "في قائمة الانتظار",
    "in_production": "قيد الإنتاج",
    "qc_pending": "بانتظار فحص الجودة",
    "qc_failed": "فشل فحص الجودة",
    "ready_for_fulfillment": "جاهز للتنفيذ",
    "cancelled": "ملغى",
    # Production milestones
    "materials": "المواد",
    "cutting": "القص",
    "assembly": "التجميع / الخياطة",
    "decoration": "الطباعة / التطريز",
    "finishing": "التشطيب",
    "in_progress": "قيد التنفيذ",
    "completed": "مكتمل",
    "blocked": "متوقف",
    # QC
    "passed": "ناجح",
    "failed": "فشل",
    "rework": "إعادة العمل مطلوبة",
    # Fulfillment
    "waiting_production": "بانتظار الإنتاج",
    "ready_to_pack": "جاهز للتعبئة",
    "packed": "معبأ",
    "shipped": "تم الشحن",
    "delivered": "تم التسليم",
    "returned": "مرتجع",
    # Finance
    "bank": "تحويل بنكي",
    "manual": "تسوية يدوية",
    "verified": "موثّق",
    "requested": "تم الطلب",
    "paid": "مدفوع",
    "manufacturer_earning": "أرباح المصنع",
    "designer_earning": "أرباح المصمم",
    "platform_fee": "رسوم المنصة",
    "settlement": "تسوية",
    "adjustment": "تعديل",
    "reversal": "عكس قيد",
    # Production methods / Studio kinds used inside jobs
    "print": "طباعة",
    "embroidery": "تطريز",
    "both": "طباعة وتطريز",
    "text": "نص",
    "image": "صورة عميل",
    "artwork": "عمل فني",
    # Manufacturer capability classes
    "cut_sew": "قص وخياطة",
    "sampling": "إعداد عينات",
    "pattern": "إعداد الباترون",
    "packaging": "تعبئة وتغليف",
    "other": "أخرى",
}

_MEASUREMENT_LABELS = {
    "chest": ("Chest", "الصدر"),
    "length": ("Length", "الطول"),
    "body_length": ("Body length", "طول الجسم"),
    "waist": ("Waist", "الخصر"),
    "hip": ("Hip", "الورك"),
    "hips": ("Hips", "الأوراك"),
    "shoulder": ("Shoulder", "الكتف"),
    "shoulder_width": ("Shoulder width", "عرض الكتفين"),
    "sleeve": ("Sleeve", "الكم"),
    "sleeve_length": ("Sleeve length", "طول الكم"),
    "neck": ("Neck", "الرقبة"),
    "inseam": ("Inseam", "طول الساق الداخلي"),
    "outseam": ("Outseam", "طول الساق الخارجي"),
    "rise": ("Rise", "ارتفاع الحجر"),
    "width": ("Width", "العرض"),
    "height": ("Height", "الارتفاع"),
}

_UNIT_LABELS = {
    "cm": ("cm", "سم"),
    "mm": ("mm", "مم"),
    "in": ("in", "بوصة"),
    "kg": ("kg", "كجم"),
    "g": ("g", "جم"),
}

_TRANSFORM_LABELS = {
    "x": ("X", "X"),
    "y": ("Y", "Y"),
    "scale": ("Scale", "المقياس"),
    "rotation": ("Rotation", "الدوران"),
}
_TRANSFORM_ORDER = ("x", "y", "scale", "rotation")


def _is_arabic(language):
    return str(language or "").lower().startswith("ar")


def _fallback_label(key):
    text = str(key or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Value"


def _measurement_label(key, language):
    key = str(key or "")
    parts = key.split("_")
    unit_key = parts[-1].lower() if len(parts) > 1 and parts[-1].lower() in _UNIT_LABELS else ""
    base_key = "_".join(parts[:-1]) if unit_key else key
    labels = _MEASUREMENT_LABELS.get(base_key.lower())
    if labels:
        label = labels[1] if _is_arabic(language) else labels[0]
    else:
        label = _fallback_label(base_key)
    if unit_key:
        unit_labels = _UNIT_LABELS[unit_key]
        unit = unit_labels[1] if _is_arabic(language) else unit_labels[0]
    else:
        unit = ""
    return label, unit


def _safe_scalar(value, language):
    if value is None:
        return "—"
    if isinstance(value, Mapping):
        parts = []
        for key, nested in value.items():
            parts.append(f"{_fallback_label(key)}: {_safe_scalar(nested, language)}")
        return "; ".join(parts)
    if isinstance(value, (list, tuple)):
        return ", ".join(_safe_scalar(item, language) for item in value)
    if isinstance(value, bool):
        if _is_arabic(language):
            return "نعم" if value else "لا"
        return "Yes" if value else "No"
    return str(value)


def _flatten_measurements(measurements, language, prefix=()):
    rows = []
    for raw_key, value in measurements.items():
        key = str(raw_key)
        path = prefix + (key,)
        if isinstance(value, Mapping):
            rows.extend(_flatten_measurements(value, language, path))
            continue
        label, unit = _measurement_label(key, language)
        if prefix:
            parent_label = " / ".join(_fallback_label(item) for item in prefix)
            label = f"{parent_label} / {label}"
        rows.append(
            {
                "key": ".".join(path),
                "label": label,
                "value": _safe_scalar(value, language),
                "unit": unit,
            }
        )
    return rows


def _decimal_text(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@register.filter(name="mfr_ar")
def manufacturer_arabic_label(value, fallback=""):
    """Arabic presentation label for existing canonical choice values.

    This is intentionally presentation-only: persisted/model/API values remain unchanged.
    """
    key = "" if value is None else str(value)
    return _ARABIC_LABELS.get(key, fallback or key)


@register.simple_tag(name="mfr_measurement_rows")
def manufacturer_measurement_rows(measurements, language="en"):
    """Return persisted size-chart measurements as human-readable technical rows."""
    if isinstance(measurements, Mapping):
        return _flatten_measurements(measurements, language)
    return [
        {
            "key": "value",
            "label": "القيمة" if _is_arabic(language) else "Value",
            "value": _safe_scalar(measurements, language),
            "unit": "",
        }
    ]


@register.simple_tag(name="mfr_transform_rows")
def manufacturer_transform_rows(transform, language="en"):
    """Return persisted normalized transform values without changing physical semantics."""
    if not isinstance(transform, Mapping):
        return [
            {
                "key": "value",
                "label": "القيمة" if _is_arabic(language) else "Value",
                "value": _safe_scalar(transform, language),
            }
        ]

    rows = []
    seen = set()
    for key in _TRANSFORM_ORDER:
        if key not in transform:
            continue
        seen.add(key)
        labels = _TRANSFORM_LABELS[key]
        label = labels[1] if _is_arabic(language) else labels[0]
        value = transform[key]
        if key in {"x", "y", "scale"}:
            try:
                display = f"{_decimal_text(Decimal(str(value)) * Decimal('100'))}%"
            except (InvalidOperation, TypeError, ValueError):
                display = _safe_scalar(value, language)
        elif key == "rotation":
            display = f"{_decimal_text(value)}°"
        else:
            display = _safe_scalar(value, language)
        rows.append({"key": key, "label": label, "value": display})

    for raw_key, value in transform.items():
        key = str(raw_key)
        if key in seen:
            continue
        rows.append(
            {
                "key": key,
                "label": _fallback_label(key),
                "value": _safe_scalar(value, language),
            }
        )
    return rows
