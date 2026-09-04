from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import activate

from apps.checkout.models import Cart, CustomerPurchase
from apps.notifications.models import Notification
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.storefront.models import StudioProject
from .forms import AccountPreferencesForm, PublicSignupForm


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


def _business_memberships(user):
    return list(
        Membership.objects.filter(
            user=user,
            is_active=True,
            organization__kind__in=[Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER],
        )
        .select_related("organization", "organization__onboarding_application")
        .order_by("organization__kind", "joined_at", "id")
    )


@login_required
def app_home(request):
    purchases_qs = CustomerPurchase.objects.filter(customer=request.user)
    recent_purchases = purchases_qs.prefetch_related("child_orders__item__store_product").order_by("-created_at")[:4]
    active_studio_qs = StudioProject.objects.filter(customer=request.user).exclude(status=StudioProject.Status.ARCHIVED)
    studio_projects = active_studio_qs.select_related("product", "product__storefront", "variant").order_by("-updated_at")[:4]
    active_cart = Cart.objects.filter(customer=request.user, status=Cart.Status.ACTIVE).first()
    cart_item_count = active_cart.items.count() if active_cart else 0
    unread_notifications = Notification.objects.filter(recipient=request.user, is_read=False).count()
    business_memberships = _business_memberships(request.user)
    return render(
        request,
        "accounts/app_home.html",
        {
            "recent_purchases": recent_purchases,
            "studio_projects": studio_projects,
            "active_cart": active_cart,
            "cart_item_count": cart_item_count,
            "active_studio_project_count": active_studio_qs.count(),
            "purchase_count": purchases_qs.count(),
            "unread_notifications": unread_notifications,
            "business_memberships": business_memberships,
            "has_professional_business": bool(business_memberships),
        },
    )


@login_required
def business_start(request):
    memberships = _business_memberships(request.user)
    by_kind = {membership.organization.kind: membership for membership in memberships}
    return render(
        request,
        "accounts/business_start.html",
        {
            "designer_membership": by_kind.get(Organization.Kind.DESIGNER),
            "manufacturer_membership": by_kind.get(Organization.Kind.MANUFACTURER),
        },
    )


@login_required
def profile_preferences(request):
    if request.method == "POST":
        form = AccountPreferencesForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save()
            activate(user.language_preference)
            request.session["django_language"] = user.language_preference
            messages.success(
                request,
                "تم حفظ تفضيلات الحساب."
                if user.language_preference == "ar"
                else "Account preferences saved.",
            )
            return redirect("profile-preferences")
    else:
        form = AccountPreferencesForm(user=request.user)
    return render(request, "accounts/preferences.html", {"form": form})
