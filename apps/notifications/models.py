from django.conf import settings
from django.db import models

class Notification(models.Model):
    recipient=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="notifications")
    type=models.CharField(max_length=80); title_ar=models.CharField(max_length=220); title_en=models.CharField(max_length=220); body_ar=models.TextField(blank=True); body_en=models.TextField(blank=True); destination=models.CharField(max_length=500,blank=True); is_read=models.BooleanField(default=False); created_at=models.DateTimeField(auto_now_add=True,db_index=True); read_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=("-created_at",)

class NotificationPreference(models.Model):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="notification_preference")
    email_enabled=models.BooleanField(default=False); sms_enabled=models.BooleanField(default=False); phone_e164=models.CharField(max_length=24,blank=True); updated_at=models.DateTimeField(auto_now=True)

class NotificationDelivery(models.Model):
    class Channel(models.TextChoices): EMAIL="email","Email"; SMS="sms","SMS"
    class Status(models.TextChoices): QUEUED="queued","Queued"; SENT="sent","Sent"; SKIPPED="skipped","Skipped"; FAILED="failed","Failed"
    notification=models.ForeignKey(Notification,on_delete=models.CASCADE,related_name="deliveries"); channel=models.CharField(max_length=12,choices=Channel.choices); status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED,db_index=True); provider=models.CharField(max_length=32,blank=True); attempt_count=models.PositiveIntegerField(default=0); last_error=models.CharField(max_length=255,blank=True); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True); sent_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        ordering=("-created_at",); constraints=[models.UniqueConstraint(fields=("notification","channel"),name="unique_notification_channel_delivery")]
