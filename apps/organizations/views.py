from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import DesignerOnboardingForm, ManufacturerOnboardingForm, OrganizationForm
from .models import Membership, OnboardingApplication, Organization
from .services import create_designer_onboarding, create_manufacturer_onboarding, submit_application


def _owned_application(user, kind):
    membership = Membership.objects.filter(user=user, is_active=True, organization__kind=kind).select_related("organization", "organization__onboarding_application").order_by("joined_at").first()
    return membership.organization.onboarding_application if membership else None


@login_required
def designer_portal(request):
    application = _owned_application(request.user, Organization.Kind.DESIGNER)
    if application:
        return render(request, "organizations/portal_dashboard.html", {"application": application, "portal_kind": "designer"})
    if request.method == "POST":
        org_form = OrganizationForm(request.POST, prefix="org")
        profile_form = DesignerOnboardingForm(request.POST, prefix="profile")
        if org_form.is_valid() and profile_form.is_valid():
            org_data = org_form.cleaned_data.copy()
            profile_data = profile_form.cleaned_data.copy()
            profile_data.pop("accept_terms", None)
            profile_data["terms_accepted"] = True
            profile_data["terms_accepted_at"] = timezone.now()
            create_designer_onboarding(user=request.user, organization_data=org_data, profile_data=profile_data, request=request)
            messages.success(request, "Designer onboarding draft created.")
            return redirect("designer")
    else:
        org_form = OrganizationForm(prefix="org")
        profile_form = DesignerOnboardingForm(prefix="profile")
    return render(request, "organizations/onboarding_form.html", {"org_form": org_form, "profile_form": profile_form, "portal_kind": "designer"})


@login_required
def manufacturer_portal(request):
    application = _owned_application(request.user, Organization.Kind.MANUFACTURER)
    if application:
        return render(request, "organizations/portal_dashboard.html", {"application": application, "portal_kind": "manufacturer"})
    if request.method == "POST":
        org_form = OrganizationForm(request.POST, prefix="org")
        profile_form = ManufacturerOnboardingForm(request.POST, prefix="profile")
        if org_form.is_valid() and profile_form.is_valid():
            org_data = org_form.cleaned_data.copy()
            profile_data = profile_form.cleaned_data.copy()
            profile_data.pop("accept_terms", None)
            profile_data["terms_accepted"] = True
            profile_data["terms_accepted_at"] = timezone.now()
            create_manufacturer_onboarding(user=request.user, organization_data=org_data, profile_data=profile_data, request=request)
            messages.success(request, "Manufacturer onboarding draft created.")
            return redirect("manufacturer")
    else:
        org_form = OrganizationForm(prefix="org")
        profile_form = ManufacturerOnboardingForm(prefix="profile")
    return render(request, "organizations/onboarding_form.html", {"org_form": org_form, "profile_form": profile_form, "portal_kind": "manufacturer"})


@login_required
def submit_onboarding(request, pk):
    application = get_object_or_404(OnboardingApplication, pk=pk)
    if request.method != "POST":
        return redirect("designer" if application.organization.kind == Organization.Kind.DESIGNER else "manufacturer")
    try:
        submit_application(application=application, actor=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Application submitted for FABINZI review.")
    return redirect("designer" if application.organization.kind == Organization.Kind.DESIGNER else "manufacturer")
