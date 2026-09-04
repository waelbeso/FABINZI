from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class PublicSignupForm(UserCreationForm):
    """Create the single FABINZI web identity without assigning a business role."""

    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data.get("first_name", "").strip()
        user.last_name = self.cleaned_data.get("last_name", "").strip()
        if commit:
            user.save()
        return user


class AccountPreferencesForm(forms.Form):
    """Profile/language/theme preferences with backward-compatible secure email handling.

    The production preferences surface posts profile/language/theme separately from
    email changes. The optional email/current-password fields remain accepted here
    so older direct clients/tests cannot bypass the same password and collision
    checks when they still submit the combined payload.
    """

    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    language = forms.ChoiceField(choices=User.Language.choices)
    theme = forms.ChoiceField(choices=User.Theme.choices)
    current_password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Required only when changing the account email address.",
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        if not args and "initial" not in kwargs:
            kwargs["initial"] = {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "language": user.language_preference,
                "theme": user.theme_preference,
            }
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return ""
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        if "email" in self.data and email and email.lower() != str(self.user.email or "").strip().lower():
            password = cleaned.get("current_password") or ""
            if not password:
                self.add_error("current_password", "Enter your current password to change the account email address.")
            elif not self.user.check_password(password):
                self.add_error("current_password", "Current password is incorrect.")
        return cleaned

    def save(self):
        update_fields = []
        if "first_name" in self.data:
            self.user.first_name = self.cleaned_data.get("first_name", "").strip()
            update_fields.append("first_name")
        if "last_name" in self.data:
            self.user.last_name = self.cleaned_data.get("last_name", "").strip()
            update_fields.append("last_name")
        if "email" in self.data and self.cleaned_data.get("email"):
            self.user.email = self.cleaned_data["email"]
            update_fields.append("email")
        if "language" in self.data:
            self.user.language_preference = self.cleaned_data["language"]
            update_fields.append("language_preference")
        if "theme" in self.data:
            self.user.theme_preference = self.cleaned_data["theme"]
            update_fields.append("theme_preference")
        if update_fields:
            self.user.save(update_fields=update_fields)
        return self.user


class AccountEmailChangeForm(forms.Form):
    email = forms.EmailField(required=True)
    current_password = forms.CharField(
        required=True,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        if not args and "initial" not in kwargs:
            kwargs["initial"] = {"email": user.email}
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Current password is incorrect.")
        return password

    def save(self):
        self.user.email = self.cleaned_data["email"]
        self.user.save(update_fields=["email"])
        return self.user
