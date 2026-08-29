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


@register.filter(name="mfr_ar")
def manufacturer_arabic_label(value, fallback=""):
    """Arabic presentation label for existing canonical choice values.

    This is intentionally presentation-only: persisted/model/API values remain unchanged.
    """
    key = "" if value is None else str(value)
    return _ARABIC_LABELS.get(key, fallback or key)
