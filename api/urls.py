from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

class ApiHealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def get(self, request):
        return Response({"status": "ok", "service": "fabinzi", "api": "v1"})

app_name = "v1"
urlpatterns = [path("health/", ApiHealthView.as_view(), name="health")]
