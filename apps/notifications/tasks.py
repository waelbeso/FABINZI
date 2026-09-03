import logging

from celery import shared_task

from .models import NotificationDelivery
from .services import deliver_external

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def deliver_notification_channel(self, delivery_id: int):
    delivery = NotificationDelivery.objects.select_related("notification__recipient").get(pk=delivery_id)
    try:
        return deliver_external(delivery).status
    except Exception:
        logger.exception("notification_delivery_task_failed", extra={"delivery_id": delivery_id})
        raise


@shared_task
def dispatch_pending_deliveries(limit=100):
    ids = list(
        NotificationDelivery.objects.filter(
            status__in=[NotificationDelivery.Status.QUEUED, NotificationDelivery.Status.FAILED]
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:limit]
    )
    for pk in ids:
        deliver_notification_channel.delay(pk)
    return len(ids)
