from django import forms

from .models import MaintenanceWindow, PlatformAnnouncement


class _LocalizedModelForm(forms.ModelForm):
    label_map = {}

    def __init__(self, *args, language="en", **kwargs):
        super().__init__(*args, **kwargs)
        is_ar = str(language).startswith("ar")
        for name, labels in self.label_map.items():
            if name in self.fields:
                self.fields[name].label = labels[1] if is_ar else labels[0]
        for name in ("starts_at", "ends_at"):
            if name in self.fields:
                self.fields[name].widget = forms.DateTimeInput(
                    attrs={"type": "datetime-local"},
                    format="%Y-%m-%dT%H:%M",
                )
                self.fields[name].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]


class PlatformAnnouncementForm(_LocalizedModelForm):
    label_map = {
        "enabled": ("Enabled", "مفعّل"),
        "title_en": ("English title", "العنوان بالإنجليزية"),
        "title_ar": ("Arabic title", "العنوان بالعربية"),
        "message_en": ("English message", "الرسالة بالإنجليزية"),
        "message_ar": ("Arabic message", "الرسالة بالعربية"),
        "severity": ("Severity", "النوع / الأهمية"),
        "audience": ("Audience", "الجمهور"),
        "starts_at": ("Starts at", "يبدأ في"),
        "ends_at": ("Ends at", "ينتهي في"),
        "dismissible": ("Dismissible", "قابل للإغلاق"),
        "cta_label_en": ("English CTA label", "نص الإجراء بالإنجليزية"),
        "cta_label_ar": ("Arabic CTA label", "نص الإجراء بالعربية"),
        "cta_url": ("CTA URL", "رابط الإجراء"),
        "priority": ("Priority", "الأولوية"),
    }

    class Meta:
        model = PlatformAnnouncement
        fields = (
            "enabled", "title_en", "title_ar", "message_en", "message_ar",
            "severity", "audience", "starts_at", "ends_at", "dismissible",
            "cta_label_en", "cta_label_ar", "cta_url", "priority",
        )
        widgets = {"message_en": forms.Textarea(attrs={"rows": 3}), "message_ar": forms.Textarea(attrs={"rows": 3})}


class MaintenanceWindowForm(_LocalizedModelForm):
    label_map = {
        "enabled": ("Enabled", "مفعّل"),
        "mode": ("Mode", "الوضع"),
        "message_en": ("English message", "الرسالة بالإنجليزية"),
        "message_ar": ("Arabic message", "الرسالة بالعربية"),
        "starts_at": ("Starts at", "يبدأ في"),
        "ends_at": ("Ends at", "ينتهي في"),
    }

    class Meta:
        model = MaintenanceWindow
        fields = ("enabled", "mode", "message_en", "message_ar", "starts_at", "ends_at")
        widgets = {"message_en": forms.Textarea(attrs={"rows": 3}), "message_ar": forms.Textarea(attrs={"rows": 3})}
