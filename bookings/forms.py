from django import forms
from django.utils import timezone

from .services.availability import validate_stay
from .services.errors import InvalidDates
from .validators import normalize_phone


class SearchForm(forms.Form):
    check_in = forms.DateField(input_formats=["%Y-%m-%d"])
    check_out = forms.DateField(input_formats=["%Y-%m-%d"])
    property = forms.SlugField(required=False)

    def clean(self):
        data = super().clean()
        if data.get("check_in") and data.get("check_out"):
            try:
                validate_stay(data["check_in"], data["check_out"], timezone.localdate())
            except InvalidDates as exc:
                raise forms.ValidationError(exc.message)
        return data


class GuestDetailsForm(forms.Form):
    """Single source of truth for guest-detail rules.
    Used by the HTML flow and by the JSON API (through the serializer)."""

    first_name = forms.CharField(max_length=100, strip=True)
    last_name = forms.CharField(max_length=100, strip=True)
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=30)
    special_request = forms.CharField(max_length=500, required=False, strip=True)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        return normalize_phone(self.cleaned_data["phone"])