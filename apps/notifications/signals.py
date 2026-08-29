from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Notification, NotificationDelivery, NotificationPreference

@receiver(post_save,sender=Notification)
def prepare_external_deliveries(sender,instance,created,**kwargs):
    if not created: return
    pref,_=NotificationPreference.objects.get_or_create(user=instance.recipient)
    if pref.email_enabled:
        NotificationDelivery.objects.get_or_create(notification=instance,channel=NotificationDelivery.Channel.EMAIL,defaults={"provider":"mailgun"})
    if pref.sms_enabled:
        NotificationDelivery.objects.get_or_create(notification=instance,channel=NotificationDelivery.Channel.SMS,defaults={"provider":"twilio"})
