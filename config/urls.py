from django.urls import include, path
from two_factor.urls import urlpatterns as tf_urls
from apps.accounts.views import app_home, profile_preferences
from apps.artwork.media_views import public_artwork_preview_media
from apps.artwork.views import artwork_detail, artwork_marketplace
from apps.checkout.views import (
    add_product_to_cart,
    cart,
    cart_checkout_start,
    cart_item_remove,
    cart_item_update,
    checkout_detail,
    checkout_start,
    order_detail,
    orders,
    purchase_confirmation,
    purchase_detail,
    purchases,
)
from apps.finance.views import finance_dashboard
from apps.manufacturer_marketplace.views import manufacturer_marketplace, manufacturer_public_detail
from apps.media.designer_views import private_designer_media
from apps.media.manufacturer_views import manufacturer_production_media
from apps.media.views import private_studio_media
from apps.notifications.views import notification_center
from apps.operations.views import order_operations
from apps.platform_ops.views import (
    apple_touch_icon,
    favicon,
    handler403 as public_handler403,
    handler404 as public_handler404,
    handler500 as public_handler500,
    healthz,
    home,
    readyz,
    robots_txt,
    site_icon_192,
    site_icon_512,
    site_manifest,
    sitemap_xml,
    social_share_image,
)
from apps.integrations.admin_site import fabinzi_admin_site
from apps.organizations.designer_views import (
    designer_artwork_detail,
    designer_artworks,
    designer_design_detail,
    designer_design_list,
    designer_finance,
    designer_fulfillment,
    designer_portal,
    designer_product_detail,
    designer_products,
    designer_profile,
    designer_rfq_detail,
    designer_rfqs,
    designer_store,
    designer_store_product,
    designer_team,
)
from apps.organizations.manufacturer_views import (
    manufacturer_capabilities,
    manufacturer_finance,
    manufacturer_opportunities,
    manufacturer_portal,
    manufacturer_production,
    manufacturer_production_detail,
    manufacturer_profile,
    manufacturer_qc,
    manufacturer_quote_detail,
    manufacturer_quotes,
    manufacturer_ready_to_ship,
    manufacturer_rfq_detail,
    manufacturer_shipment,
    manufacturer_team,
)
from apps.organizations.views import edit_onboarding, submit_onboarding
from apps.storefront.studio_views import studio, studio_project
from apps.storefront.views import public_product, public_storefront, store_marketplace

urlpatterns = [
    path("", home, name="home"),
    path("robots.txt", robots_txt, name="robots-txt"),
    path("sitemap.xml", sitemap_xml, name="sitemap-xml"),
    path("site.webmanifest", site_manifest, name="site-manifest"),
    path("favicon.ico", favicon, name="favicon"),
    path("apple-touch-icon.png", apple_touch_icon, name="apple-touch-icon"),
    path("icon-192.png", site_icon_192, name="site-icon-192"),
    path("icon-512.png", site_icon_512, name="site-icon-512"),
    path("share/fabinzi-1200x630.png", social_share_image, name="social-share-image"),
    path("app/", app_home, name="app-home"),
    path("app/settings/preferences/", profile_preferences, name="profile-preferences"),
    path("notifications/", notification_center, name="notifications"),
    path("store/", store_marketplace, name="store-marketplace"),
    path("store/<slug:slug>/", public_storefront, name="public-storefront"),
    path("store/<slug:store_slug>/<slug:product_slug>/", public_product, name="public-store-product"),
    path("cart/", cart, name="cart"),
    path("cart/add/<int:product_id>/", add_product_to_cart, name="cart-add-product"),
    path("cart/items/<int:pk>/update/", cart_item_update, name="cart-item-update"),
    path("cart/items/<int:pk>/remove/", cart_item_remove, name="cart-item-remove"),
    path("cart/checkout/", cart_checkout_start, name="cart-checkout-start"),
    path("studio/", studio, name="studio"),
    path("studio/<int:pk>/", studio_project, name="studio-project"),
    path("studio/<int:project_id>/checkout/", checkout_start, name="checkout-start"),
    path("media/private/<int:pk>/", private_studio_media, name="private-studio-media"),
    path("media/designer-private/<int:pk>/", private_designer_media, name="private-designer-media"),
    path("artwork/media/<int:pk>/", public_artwork_preview_media, name="artwork-public-preview-media"),
    path("checkout/<int:pk>/", checkout_detail, name="checkout-detail"),
    path("purchases/", purchases, name="purchases"),
    path("purchases/<int:pk>/confirmation/", purchase_confirmation, name="purchase-confirmation"),
    path("purchases/<int:pk>/", purchase_detail, name="purchase-detail"),
    path("orders/", orders, name="orders"),
    path("orders/<int:pk>/", order_detail, name="order-detail"),
    path("orders/<int:pk>/production/", order_operations, name="order-operations"),
    path("artwork/", artwork_marketplace, name="artwork"),
    path("artwork/<int:pk>/", artwork_detail, name="artwork-detail"),
    path("manufacturers/", manufacturer_marketplace, name="manufacturer-marketplace"),
    path("manufacturers/<int:pk>/", manufacturer_public_detail, name="manufacturer-public-detail"),

    path("designer/", designer_portal, name="designer"),
    path("designer/profile/", designer_profile, name="designer-profile"),
    path("designer/team/", designer_team, name="designer-team"),
    path("designer/designs/", designer_design_list, name="designer-design-list"),
    path("designer/designs/<int:pk>/", designer_design_detail, name="designer-design-detail"),
    path("designer/artworks/", designer_artworks, name="designer-artworks"),
    path("designer/artworks/<int:pk>/", designer_artwork_detail, name="designer-artwork-detail"),
    path("designer/products/", designer_products, name="designer-products"),
    path("designer/products/<int:pk>/", designer_product_detail, name="designer-product-detail"),
    path("designer/rfqs/", designer_rfqs, name="designer-rfqs"),
    path("designer/rfqs/<int:pk>/", designer_rfq_detail, name="designer-rfq-detail"),
    path("designer/store/", designer_store, name="designer-store"),
    path("designer/store/products/<int:pk>/", designer_store_product, name="designer-store-product"),
    path("designer/fulfillment/", designer_fulfillment, name="designer-fulfillment"),
    path("designer/finance/", designer_finance, name="designer-finance"),

    path("manufacturer/", manufacturer_portal, name="manufacturer"),
    path("manufacturer/profile/", manufacturer_profile, name="manufacturer-profile"),
    path("manufacturer/team/", manufacturer_team, name="manufacturer-team"),
    path("manufacturer/capabilities/", manufacturer_capabilities, name="manufacturer-capabilities"),
    path("manufacturer/opportunities/", manufacturer_opportunities, name="manufacturer-opportunities"),
    path("manufacturer/marketplace/", manufacturer_opportunities, name="manufacturer-marketplace-dashboard"),
    path("manufacturer/opportunities/<int:pk>/", manufacturer_rfq_detail, name="manufacturer-rfq-detail"),
    path("manufacturer/quotes/", manufacturer_quotes, name="manufacturer-quotes"),
    path("manufacturer/quotes/<int:pk>/", manufacturer_quote_detail, name="manufacturer-quote-detail"),
    path("manufacturer/production/", manufacturer_production, name="manufacturer-production"),
    path("manufacturer/production/<int:pk>/", manufacturer_production_detail, name="manufacturer-production-detail"),
    path("manufacturer/production/<int:pk>/qc/", manufacturer_qc, name="manufacturer-qc"),
    path("manufacturer/production/<int:pk>/ready-to-ship/", manufacturer_ready_to_ship, name="manufacturer-ready-to-ship"),
    path("manufacturer/production/<int:pk>/shipment/", manufacturer_shipment, name="manufacturer-shipment"),
    path("manufacturer/production/<int:job_id>/media/<str:asset_type>/<int:pk>/", manufacturer_production_media, name="manufacturer-production-media"),
    path("manufacturer/finance/", manufacturer_finance, name="manufacturer-finance"),
    path("finance/", finance_dashboard, name="finance-dashboard"),
    path("onboarding/<int:pk>/edit/", edit_onboarding, name="edit-onboarding"),
    path("onboarding/<int:pk>/submit/", submit_onboarding, name="submit-onboarding"),
    path("healthz/", healthz, name="healthz"),
    path("readyz/", readyz, name="readyz"),
    path("api/v1/", include(("api.urls", "v1"), namespace="v1")),
    path("", include(tf_urls)),
    path("Maneg/", fabinzi_admin_site.urls),
]

handler403 = public_handler403
handler404 = public_handler404
handler500 = public_handler500
