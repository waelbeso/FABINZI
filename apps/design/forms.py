from django import forms
from .models import GarmentDesign, GarmentDesignVersion


class GarmentDesignForm(forms.ModelForm):
    class Meta:
        model = GarmentDesign
        fields = ["title", "description", "category"]


class GarmentDesignVersionForm(forms.ModelForm):
    class Meta:
        model = GarmentDesignVersion
        fields = ["summary", "base_material", "construction_notes", "technical_specs"]
