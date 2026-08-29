from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

def home(request): return render(request,"home.html")
def placeholder_surface(request,surface): return render(request,"surface_placeholder.html",{"surface":surface})
def healthz(request): return JsonResponse({"status":"ok","service":"fabinzi"})
def readyz(request):
    try:
        with connection.cursor() as cursor: cursor.execute("SELECT 1"); cursor.fetchone()
        return JsonResponse({"status":"ready","database":"ok"})
    except Exception:
        return JsonResponse({"status":"not_ready","database":"error"},status=503)
