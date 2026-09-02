from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from apps.accounts.guest_identity import GUEST_SESSION_KEY
from .services import GuestCartMergeConflict, merge_guest_cart_into_customer

PENDING_GUEST_CART_MERGE_KEY = "fabinzi_pending_guest_cart_merge"


@receiver(user_logged_in)
def merge_guest_cart_after_login(sender, request, user, **kwargs):
    if request is None:
        return
    guest_identity = request.session.get(GUEST_SESSION_KEY)
    if not guest_identity:
        return
    try:
        cart = merge_guest_cart_into_customer(guest_identity=guest_identity, customer=user, request=request)
    except GuestCartMergeConflict as exc:
        request.session[PENDING_GUEST_CART_MERGE_KEY] = {
            "message": " ".join(exc.messages) if getattr(exc, "messages", None) else str(exc),
        }
        return
    if cart is not None:
        request.session.pop(PENDING_GUEST_CART_MERGE_KEY, None)
        request.session.pop(GUEST_SESSION_KEY, None)
