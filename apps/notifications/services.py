import requests
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.integrations.models import IntegrationConfig
from .models import NotificationDelivery

def _active_config(provider):
    cfg=IntegrationConfig.objects.filter(provider=provider,enabled=True,last_test_status=IntegrationConfig.TestStatus.SUCCESS).first()
    if not cfg: raise ValidationError(f"{provider} is not enabled and successfully tested.")
    return cfg

def deliver_external(delivery):
    if delivery.status==NotificationDelivery.Status.SENT: return delivery
    n=delivery.notification; pref=n.recipient.notification_preference
    delivery.attempt_count+=1
    try:
        if delivery.channel==NotificationDelivery.Channel.EMAIL:
            if not pref.email_enabled or not n.recipient.email: raise ValidationError("Email delivery is not configured for recipient.")
            cfg=_active_config(IntegrationConfig.Provider.MAILGUN); sec=cfg.get_secrets(); domain=cfg.config.get("domain",""); base=cfg.config.get("api_base","https://api.mailgun.net"); sender=cfg.config.get("from_email",f"FABINZI <no-reply@{domain}>")
            r=requests.post(f"{base.rstrip('/')}/v3/{domain}/messages",auth=("api",sec.get("api_key","")),data={"from":sender,"to":n.recipient.email,"subject":n.title_en,"text":n.body_en or n.title_en},timeout=10); r.raise_for_status()
        else:
            if not pref.sms_enabled or not pref.phone_e164: raise ValidationError("SMS delivery is not configured for recipient.")
            cfg=_active_config(IntegrationConfig.Provider.TWILIO); sec=cfg.get_secrets(); sid=cfg.config.get("account_sid",""); sender=cfg.config.get("from_number","")
            r=requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",auth=(sid,sec.get("auth_token","")),data={"From":sender,"To":pref.phone_e164,"Body":n.body_en or n.title_en},timeout=10); r.raise_for_status()
        delivery.status=NotificationDelivery.Status.SENT; delivery.sent_at=timezone.now(); delivery.last_error=""
    except Exception as exc:
        delivery.status=NotificationDelivery.Status.FAILED; delivery.last_error=exc.__class__.__name__
    delivery.save(update_fields=["status","attempt_count","last_error","sent_at","updated_at"]); return delivery
