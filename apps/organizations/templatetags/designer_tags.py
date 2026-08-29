from django import template

register = template.Library()


@register.filter
def pairs_text(value):
    if not isinstance(value, dict):
        return ""
    return "\n".join(f"{key} = {item}" for key, item in value.items())


@register.filter
def designer_role_label(value, language="en"):
    labels = {
        "owner": ("Owner", "مالك"),
        "manager": ("Manager", "مدير"),
        "designer": ("Designer", "مصمم"),
        "design_manager": ("Design Manager", "مدير التصميم"),
        "accountant": ("Accountant", "محاسب"),
    }
    en, ar = labels.get(str(value), (str(value), str(value)))
    return ar if language == "ar" else en


@register.filter
def yes_no(value, language="en"):
    if language == "ar":
        return "نعم" if value else "لا"
    return "Yes" if value else "No"
