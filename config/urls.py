from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView
from two_factor.urls import urlpatterns as tf_urls
from apps.accounts.views import app_home, profile_preferences, sign_out, signup
from apps.artwork.media_views import public_artwork_preview_media
from apps.artwork.ready_product_v2_4_portal import designer_ready_product_composer, designer_ready_product_composer_detail
from apps.artwork.v2_4_portal import designer_artwork_technical_workspace
from apps.artwork.views import artwork_detail, artwork_marketplace
from apps.checkout.views import add_product_to_cart, cart, cart_checkout_start, cart_item_remove, cart_item_update, checkout_detail, checkout_start, guest_purchase_confirmation, guest_purchase_detail, order_detail, orders, purchase_confirmation, purchase_detail, purchases, retry_guest_cart_merge
from apps.design.v2_4_portal import designer_design_technical_workspace
from apps.finance.views import finance_dashboard
from apps.media.designer_views import private_designer_media
from apps.media.manufacturer_views import manufacturer_production_media
from apps.media.views import private_studio_media
from apps.notifications.views import notification_center
from apps.operations.views import order_operations
from apps.platform_ops.launch_views import bad_request as public_handler400
from apps.platform_ops.public_shell_views import discover, how_it_works, robots_txt, sitemap_xml
from apps.platform_ops.super_admin import configure_stock_super_admin
from apps.platform_ops.views import apple_touch_icon, favicon, handler403 as public_handler403, handler404 as public_handler404, handler500 as public_handler500, healthz, readyz, site_icon_192, site_icon_512, site_manifest, social_share_image
from apps.organizations.designer_views import designer_artwork_detail, designer_artworks, designer_design_detail, designer_design_list, designer_finance, designer_fulfillment, designer_portal, designer_product_detail, designer_products, designer_profile, designer_rfq_detail, designer_rfqs, designer_store, designer_store_product, designer_team
from apps.organizations.manufacturer_views import manufacturer_capabilities, manufacturer_finance, manufacturer_opportunities, manufacturer_portal, manufacturer_production, manufacturer_production_detail, manufacturer_profile, manufacturer_qc, manufacturer_quote_detail, manufacturer_quotes, manufacturer_ready_to_ship, manufacturer_rfq_detail, manufacturer_shipment, manufacturer_team
from apps.organizations.views import edit_onboarding, submit_onboarding
from apps.public_inquiries.media_views import public_inquiry_attachment_media
from apps.public_inquiries.portal_views import designer_inquiries as designer_public_inquiries, designer_inquiry_detail as designer_public_inquiry_detail, manufacturer_inquiries as manufacturer_public_inquiries, manufacturer_inquiry_detail as manufacturer_public_inquiry_detail
from apps.public_inquiries.views import designer_inquiry, manufacturer_inquiry, public_inquiry_status
from apps.public_profiles.portal_views import designer_public_profile, manufacturer_public_products, manufacturer_public_profile
from apps.public_profiles.public_views import designer_directory, designer_public_detail, manufacturer_directory, manufacturer_legacy_redirect, manufacturer_public_detail
from apps.storefront.studio_views import studio, studio_project
from apps.storefront.views import public_product, public_storefront, store_marketplace

configure_stock_super_admin()

urlpatterns = [
    path("", store_marketplace, name="home"),
    path("", store_marketplace, name="store-marketplace"),
    path("store/", RedirectView.as_view(pattern_name="home", permanent=True, query_string=True), name="store-legacy"),
    path("discover/", discover, name="discover"),
    path("how-it-works/", how_it_works, name="how-it-works"),
    path("designers/", designer_directory, name="designer-directory"),
    path("designers/<slug:slug>/", designer_public_detail, name="designer-public-detail"),
    path("manufacturers/", manufacturer_directory, name="manufacturer-marketplace"),
    path("manufacturers/<int:pk>/", manufacturer_legacy_redirect, name="manufacturer-public-detail-legacy"),
    path("manufacturers/<slug:slug>/", manufacturer_public_detail, name="manufacturer-public-detail"),
    path("inquiry/designer/<slug:slug>/", designer_inquiry, name="designer-public-inquiry"),
    path("inquiry/manufacturer/<slug:slug>/", manufacturer_inquiry, name="manufacturer-public-inquiry"),
    path("inquiry/status/<uuid:reference>/", public_inquiry_status, name="public-inquiry-status"),
    path("inquiry/media/<int:pk>/", public_inquiry_attachment_media, name="public-inquiry-attachment-media"),

    path("robots.txt", robots_txt, name="robots-txt"),
    path("sitemap.xml", sitemap_xml, name="sitemap-xml"),
    path("site.webmanifest", site_manifest, name="site-manifest"),
    path("favicon.ico", favicon, name="favicon"),
    path("apple-touch-icon.png", apple_touch_icon, name="apple-touch-icon"),
    path("icon-192.png", site_icon_192, name="site-icon-192"),
    path("icon-512.png", site_icon_512, name="site-icon-512"),
    path("share/fabinzi-1200x630.png", social_share_image, name="social-share-image"),
    path("", include("apps.platform_ops.launch_urls")),

    path("account/signup/", signup, name="signup"),
    path("account/logout/", sign_out, name="logout"),
    path("account/password/change/", auth_views.PasswordChangeView.as_view(template_name="registration/password_change_form.html", success_url="/account/password/change/done/"), name="password-change"),
    path("account/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"), name="password-change-done"),
    path("account/password/reset/", auth_views.PasswordResetView.as_view(template_name="registration/password_reset_form.html", email_template_name="registration/password_reset_email.txt", subject_template_name="registration/password_reset_subject.txt", success_url="/account/password/reset/done/"), name="password-reset"),
    path("account/password/reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password-reset-done"),
    path("account/password/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html", success_url="/account/password/reset/complete/"), name="password-reset-confirm"),
    path("account/password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password-reset-complete"),

    path("app/", app_home, name="app-home"),
    path("app/settings/preferences/", profile_preferences, name="profile-preferences"),
    path("notifications/", notification_center, name="notifications"),
    path("store/<slug:slug>/", public_storefront, name="public-storefront"),
    path("store/<slug:store_slug>/<slug:product_slug>/", public_product, name="public-store-product"),
    path("cart/", cart, name="cart"),
    path("cart/add/<int:product_id>/", add_product_to_cart, name="cart-add-product"),
    path("cart/items/<int:pk>/update/", cart_item_update, name="cart-item-update"),
    path("cart/items/<int:pk>/remove/", cart_item_remove, name="cart-item-remove"),
    path("cart/merge/retry/", retry_guest_cart_merge, name="cart-guest-merge-retry"),
    path("cart/checkout/", cart_checkout_start, name="cart-checkout-start"),
    path("studio/", studio, name="studio"),
    path("studio/<int:pk>/", studio_project, name="studio-project"),
    path("studio/<int:project_id>/checkout/", checkout_start, name="checkout-start"),
    path("media/private/<int:pk>/", private_studio_media, name="private-studio-media"),
    path("media/designer-private/<int:pk>/", private_designer_media, name="private-designer-media"),
    path("artwork/media/<int:pk>/", public_artwork_preview_media, name="artwork-public-preview-media"),
    path("checkout/<int:pk>/", checkout_detail, name="checkout-detail"),
    path("guest/purchase/<str:token>/confirmation/", guest_purchase_confirmation, name="guest-purchase-confirmation"),
    path("guest/purchase/<str:token>/", guest_purchase_detail, name="guest-purchase-detail"),
    path("purchases/", purchases, name="purchases"),
    path("purchases/<int:pk>/confirmation/", purchase_confirmation, name="purchase-confirmation"),
    path("purchases/<int:pk>/", purchase_detail, name="purchase-detail"),
    path("orders/", orders, name="orders"),
    path("orders/<int:pk>/", order_detail, name="order-detail"),
    path("orders/<int:pk>/production/", order_operations, name="order-operations"),
    path("artwork/", artwork_marketplace, name="artwork"),
    path("artwork/<int:pk>/", artwork_detail, name="artwork-detail"),

    path("", include("apps.subscriptions.urls")),

    path("designer/", designer_portal, name="designer"),
    path("designer/profile/", designer_profile, name="designer-profile"),
    path("designer/public-profile/", designer_public_profile, name="designer-public-profile"),
    path("designer/public-inquiries/", designer_public_inquiries, name="designer-public-inquiries"),
    path("designer/public-inquiries/<int:pk>/", designer_public_inquiry_detail, name="designer-public-inquiry-detail"),
    path("designer/team/", designer_team, name="designer-team"),
    path("designer/designs/", designer_design_list, name="designer-design-list"),
    path("designer/designs/<int:pk>/", designer_design_detail, name="designer-design-detail"),
    path("designer/designs/<int:pk>/technical/", designer_design_technical_workspace, name="designer-design-technical-v2-4"),
    path("designer/artworks/", designer_artworks, name="designer-artworks"),
    path("designer/artworks/<int:pk>/", designer_artwork_detail, name="designer-artwork-detail"),
    path("designer/artworks/<int:pk>/technical/", designer_artwork_technical_workspace, name="designer-artwork-technical-v2-4"),
    path("designer/products/", designer_products, name="designer-products"),
    path("designer/products/compose/", designer_ready_product_composer, name="designer-ready-product-composer-v2-4"),
    path("designer/products/compose/<int:pk>/", designer_ready_product_composer_detail, name="designer-ready-product-composer-detail-v2-4"),
    path("designer/products/<int:pk>/", designer_product_detail, name="designer-product-detail"),
    path("designer/rfqs/", designer_rfqs, name="designer-rfqs"),
    path("designer/rfqs/<int:pk>/", designer_rfq_detail, name="designer-rfq-detail"),
    path("designer/store/", designer_store, name="designer-store"),
    path("designer/store/products/<int:pk>/", designer_store_product, name="designer-store-product"),
    path("designer/fulfillment/", designer_fulfillment, name="designer-fulfillment"),
    path("designer/finance/", designer_finance, name="designer-finance"),

    path("manufacturer/", manufacturer_portal, name="manufacturer"),
    path("manufacturer/profile/", manufacturer_profile, name="manufacturer-profile"),
    path("manufacturer/public-profile/", manufacturer_public_profile, name="manufacturer-public-profile"),
    path("manufacturer/public-products/", manufacturer_public_products, name="manufacturer-public-products"),
    path("manufacturer/public-inquiries/", manufacturer_public_inquiries, name="manufacturer-public-inquiries"),
    path("manufacturer/public-inquiries/<int:pk>/", manufacturer_public_inquiry_detail, name="manufacturer-public-inquiry-detail"),
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
    path("Maneg/", include(("apps.platform_ops.maneg_urls", "fabinzi_admin"), namespace="fabinzi_admin")),
    path("super/", admin.site.urls),
]

handler400 = public_handler400
handler403 = public_handler403
handler404 = public_handler404
handler500 = public_handler500
