from celery import shared_task

from .services import process_all_subscriptions


@shared_task(name="apps.subscriptions.tasks.process_subscription_lifecycle")
def process_subscription_lifecycle():
    return process_all_subscriptions()
