from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from apps.integrations.models import IntegrationConfig

class ProductionStorageUnavailable(ImproperlyConfigured):
    pass

def active_provider(provider: str):
    try:
        return IntegrationConfig.objects.get(provider=provider, enabled=True)
    except IntegrationConfig.DoesNotExist as exc:
        raise ProductionStorageUnavailable(f"{provider} is not configured and enabled") from exc

def assert_production_file_storage():
    if settings.DEBUG:
        return
    active_provider(IntegrationConfig.Provider.AMAZON_S3)
