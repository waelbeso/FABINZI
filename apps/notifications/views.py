from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Notification, NotificationPreference
@login_required
def notification_center(request):
    pref,_=NotificationPreference.objects.get_or_create(user=request.user)
    return render(request,"notifications/center.html",{"notifications":Notification.objects.filter(recipient=request.user)[:100],"preference":pref})
