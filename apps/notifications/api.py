from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Notification, NotificationPreference

def _item(n): return {"id":n.id,"type":n.type,"title_en":n.title_en,"title_ar":n.title_ar,"body_en":n.body_en,"body_ar":n.body_ar,"destination":n.destination,"is_read":n.is_read,"created_at":n.created_at}
class NotificationListAPIView(APIView):
    def get(self,request): return Response([_item(n) for n in Notification.objects.filter(recipient=request.user)[:100]])
class NotificationReadAPIView(APIView):
    def post(self,request,notification_id):
        n=Notification.objects.filter(pk=notification_id,recipient=request.user).first()
        if not n: return Response({"detail":"Not found."},status=404)
        if not n.is_read: n.is_read=True; n.read_at=timezone.now(); n.save(update_fields=["is_read","read_at"])
        return Response(_item(n))
class NotificationReadAllAPIView(APIView):
    def post(self,request):
        now=timezone.now(); count=Notification.objects.filter(recipient=request.user,is_read=False).update(is_read=True,read_at=now); return Response({"updated":count})
class NotificationPreferenceAPIView(APIView):
    def get(self,request):
        p,_=NotificationPreference.objects.get_or_create(user=request.user); return Response({"email_enabled":p.email_enabled,"sms_enabled":p.sms_enabled,"phone_e164":p.phone_e164})
    def patch(self,request):
        p,_=NotificationPreference.objects.get_or_create(user=request.user)
        if "email_enabled" in request.data: p.email_enabled=bool(request.data["email_enabled"])
        if "sms_enabled" in request.data: p.sms_enabled=bool(request.data["sms_enabled"])
        if "phone_e164" in request.data: p.phone_e164=str(request.data["phone_e164"]).strip()
        if p.sms_enabled and not p.phone_e164.startswith("+"): return Response({"detail":"SMS phone must be E.164 format."},status=400)
        p.save(); return self.get(request)
