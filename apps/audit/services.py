from .models import AuditEvent

def record_audit_event(*, actor=None, action, instance=None, metadata=None, request=None):
    ip = None
    if request:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip = (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None
    return AuditEvent.objects.create(actor=actor if getattr(actor, "is_authenticated", False) else None, action=action, object_type=instance._meta.label if instance is not None else "", object_id=str(instance.pk) if instance is not None and instance.pk else "", metadata=metadata or {}, ip_address=ip)
