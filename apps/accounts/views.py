from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.translation import activate
from .models import User

@login_required
def app_home(request):
    return render(request, "accounts/app_home.html")

@login_required
def profile_preferences(request):
    if request.method != "POST":
        return redirect("app-home")
    theme = request.POST.get("theme")
    language = request.POST.get("language")
    if theme not in User.Theme.values or language not in User.Language.values:
        return HttpResponseBadRequest("Invalid preference")
    request.user.theme_preference = theme
    request.user.language_preference = language
    request.user.save(update_fields=["theme_preference", "language_preference"])
    activate(language)
    request.session["django_language"] = language
    return redirect("app-home")
