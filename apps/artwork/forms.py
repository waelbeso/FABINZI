from django import forms
from .models import Artwork, ArtworkVersion, DesignedProduct


class ArtworkForm(forms.ModelForm):
    class Meta:
        model = Artwork
        fields = ["title", "description", "tags"]


class ArtworkVersionForm(forms.ModelForm):
    class Meta:
        model = ArtworkVersion
        fields = ["color_profile", "production_notes", "metadata"]


class DesignedProductForm(forms.ModelForm):
    class Meta:
        model = DesignedProduct
        fields = ["title", "description", "garment_version", "artwork_version"]
