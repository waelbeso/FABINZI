from celery import shared_task
from .models import NotificationDelivery
from .services import deliver_external

@shared_task(bind=True,autoretry_for=(Exception,),retry_backoff=True,retry_jitter=True,max_retries=5)
def deliver_notification_channel(self,delivery_id:int):
    return deliver_external(NotificationDelivery.objects.select_related("notification__recipient").get(pk=delivery_id)).status

@shared_task
def dispatch_pending_deliveries(limit=100):
    ids=list(NotificationDelivery.objects.filter(status__in=[NotificationDelivery.Status.QUEUED,NotificationDelivery.Status.FAILED]).order_by("created_at").values_list("id",flat=True)[:limit])
    for pk in ids: deliver_notification_channel.delay(pk)
    return len(ids)
