from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.translation import activate

from apps.artwork.models import Artwork
from apps.checkout.models import Cart, CustomerPurchase
from apps.notifications.models import Notification
from apps.storefront.models import StoreProduct, Storefront, StudioProject
from .forms import PublicSignupForm
from .models import User


def signup(request):
    if request.user.is_authenticated:
        return redirect("app-home")

    if request.method == "POST":
        form = PublicSignupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "تم إنشاء حسابك. يمكنك تسجيل الدخول الآن."
                if getattr(request, "LANGUAGE_CODE", "en") == "ar"
                else "Your FABINZI account is ready. You can sign in now.",
            )
            return redirect("two_factor:login")
    else:
        form = PublicSignupForm()
    return render(request, "accounts/signup.html", {"form": form})


def sign_out(request):
    if request.method == "POST":
        logout(request)
        messages.success(
            request,
            "تم تسجيل الخروج بأمان."
            if getattr(request, "LANGUAGE_CODE", "en") == "ar"
            else "You have been signed out securely.",
        )
        return redirect("home")
    return render(request, "accounts/logout_confirm.html")


@login_required
def app_home(request):
    products = (
        StoreProduct.objects.filter(
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
        )
        .select_related("storefront", "designed_product")
        .prefetch_related("images__media_asset", "variants", "designed_product__placements")
        .order_by("-featured", "-published_at", "-updated_at")[:6]
    )
    artworks = (
        Artwork.objects.filter(status=Artwork.Status.APPROVED)
        .select_related("organization")
        .order_by("-updated_at")[:4]
    )
    purchases = (
        CustomerPurchase.objects.filter(customer=request.user)
        .prefetch_related("child_orders__item__store_product")
        .order_by("-created_at")[:4]
    )
    studio_projects = (
        StudioProject.objects.filter(customer=request.user)
        .exclude(status=StudioProject.Status.ARCHIVED)
        .select_related("product", "product__storefront", "variant")
        .order_by("-updated_at")[:4]
    )
    active_cart = Cart.objects.filter(customer=request.user, status=Cart.Status.ACTIVE).prefetch_related("items").first()
    unread_notifications = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return render(
        request,
        "accounts/app_home.html",
        {
            "featured_products": products,
            "featured_artworks": artworks,
            "recent_purchases": purchases,
            "studio_projects": studio_projects,
            "active_cart": active_cart,
            "unread_notifications": unread_notifications,
        },
    )


@login_required
def profile_preferences(request):
    if request.method == "GET":
        return render(request, "accounts/preferences.html")

    theme = request.POST.get("theme")
    language = request.POST.get("language")
    if theme not in User.Theme.values or language not in User.Language.values:
        return HttpResponseBadRequest("Invalid preference")

    request.user.theme_preference = theme
    request.user.language_preference = language
    request.user.save(update_fields=["theme_preference", "language_preference"])
    activate(language)
    request.session["django_language"] = language
    messages.success(
        request,
        "تم حفظ تفضيلات الحساب." if language == "ar" else "Account preferences saved.",
    )
    return redirect("profile-preferences")
