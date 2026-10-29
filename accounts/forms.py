from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email", max_length=254,
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    # One message for unknown email and wrong password: no account enumeration at login.
    error_messages = {
        "invalid_login": "Incorrect email or password.",
        "inactive": "This account is inactive.",
    }


class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=100, strip=True)
    last_name = forms.CharField(max_length=100, strip=True)
    email = forms.EmailField(max_length=150)
    password1 = forms.CharField(label="Password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists. Please log in.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                candidate = User(username=data.get("email", ""), email=data.get("email", ""),
                                 first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
                try:
                    validate_password(p1, candidate)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return data


class CodeForm(forms.Form):
    code = forms.RegexField(regex=r"^\d{6}$", strip=True, label="6-digit code",
                            error_messages={"invalid": "Enter the 6-digit code."},
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}))

class ExtensionForm(forms.Form):
    new_check_out = forms.DateField(
        label="New check-out date", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}))