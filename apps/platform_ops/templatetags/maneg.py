import re

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

# These labels are presentation-only. AuditEvent.action remains the canonical,
# queryable value written by the domain services.
_AUDIT_ACTION_LABELS = {
    "control_center.user.suspended": ("User suspended", "تم إيقاف المستخدم"),
    "control_center.organization.suspended": ("Organization suspended", "تم إيقاف المنظمة"),
    "platform_ops.platformannouncement.updated": ("Announcement updated", "تم تحديث الإعلان"),
    "platform_ops.maintenancewindow.updated": ("Maintenance settings updated", "تم تحديث إعدادات الصيانة"),
    "integration.config.updated": ("Integration configuration updated", "تم تحديث إعداد التكامل"),
    "integration.connection.tested": ("Integration connection tested", "تم اختبار اتصال التكامل"),
    "onboarding.designer.created": ("Designer onboarding created", "تم إنشاء طلب انضمام المصمم"),
    "onboarding.manufacturer.created": ("Manufacturer onboarding created", "تم إنشاء طلب انضمام المصنع"),
    "onboarding.submitted": ("Onboarding submitted", "تم إرسال طلب الانضمام"),
    "onboarding.approved": ("Onboarding approved", "تم اعتماد طلب الانضمام"),
    "onboarding.rejected": ("Onboarding rejected", "تم رفض طلب الانضمام"),
    "onboarding.revision_required": ("Onboarding revision requested", "تم طلب تعديل طلب الانضمام"),
    "onboarding.updated": ("Onboarding updated", "تم تحديث طلب الانضمام"),
    "business.member.upserted": ("Business member updated", "تم تحديث عضو المنظمة"),
    "business.member.deactivated": ("Business member deactivated", "تم إيقاف عضو المنظمة"),
    "design.created": ("Garment design created", "تم إنشاء تصميم قطعة"),
    "design.revision.created": ("Garment design revision created", "تم إنشاء مراجعة لتصميم القطعة"),
    "design.version.submitted": ("Garment design submitted", "تم إرسال تصميم القطعة للمراجعة"),
    "design.version.approved": ("Garment design approved", "تم اعتماد تصميم القطعة"),
    "design.version.revision_required": ("Garment design revision requested", "تم طلب تعديل تصميم القطعة"),
    "design.version.rejected": ("Garment design rejected", "تم رفض تصميم القطعة"),
    "design.asset.added": ("Design asset added", "تمت إضافة ملف تصميم"),
    "artwork.preview.revoked": ("Artwork public preview revoked", "تم إلغاء المعاينة العامة للعمل الفني"),
    "artwork.preview.published": ("Artwork public preview published", "تم نشر المعاينة العامة للعمل الفني"),
    "artwork.created": ("Artwork created", "تم إنشاء العمل الفني"),
    "artwork.revision.created": ("Artwork revision created", "تم إنشاء مراجعة للعمل الفني"),
    "artwork.asset.added": ("Artwork asset added", "تمت إضافة ملف للعمل الفني"),
    "artwork.ip.declared": ("Artwork rights declared", "تم تسجيل إقرار حقوق العمل الفني"),
    "artwork.version.submitted": ("Artwork submitted", "تم إرسال العمل الفني للمراجعة"),
    "artwork.version.approved": ("Artwork approved", "تم اعتماد العمل الفني"),
    "artwork.version.revision_required": ("Artwork revision requested", "تم طلب تعديل العمل الفني"),
    "artwork.version.rejected": ("Artwork rejected", "تم رفض العمل الفني"),
    "designed_product.created": ("Designed product created", "تم إنشاء المنتج المصمم"),
    "designed_product.placement.added": ("Artwork placement added", "تمت إضافة موضع للعمل الفني"),
    "designed_product.published": ("Designed product published", "تم نشر المنتج المصمم"),
    "ip_case.created": ("IP case created", "تم إنشاء قضية حقوق ملكية"),
    "ip_case.moderated": ("IP case moderated", "تمت مراجعة قضية حقوق الملكية"),
    "finance.order.recognized": ("Order finance recognized", "تم إثبات مالية الطلب"),
    "finance.payout_profile.submitted": ("Payout profile submitted", "تم إرسال ملف التحويل للمراجعة"),
    "finance.payout_profile.updated": ("Payout profile updated", "تم تحديث ملف التحويل"),
    "finance.payout_profile.verified": ("Payout profile verified", "تم توثيق ملف التحويل"),
    "finance.payout_profile.rejected": ("Payout profile rejected", "تم رفض ملف التحويل"),
    "finance.settlement.requested": ("Settlement requested", "تم طلب التسوية"),
    "finance.settlement.approved": ("Settlement approved", "تم اعتماد التسوية"),
    "finance.settlement.rejected": ("Settlement rejected", "تم رفض التسوية"),
    "finance.settlement.paid": ("Settlement paid", "تم سداد التسوية"),
    "finance.settlement.cancelled": ("Settlement cancelled", "تم إلغاء التسوية"),
    "finance.adjustment.created": ("Finance adjustment created", "تم إنشاء تعديل مالي"),
    "production_job.created": ("Production job created", "تم إنشاء مهمة الإنتاج"),
    "production_job.manufacturer_assigned": ("Manufacturer assigned to production", "تم إسناد الإنتاج إلى المصنع"),
    "production_job.started": ("Production started", "تم بدء الإنتاج"),
    "production_job.qc_requested": ("Quality inspection requested", "تم طلب فحص الجودة"),
    "production_job.qc_recorded": ("Quality inspection recorded", "تم تسجيل فحص الجودة"),
    "production_milestone.updated": ("Production milestone updated", "تم تحديث مرحلة الإنتاج"),
    "production_asset.added": ("Production asset added", "تمت إضافة ملف إنتاج"),
    "fulfillment.packed": ("Order packed", "تم تعبئة الطلب"),
    "fulfillment.shipped": ("Order shipped", "تم شحن الطلب"),
    "fulfillment.delivered": ("Order delivered", "تم تسليم الطلب"),
    "storefront.created": ("Storefront created", "تم إنشاء واجهة المتجر"),
    "storefront.published": ("Storefront published", "تم نشر واجهة المتجر"),
    "store.product.created": ("Store product created", "تم إنشاء منتج المتجر"),
    "store.variant.created": ("Product variant created", "تم إنشاء متغير المنتج"),
    "store.product.image.added": ("Product image added", "تمت إضافة صورة المنتج"),
    "store.product.published": ("Store product published", "تم نشر منتج المتجر"),
    "studio.project.created": ("Studio project created", "تم إنشاء مشروع Studio"),
    "studio.project.reopened": ("Studio project reopened", "تمت إعادة فتح مشروع Studio"),
    "studio.project.updated": ("Studio project updated", "تم تحديث مشروع Studio"),
    "studio.customization.enabled": ("Studio customization enabled", "تم تفعيل تخصيص Studio"),
    "studio.element.created": ("Studio element added", "تمت إضافة عنصر Studio"),
    "studio.element.updated": ("Studio element updated", "تم تحديث عنصر Studio"),
    "studio.element.removed": ("Studio element removed", "تم حذف عنصر Studio"),
    "cart.item.added": ("Cart item added", "تمت إضافة عنصر إلى السلة"),
    "cart.item.updated": ("Cart item updated", "تم تحديث عنصر السلة"),
    "cart.item.removed": ("Cart item removed", "تم حذف عنصر السلة"),
    "checkout.created": ("Checkout created", "تم إنشاء جلسة الدفع"),
    "checkout.refreshed": ("Checkout refreshed", "تم تحديث جلسة الدفع"),
    "checkout.shipping.updated": ("Shipping details updated", "تم تحديث بيانات الشحن"),
    "order.confirmed": ("Operational order confirmed", "تم تأكيد الطلب التشغيلي"),
    "purchase.confirmed": ("Customer purchase confirmed", "تم تأكيد شراء العميل"),
    "manufacturer_marketplace.listing.created": ("Manufacturer listing created", "تم إنشاء صفحة المصنع"),
    "manufacturer_marketplace.listing.updated": ("Manufacturer listing updated", "تم تحديث صفحة المصنع"),
    "manufacturer_marketplace.listing.published": ("Manufacturer listing published", "تم نشر صفحة المصنع"),
    "manufacturer_marketplace.capability.added": ("Manufacturer capability added", "تمت إضافة قدرة تصنيع"),
    "manufacturer_marketplace.portfolio.added": ("Manufacturer portfolio asset added", "تمت إضافة ملف إلى معرض المصنع"),
    "manufacturer_marketplace.rfq.created": ("Manufacturing RFQ created", "تم إنشاء طلب عرض تصنيع"),
    "manufacturer_marketplace.rfq.opened": ("Manufacturing RFQ opened", "تم فتح طلب عرض التصنيع"),
    "manufacturer_marketplace.rfq.declined": ("Manufacturing RFQ declined", "تم رفض طلب عرض التصنيع"),
    "manufacturer_marketplace.rfq.cancelled": ("Manufacturing RFQ cancelled", "تم إلغاء طلب عرض التصنيع"),
    "manufacturer_marketplace.quote.submitted": ("Manufacturing quote submitted", "تم إرسال عرض التصنيع"),
    "manufacturer_marketplace.quote.selected": ("Manufacturing quote selected", "تم اختيار عرض التصنيع"),
}

_AUDIT_OBJECT_LABELS = {
    "accounts.User": ("User", "مستخدم"),
    "organizations.Organization": ("Organization", "منظمة"),
    "organizations.OnboardingApplication": ("Onboarding application", "طلب انضمام"),
    "organizations.Membership": ("Membership", "عضوية"),
    "design.GarmentDesign": ("Garment design", "تصميم قطعة"),
    "design.GarmentDesignVersion": ("Garment design version", "إصدار تصميم قطعة"),
    "design.DesignAsset": ("Design asset", "ملف تصميم"),
    "artwork.Artwork": ("Artwork", "عمل فني"),
    "artwork.ArtworkVersion": ("Artwork version", "إصدار عمل فني"),
    "artwork.ArtworkAsset": ("Artwork asset", "ملف عمل فني"),
    "artwork.IPDeclaration": ("IP declaration", "إقرار حقوق"),
    "artwork.IPCase": ("IP case", "قضية حقوق ملكية"),
    "artwork.IPCaseEvidence": ("IP case evidence", "دليل قضية حقوق ملكية"),
    "artwork.DesignedProduct": ("Designed product", "منتج مصمم"),
    "artwork.ArtworkPlacement": ("Artwork placement", "موضع عمل فني"),
    "storefront.Storefront": ("Storefront", "واجهة متجر"),
    "storefront.StoreProduct": ("Store product", "منتج متجر"),
    "storefront.StoreProductImage": ("Store product image", "صورة منتج متجر"),
    "storefront.ProductVariant": ("Product variant", "متغير منتج"),
    "storefront.StudioProject": ("Studio project", "مشروع Studio"),
    "storefront.CustomerCustomization": ("Customer customization", "تخصيص العميل"),
    "storefront.CustomizationElement": ("Customization element", "عنصر تخصيص"),
    "checkout.Cart": ("Cart", "سلة"),
    "checkout.CartItem": ("Cart item", "عنصر سلة"),
    "checkout.CheckoutSession": ("Checkout", "جلسة دفع"),
    "checkout.CustomerPurchase": ("Customer purchase", "شراء العميل"),
    "checkout.CustomerOrder": ("Operational order", "طلب تشغيلي"),
    "operations.ProductionJob": ("Production job", "مهمة إنتاج"),
    "operations.ProductionMilestone": ("Production milestone", "مرحلة إنتاج"),
    "operations.ProductionAsset": ("Production asset", "ملف إنتاج"),
    "operations.FulfillmentRecord": ("Fulfillment record", "سجل تنفيذ وشحن"),
    "finance.OrderFinance": ("Order finance", "مالية الطلب"),
    "finance.PayoutProfile": ("Payout profile", "ملف تحويل"),
    "finance.SettlementRequest": ("Settlement request", "طلب تسوية"),
    "finance.FinanceAdjustment": ("Finance adjustment", "تعديل مالي"),
    "integrations.IntegrationConfig": ("Integration", "تكامل"),
    "platform_ops.PlatformAnnouncement": ("Announcement", "إعلان"),
    "platform_ops.MaintenanceWindow": ("Maintenance window", "نافذة الصيانة"),
    "manufacturer_marketplace.ManufacturerListing": ("Manufacturer listing", "صفحة مصنع"),
    "manufacturer_marketplace.ManufacturerCapability": ("Manufacturer capability", "قدرة تصنيع"),
    "manufacturer_marketplace.ManufacturerPortfolioAsset": ("Manufacturer portfolio asset", "ملف معرض المصنع"),
    "manufacturer_marketplace.RFQ": ("Manufacturing RFQ", "طلب عرض تصنيع"),
    "manufacturer_marketplace.RFQInvitation": ("RFQ invitation", "دعوة طلب عرض"),
    "manufacturer_marketplace.ManufacturerQuote": ("Manufacturing quote", "عرض تصنيع"),
    "manufacturer_marketplace.ManufacturerSelection": ("Manufacturer selection", "اختيار مصنع"),
}

_SENSITIVE = (
    "password", "secret", "token", "credential", "authorization", "api_key", "apikey",
    "webhook", "dsn", "database_url", "redis_url", "encryption", "private_key", "access_key",
)


def _sensitive_key(value):
    key = str(value or "").lower()
    return any(token in key for token in _SENSITIVE)


def _human_words(value):
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _sentence(value):
    text = _human_words(value)
    return text[:1].upper() + text[1:] if text else ""


def _localized_pair(pair, language):
    return pair[1] if str(language).startswith("ar") else pair[0]


@register.filter(name="audit_action_label")
def audit_action_label(value, language="en"):
    raw = "" if value is None else str(value).strip()
    if not raw:
        return "حدث تدقيق" if str(language).startswith("ar") else "Audit event"
    known = _AUDIT_ACTION_LABELS.get(raw)
    if known:
        return _localized_pair(known, language)
    parts = [_sentence(part) for part in raw.split(".") if _human_words(part)]
    if len(parts) >= 2:
        return f"{parts[-2]} — {parts[-1]}"
    return parts[0] if parts else ("حدث تدقيق" if str(language).startswith("ar") else "Audit event")


@register.filter(name="audit_object_label")
def audit_object_label(value, language="en"):
    raw = "" if value is None else str(value).strip()
    if not raw:
        return "—"
    known = _AUDIT_OBJECT_LABELS.get(raw)
    if known:
        return _localized_pair(known, language)
    return _sentence(raw.rsplit(".", 1)[-1]) or "—"


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
