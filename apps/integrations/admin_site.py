from two_factor.admin import AdminSiteOTPRequired

class FabinziAdminSite(AdminSiteOTPRequired):
    site_header = "FABINZI Control Center"
    site_title = "FABINZI"
    index_title = "Platform Operations"

fabinzi_admin_site = FabinziAdminSite(name="fabinzi_admin")
