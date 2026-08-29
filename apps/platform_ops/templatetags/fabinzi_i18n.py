from django import template

register = template.Library()

LABELS = {
    "pending_payment": {"en": "Pending payment", "ar": "بانتظار الدفع"},
    "confirmed": {"en": "Confirmed", "ar": "مؤكد"},
    "payment_failed": {"en": "Payment failed", "ar": "فشل الدفع"},
    "cancelled": {"en": "Cancelled", "ar": "ملغي"},
    "refunded": {"en": "Refunded", "ar": "مسترد"},
    "processing": {"en": "Processing", "ar": "قيد التجهيز"},
    "shipped": {"en": "Shipped", "ar": "تم الشحن"},
    "partially_shipped": {"en": "Partially shipped", "ar": "تم شحن بعض العناصر"},
    "delivered": {"en": "Delivered", "ar": "تم التسليم"},
    "partially_delivered": {"en": "Partially delivered", "ar": "تم تسليم بعض العناصر"},
    "partially_cancelled": {"en": "Partially cancelled", "ar": "تم إلغاء بعض العناصر"},
    "draft": {"en": "Draft", "ar": "مسودة"},
    "ready": {"en": "Ready", "ar": "جاهز"},
    "archived": {"en": "Archived", "ar": "مؤرشف"},
    "made_to_order": {"en": "Made to order", "ar": "يصنع حسب الطلب"},
    "stock": {"en": "Stock", "ar": "من المخزون"},
    "cod": {"en": "Cash on Delivery", "ar": "الدفع عند الاستلام"},
    "paymob": {"en": "Paymob", "ar": "Paymob"},
    "stripe": {"en": "Stripe", "ar": "Stripe"},
    "queued": {"en": "Queued", "ar": "في قائمة الانتظار"},
    "in_production": {"en": "In production", "ar": "قيد الإنتاج"},
    "qc": {"en": "Quality control", "ar": "فحص الجودة"},
    "ready_to_ship": {"en": "Ready to ship", "ar": "جاهز للشحن"},
}


@register.filter
def fab_label(value, language="en"):
    if value is None:
        return ""
    key = str(value)
    language = "ar" if str(language).lower().startswith("ar") else "en"
    labels = LABELS.get(key)
    if labels:
        return labels[language]
    return key.replace("_", " ").strip().capitalize()
