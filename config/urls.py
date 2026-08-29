from django.urls import include, path
from two_factor.urls import urlpatterns as tf_urls

from apps.accounts.views import app_home, profile_preferences
from apps.artwork.views import artwork_marketplace, designer_artwork_detail, designer_artworks, designer_products
from apps.design.views import design_detail, design_list
from apps.manufacturer_marketplace.views import designer_rfq_dashboard, manufacturer_marketplace, manufacturer_marketplace_dashboard, manufacturer_public_detail
from apps.platform_ops.views import healthz, home
from apps.integrations.admin_site import fabinzi_admin_site
from apps.organizations.views import designer_portal, edit_onboarding, manufacturer_portal, submit_onboarding
from apps.storefront.views import designer_store_dashboard, public_product, public_storefront, store_marketplace, studio, studio_project

urlpatterns = [
    path("",home,name="home"),path("app/",app_home,name="app-home"),path("app/settings/preferences/",profile_preferences,name="profile-preferences"),
    path("store/",store_marketplace,name="store-marketplace"),path("store/<slug:slug>/",public_storefront,name="public-storefront"),path("store/<slug:store_slug>/<slug:product_slug>/",public_product,name="public-store-product"),
    path("studio/",studio,name="studio"),path("studio/<int:pk>/",studio_project,name="studio-project"),path("artwork/",artwork_marketplace,name="artwork"),
    path("manufacturers/",manufacturer_marketplace,name="manufacturer-marketplace"),path("manufacturers/<int:pk>/",manufacturer_public_detail,name="manufacturer-public-detail"),
    path("designer/",designer_portal,name="designer"),path("designer/designs/",design_list,name="designer-design-list"),path("designer/designs/<int:pk>/",design_detail,name="designer-design-detail"),path("designer/artworks/",designer_artworks,name="designer-artworks"),path("designer/artworks/<int:pk>/",designer_artwork_detail,name="designer-artwork-detail"),path("designer/products/",designer_products,name="designer-products"),path("designer/rfqs/",designer_rfq_dashboard,name="designer-rfqs"),path("designer/store/",designer_store_dashboard,name="designer-store"),
    path("manufacturer/",manufacturer_portal,name="manufacturer"),path("manufacturer/marketplace/",manufacturer_marketplace_dashboard,name="manufacturer-marketplace-dashboard"),
    path("onboarding/<int:pk>/edit/",edit_onboarding,name="edit-onboarding"),path("onboarding/<int:pk>/submit/",submit_onboarding,name="submit-onboarding"),path("healthz/",healthz,name="healthz"),path("api/v1/",include(("api.urls","v1"),namespace="v1")),path("",include(tf_urls)),path("Maneg/",fabinzi_admin_site.urls),
]
