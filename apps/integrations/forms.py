import json
from django import forms
from .models import IntegrationConfig

class IntegrationConfigAdminForm(forms.ModelForm):
    secret_payload = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), help_text='Write-only JSON object, e.g. {"api_key":"..."}. Leave blank to keep existing secrets.', label="Secret values (write-only JSON)")
    class Meta:
        model = IntegrationConfig
        fields = ("provider", "enabled", "config")
    def clean_secret_payload(self):
        raw = self.cleaned_data.get("secret_payload", "")
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Secrets must be a valid JSON object.") from exc
        if not isinstance(value, dict):
            raise forms.ValidationError("Secrets must be a JSON object.")
        return value
