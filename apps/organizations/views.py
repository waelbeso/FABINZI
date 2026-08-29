from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import DesignerOnboardingForm, ManufacturerOnboardingForm, OrganizationForm
from .models import Membership, OnboardingApplication, Organization
from .services import create_designer_onboarding, create_manufacturer_onboarding, require_org_access, submit_application, update_onboarding


def _owned_application(user, kind):
    membership = Membership.objects.filter(user=user, is_active=True, organization__kind=kind).select_related("organization", "organization__onboarding_application").order_by("joined_at").first()
    return membership.organization.onboarding_application if membership else None


def _profile_form_class(kind):
    return DesignerOnboardingForm if kind == Organization.Kind.DESIGNER else ManufacturerOnboardingForm


@login_required
def designer_portal(request):
    return _portal(request, Organization.Kind.DESIGNER)


@login_required
def manufacturer_portal(request):
    return _portal(request, Organization.Kind.MANUFACTURER)


def _portal(request, kind):
    application = _owned_application(request.user, kind)
    portal_kind = "designer" if kind == Organization.Kind.DESIGNER else "manufacturer"
    if application:
        return render(request, "organizations/portal_dashboard.html", {"application": application, "portal_kind": portal_kind})
    profile_form_class = _profile_form_class(kind)
    if request.method == "POST":
        org_form = OrganizationForm(request.POST, prefix="org")
        profile_form = profile_form_class(request.POST, prefix="profile")
        if org_form.is_valid() and profile_form.is_valid():
            org_data = org_form.cleaned_data.copy()
            profile_data = profile_form.cleaned_data.copy()
            profile_data.pop("accept_terms", None)
            profile_data["terms_accepted"] = True
            profile_data["terms_accepted_at"] = timezone.now()
            creator = create_designer_onboarding if kind == Organization.Kind.DESIGNER else create_manufacturer_onboarding
            creator(user=request.user, organization_data=org_data, profile_data=profile_data, request=request)
            messages.success(request, f"{portal_kind.title()} onboarding draft created.")
            return redirect(portal_kind)
    else:
        org_form = OrganizationForm(prefix="org")
        profile_form = profile_form_class(prefix="profile")
    return render(request, "organizations/onboarding_form.html", {"org_form": org_form, "profile_form": profile_form, "portal_kind": portal_kind, "editing": False})


@login_required
def edit_onboarding(request, pk):
    application = get_object_or_404(OnboardingApplication.objects.select_related("organization"), pk=pk)
    require_org_access(request.user, application.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
        messages.error(request, "This application is locked while under review or after a final decision.")
        return redirect("designer" if application.organization.kind == Organization.Kind.DESIGNER else "manufacturer")
    org = application.organization
    portal_kind = "designer" if org.kind == Organization.Kind.DESIGNER else "manufacturer"
    profile = org.designer_profile if org.kind == Organization.Kind.DESIGNER else org.manufacturer_profile
    profile_form_class = _profile_form_class(org.kind)
    if request.method == "POST":
        org_form = OrganizationForm(request.POST, instance=org, prefix="org")
        profile_form = profile_form_class(request.POST, instance=profile, prefix="profile")
        if org_form.is_valid() and profile_form.is_valid():
            org_data = org_form.cleaned_data.copy()
            profile_data = profile_form.cleaned_data.copy()
            profile_data.pop("accept_terms", None)
            profile_data["terms_accepted"] = True
            if not profile.terms_accepted_at:
                profile_data["terms_accepted_at"] = timezone.now()
            try:
                update_onboarding(application=application, actor=request.user, organization_data=org_data, profile_data=profile_data, request=request)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Onboarding draft updated.")
                return redirect(portal_kind)
    else:
        org_form = OrganizationForm(instance=org, prefix="org")
        profile_form = profile_form_class(instance=profile, prefix="profile", initial={"accept_terms": profile.terms_accepted})
    return render(request, "organizations/onboarding_form.html", {"org_form": org_form, "profile_form": profile_form, "portal_kind": portal_kind, "editing": True, "application": application})


@login_required
def submit_onboarding(request, pk):
    application = get_object_or_404(OnboardingApplication, pk=pk)
    destination = "designer" if application.organization.kind == Organization.Kind.DESIGNER else "manufacturer"
    if request.method != "POST":
        return redirect(destination)
    try:
        submit_application(application=application, actor=request.user, request=request)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Application submitted for FABINZI review.")
    return redirect(destination)
