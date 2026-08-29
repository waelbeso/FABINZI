from django import forms
from django.utils import timezone

from .models import DesignerProfile, ManufacturerProfile, Organization


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["display_name", "legal_name", "email", "phone", "website", "address_line1", "address_line2", "city", "region", "country"]


class DesignerOnboardingForm(forms.ModelForm):
    accept_terms = forms.BooleanField(required=True)

    class Meta:
        model = DesignerProfile
        fields = ["studio_name", "portfolio_url", "legal_registration_number", "tax_number", "payout_information"]

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

    class Meta:
        model = ManufacturerProfile
        fields = ["commercial_registration", "tax_number", "google_maps_url", "primary_contact_person", "contact_job_title", "whatsapp", "daily_capacity", "monthly_capacity", "payout_information"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.terms_accepted = self.cleaned_data["accept_terms"]
        if obj.terms_accepted and not obj.terms_accepted_at:
            obj.terms_accepted_at = timezone.now()
        if commit:
            obj.save()
        return obj
