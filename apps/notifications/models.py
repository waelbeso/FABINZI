from django.conf import settings
from django.db import models

class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=80)
    title_ar = models.CharField(max_length=220)
    title_en = models.CharField(max_length=220)
    body_ar = models.TextField(blank=True)
    body_en = models.TextField(blank=True)
    destination = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ("-created_at",)
