from django.urls import path

from .launch_views import public_trust_page


urlpatterns = [
    path("about/", public_trust_page, {"page_key": "about"}, name="about"),
    path("terms/", public_trust_page, {"page_key": "terms"}, name="terms"),
    path("privacy/", public_trust_page, {"page_key": "privacy"}, name="privacy"),
    path("returns/", public_trust_page, {"page_key": "returns"}, name="returns"),
    path("shipping/", public_trust_page, {"page_key": "shipping"}, name="shipping"),
    path("support/", public_trust_page, {"page_key": "support"}, name="support"),
]
