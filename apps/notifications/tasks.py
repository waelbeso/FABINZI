from celery import shared_task

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def deliver_notification_channel(self, notification_id: int, channel: str):
    return {"notification_id": notification_id, "channel": channel, "status": "provider-disabled-or-not-activated"}
