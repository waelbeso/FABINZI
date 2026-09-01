from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.subscriptions"

    def ready(self):
        # V2-3 correction layer: preserve the prepared implementation as the
        # base while replacing owner-reviewed lifecycle entry points with the
        # corrected transactional implementations.
        from . import corrections, corrections_followup
        from . import services

        for name, implementation in corrections.SERVICE_OVERRIDES.items():
            setattr(services, name, implementation)
        for name, implementation in corrections_followup.SERVICE_OVERRIDES.items():
            setattr(services, name, implementation)

        # Preserve the existing canonical Manufacturer marketplace workflow;
        # only wrap its submit_quote entry point so the quote transition and
        # quota evidence share one transaction.
        from apps.manufacturer_marketplace import services as marketplace_services
        from .marketplace_integration import submit_quote as quota_aware_submit_quote

        marketplace_services.submit_quote = quota_aware_submit_quote

        # django.contrib.admin autodiscovers app admin modules before this app's
        # ready() runs. Rebind the already-imported operational actions to the
        # corrected lifecycle entry points without changing /Maneg/ structure.
        from . import admin as subscription_admin

        subscription_admin.activate_paid_pro = corrections_followup.activate_paid_pro
        subscription_admin.confirm_subscription_billing = corrections_followup.confirm_subscription_billing
        subscription_admin.downgrade_to_starter = corrections.downgrade_to_starter

        # Signals are imported only after the corrected service bindings are in
        # place. Manufacturer quota enforcement is intentionally integrated in
        # the canonical transactional submit_quote service rather than pre_save.
        from . import signals  # noqa: F401
