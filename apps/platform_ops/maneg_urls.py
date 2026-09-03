from django.urls import path

from apps.finance import maneg_v2_8 as finance_v2_8_maneg
from apps.operations import maneg_v2_7 as operations_v2_7_maneg
from apps.public_inquiries import maneg_views as public_inquiry_maneg
from apps.public_profiles import maneg_views as public_profile_maneg

from . import maneg_v2_9, maneg_views
from .maneg_access import maneg_staff_required, maneg_superuser_required, stock_admin_redirect

app_name = "fabinzi_admin"


def _staff(route, view, name):
    return path(route, maneg_staff_required(view), name=name)


def _super(route, view, name):
    return path(route, maneg_superuser_required(view), name=name)


urlpatterns = [
    _staff("", maneg_v2_9.dashboard, "index"),
    _staff("users/", maneg_views.users, "maneg-users"),
    _staff("users/<int:pk>/", maneg_views.user_detail, "maneg-user-detail"),
    _staff("organizations/", maneg_views.organizations, "maneg-organizations"),
    _staff("organizations/<int:pk>/", maneg_views.organization_detail, "maneg-organization-detail"),
    _staff("verification/", maneg_views.verification, "maneg-verification"),
    _staff("verification/<int:pk>/", maneg_views.verification_detail, "maneg-verification-detail"),
    _staff("public-profiles/", public_profile_maneg.public_profile_queue, "maneg-v2-5-public-profiles"),
    _staff("public-profiles/revisions/<int:pk>/", public_profile_maneg.public_profile_revision_detail, "maneg-v2-5-public-profile-detail"),
    _staff("public-profiles/manufacturers/", public_profile_maneg.manufacturer_public_controls, "maneg-v2-5-manufacturer-public-controls"),
    _staff("public-inquiries/", public_inquiry_maneg.public_inquiry_queue, "maneg-v2-5-public-inquiries"),
    _staff("public-inquiries/<int:pk>/", public_inquiry_maneg.public_inquiry_detail, "maneg-v2-5-public-inquiry-detail"),
    _staff("design-review/", maneg_views.design_review, "maneg-design-review"),
    _staff("design-review/<int:pk>/", maneg_views.design_review_detail, "maneg-design-review-detail"),
    _staff("artwork-ip/", maneg_views.artwork_ip, "maneg-artwork-ip"),
    _staff("artwork-ip/version/<int:pk>/", maneg_views.artwork_version_detail, "maneg-artwork-version-detail"),
    _staff("artwork-ip/case/<int:pk>/", maneg_views.ip_case_detail, "maneg-ip-case-detail"),
    _staff("catalog/", maneg_views.catalog, "maneg-catalog"),
    _staff("orders/", maneg_views.orders, "maneg-orders"),
    _staff("production/", maneg_views.production, "maneg-production"),
    _staff("production-routing/", operations_v2_7_maneg.routing_console, "maneg-v2-7-routing"),
    _staff("subscriptions/", maneg_v2_9.subscriptions, "maneg-v2-9-subscriptions"),
    _staff("commercial-settings/", maneg_v2_9.commercial_settings, "maneg-v2-9-commercial-settings"),
    # Stable internal reverse contract retained without reviving Django Admin UX.
    _staff(
        "commercial-settings/application-review/<int:pk>/",
        maneg_v2_9.application_review_configuration_compat,
        "platform_ops_applicationreviewconfiguration_change",
    ),
    _staff("finance/", maneg_views.finance, "maneg-finance"),
    _staff("finance-policies/", finance_v2_8_maneg.finance_policy_list, "maneg-v2-8-finance-policies"),
    _staff("finance-policies/new/", finance_v2_8_maneg.finance_policy_create, "maneg-v2-8-finance-policy-create"),
    _staff("finance-policies/<int:pk>/", finance_v2_8_maneg.finance_policy_detail, "maneg-v2-8-finance-policy-detail"),
    _staff("finance-policies/<int:pk>/activate/", finance_v2_8_maneg.finance_policy_activate, "maneg-v2-8-finance-policy-activate"),
    _staff("finance-policies/<int:pk>/retire/", finance_v2_8_maneg.finance_policy_retire, "maneg-v2-8-finance-policy-retire"),
    _staff("finance-policies/<int:pk>/preview/", finance_v2_8_maneg.finance_policy_preview, "maneg-v2-8-finance-policy-preview"),
    _staff("finance-reconciliation/", finance_v2_8_maneg.finance_pending, "maneg-v2-8-finance-pending"),
    _staff("finance-reconciliation/<int:pk>/reconcile/", finance_v2_8_maneg.finance_pending_reconcile, "maneg-v2-8-finance-reconcile"),
    _staff("finance-payouts/", finance_v2_8_maneg.finance_payouts, "maneg-v2-8-finance-payouts"),
    _staff("finance-payouts/profile/<int:pk>/bank-proof/", finance_v2_8_maneg.payout_bank_proof, "maneg-v2-8-bank-proof"),
    _super("integrations/", maneg_views.integrations, "maneg-integrations"),
    _super("integrations/<int:pk>/", maneg_views.integration_detail, "maneg-integration-detail"),
    _staff("notifications/", maneg_views.notifications, "maneg-notifications"),
    _staff("announcements/", maneg_views.announcements, "maneg-announcements"),
    _staff("maintenance/", maneg_views.maintenance, "maneg-maintenance"),
    _staff("audit/", maneg_views.audit_log, "maneg-audit"),
    _super("system/", maneg_views.system_status, "maneg-system"),
    _staff("private/<str:asset_type>/<int:pk>/", maneg_views.private_evidence, "maneg-private-evidence"),
    path("expert/", stock_admin_redirect, name="maneg-expert"),
]
