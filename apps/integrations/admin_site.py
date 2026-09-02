from django.urls import path
from two_factor.admin import AdminSiteOTPRequired


class FabinziAdminSite(AdminSiteOTPRequired):
    site_header = "FABINZI Control Center"
    site_title = "FABINZI"
    index_title = "Platform Operations"

    def index(self, request, extra_context=None):
        from apps.platform_ops.maneg_views import dashboard
        return dashboard(request, extra_context=extra_context)

    def get_urls(self):
        from apps.platform_ops import maneg_views
        from apps.public_profiles import maneg_views as public_profile_maneg
        from apps.public_inquiries import maneg_views as public_inquiry_maneg

        custom = [
            path("users/", self.admin_view(maneg_views.users), name="maneg-users"),
            path("users/<int:pk>/", self.admin_view(maneg_views.user_detail), name="maneg-user-detail"),
            path("organizations/", self.admin_view(maneg_views.organizations), name="maneg-organizations"),
            path("organizations/<int:pk>/", self.admin_view(maneg_views.organization_detail), name="maneg-organization-detail"),
            path("verification/", self.admin_view(maneg_views.verification), name="maneg-verification"),
            path("verification/<int:pk>/", self.admin_view(maneg_views.verification_detail), name="maneg-verification-detail"),
            path("public-profiles/", self.admin_view(public_profile_maneg.public_profile_queue), name="maneg-v2-5-public-profiles"),
            path("public-profiles/revisions/<int:pk>/", self.admin_view(public_profile_maneg.public_profile_revision_detail), name="maneg-v2-5-public-profile-detail"),
            path("public-profiles/manufacturers/", self.admin_view(public_profile_maneg.manufacturer_public_controls), name="maneg-v2-5-manufacturer-public-controls"),
            path("public-inquiries/", self.admin_view(public_inquiry_maneg.public_inquiry_queue), name="maneg-v2-5-public-inquiries"),
            path("public-inquiries/<int:pk>/", self.admin_view(public_inquiry_maneg.public_inquiry_detail), name="maneg-v2-5-public-inquiry-detail"),
            path("design-review/", self.admin_view(maneg_views.design_review), name="maneg-design-review"),
            path("design-review/<int:pk>/", self.admin_view(maneg_views.design_review_detail), name="maneg-design-review-detail"),
            path("artwork-ip/", self.admin_view(maneg_views.artwork_ip), name="maneg-artwork-ip"),
            path("artwork-ip/version/<int:pk>/", self.admin_view(maneg_views.artwork_version_detail), name="maneg-artwork-version-detail"),
            path("artwork-ip/case/<int:pk>/", self.admin_view(maneg_views.ip_case_detail), name="maneg-ip-case-detail"),
            path("catalog/", self.admin_view(maneg_views.catalog), name="maneg-catalog"),
            path("orders/", self.admin_view(maneg_views.orders), name="maneg-orders"),
            path("production/", self.admin_view(maneg_views.production), name="maneg-production"),
            path("finance/", self.admin_view(maneg_views.finance), name="maneg-finance"),
            path("integrations/", self.admin_view(maneg_views.integrations), name="maneg-integrations"),
            path("integrations/<int:pk>/", self.admin_view(maneg_views.integration_detail), name="maneg-integration-detail"),
            path("notifications/", self.admin_view(maneg_views.notifications), name="maneg-notifications"),
            path("announcements/", self.admin_view(maneg_views.announcements), name="maneg-announcements"),
            path("maintenance/", self.admin_view(maneg_views.maintenance), name="maneg-maintenance"),
            path("audit/", self.admin_view(maneg_views.audit_log), name="maneg-audit"),
            path("system/", self.admin_view(maneg_views.system_status), name="maneg-system"),
            path("private/<str:asset_type>/<int:pk>/", self.admin_view(maneg_views.private_evidence), name="maneg-private-evidence"),
            path("expert/", self.admin_view(maneg_views.expert_admin), name="maneg-expert"),
        ]
        return custom + super().get_urls()


fabinzi_admin_site = FabinziAdminSite(name="fabinzi_admin")
