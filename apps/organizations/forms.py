from django import forms
from django.utils import timezone

from .models import DesignerProfile, ManufacturerProfile, Organization


def _plan_choices(kind):
    from apps.subscriptions.services import onboarding_plan_options

    starter, pro = onboarding_plan_options(kind)
    rows = []
    for plan in (starter, pro):
        price = f"{plan.monthly_price} {plan.currency}/month" if plan.monthly_price else "Free"
        if kind == Organization.Kind.DESIGNER:
            capacity = f"Designs {plan.designer_active_design_limit} · Artworks {plan.designer_active_artwork_limit} · Team {plan.team_subaccount_limit}"
        else:
            capacity = f"Offers {plan.manufacturer_monthly_offer_limit}/month · Team {plan.team_subaccount_limit}"
        rows.append((str(plan.pk), f"{plan.public_name_en} / {plan.public_name_ar} — {price} — {capacity}"))
    return rows, starter


def _selection_initial(profile):
    organization = getattr(profile, "organization", None)
    if not organization:
        return None
    try:
        selection = organization.onboarding_application.plan_selection
    except (AttributeError, ObjectDoesNotExist):
        return None
    return str(selection.selected_plan_policy_id)


from django.core.exceptions import ObjectDoesNotExist


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["display_name", "legal_name", "email", "phone", "website", "address_line1", "address_line2", "city", "region", "country"]


class DesignerOnboardingForm(forms.ModelForm):
    accept_terms = forms.BooleanField(required=True)
    plan_policy_id = forms.ChoiceField(required=True, label="Plan / الخطة")

    class Meta:
        model = DesignerProfile
        fields = ["studio_name", "portfolio_url", "legal_registration_number", "tax_number", "payout_information", "plan_policy_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices, starter = _plan_choices(Organization.Kind.DESIGNER)
        self.fields["plan_policy_id"].choices = choices
        if not self.is_bound:
            self.initial.setdefault("plan_policy_id", _selection_initial(self.instance) or str(starter.pk))

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.terms_accepted = self.cleaned_data["accept_terms"]
        if obj.terms_accepted and not obj.terms_accepted_at:
            obj.terms_accepted_at = timezone.now()
        if commit:
            obj.save()
        return obj


class ManufacturerOnboardingForm(forms.ModelForm):
    accept_terms = forms.BooleanField(required=True)
    plan_policy_id = forms.ChoiceField(required=True, label="Plan / الخطة")

    class Meta:
        model = ManufacturerProfile
        fields = ["commercial_registration", "tax_number", "google_maps_url", "primary_contact_person", "contact_job_title", "whatsapp", "daily_capacity", "monthly_capacity", "payout_information", "plan_policy_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices, starter = _plan_choices(Organization.Kind.MANUFACTURER)
        self.fields["plan_policy_id"].choices = choices
        if not self.is_bound:
            self.initial.setdefault("plan_policy_id", _selection_initial(self.instance) or str(starter.pk))

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.terms_accepted = self.cleaned_data["accept_terms"]
        if obj.terms_accepted and not obj.terms_accepted_at:
            obj.terms_accepted_at = timezone.now()
        if commit:
            obj.save()
        return obj
