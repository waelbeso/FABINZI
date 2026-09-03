from types import MethodType

from django.contrib import admin

from apps.integrations.admin_site import fabinzi_admin_site


_TEMPLATE_ATTRIBUTES = (
    "add_form_template",
    "change_form_template",
    "change_list_template",
    "delete_confirmation_template",
    "delete_selected_confirmation_template",
    "object_history_template",
    "popup_response_template",
)


def _superuser_has_permission(_site, request):
    user = request.user
    return bool(user.is_active and user.is_staff and user.is_superuser)


def _stock_admin_class(source_admin):
    """Reuse expert ModelAdmin behavior without carrying FABINZI admin templates."""
    attrs = {attribute: None for attribute in _TEMPLATE_ATTRIBUTES}
    attrs["__module__"] = __name__
    return type(f"Stock{source_admin.__class__.__name__}", (source_admin.__class__,), attrs)


def configure_stock_super_admin():
    """Populate the singleton default AdminSite from accepted project registrations.

    /super/ remains Django's stock AdminSite and stock template hierarchy.  We
    deliberately do not create another custom AdminSite. Registrations are
    copied from the existing accepted registry so expert fallback coverage is
    retained without making /Maneg/ depend on Django Admin.
    """
    admin.site.has_permission = MethodType(_superuser_has_permission, admin.site)

    for model, source_admin in tuple(fabinzi_admin_site._registry.items()):
        if admin.site.is_registered(model):
            continue
        admin.site.register(model, _stock_admin_class(source_admin))
