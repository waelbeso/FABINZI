from django.db import transaction

from apps.manufacturer_marketplace import services as marketplace_services
from . import services as subscription_services


_original_submit_quote = marketplace_services.submit_quote


@transaction.atomic
def submit_quote(*args, **kwargs):
    """Preserve the canonical quote workflow and consume quota atomically.

    The existing Manufacturer marketplace service remains the authority for the
    quote transition. The outer transaction deliberately includes both that
    transition and the first quota-consumption evidence write, so a quota
    failure rolls back the submitted quote and a quote failure cannot consume
    durable quota.
    """
    quote = _original_submit_quote(*args, **kwargs)
    subscription_services.consume_manufacturer_offer(quote=quote)
    return quote
