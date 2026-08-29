from django.http import JsonResponse
from django.shortcuts import render

def home(request):
    return render(request, "home.html")
def placeholder_surface(request, surface):
    return render(request, "surface_placeholder.html", {"surface": surface})
def healthz(request):
    return JsonResponse({"status": "ok", "service": "fabinzi"})
