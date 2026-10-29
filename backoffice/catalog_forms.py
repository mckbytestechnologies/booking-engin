from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from bookings.models import RoomBlock
from properties.models import Amenity, Property, StaffAssignment
from rooms.models import BedType, Room, RoomType

User = get_user_model()


class _NamedForm(forms.ModelForm):
    """Trims the name and rejects case-insensitive duplicates ("wifi" vs "WiFi")."""

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = self._meta.model.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("This name already exists.")
        return name


class AmenityForm(_NamedForm):
    class Meta:
        model = Amenity
        fields = ["name", "scope", "icon", "is_active"]


class BedTypeForm(_NamedForm):
    class Meta:
        model = BedType
        fields = ["name"]


class RoomTypeForm(_NamedForm):
    class Meta:
        model = RoomType
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class StaffForm(forms.Form):
    """Gives someone a role at a property. A new email creates the account; an existing
    email just gains the role. Staff accounts do NOT get Django-admin access (is_staff stays off)."""

    email = forms.EmailField(max_length=254)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    phone = forms.CharField(max_length=20, required=False)
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False), required=False,
        help_text="Required for a new account. Leave blank to give an existing account a role.")
    property = forms.ModelChoiceField(Property.objects.none())
    role = forms.ChoiceField(choices=StaffAssignment.Role.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.fields["property"].queryset = Property.objects.filter(is_active=True).order_by("name")

    def clean(self):
        data = super().clean()
        email = (data.get("email") or "").strip().lower()
        if not email:
            return data
        self.user = User.objects.filter(email=email).first()
        password = data.get("password")
        if self.user is None:
            if not password:
                self.add_error("password", "A password is required for a new account.")
            else:
                try:
                    validate_password(password)
                except ValidationError as exc:
                    self.add_error("password", exc)
        elif data.get("property") and StaffAssignment.objects.filter(
                user=self.user, property=data["property"]).exists():
            self.add_error("property", "This person already has a role at this property. Edit it from the list.")
        return data

    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        email = d["email"].strip().lower()
        user = self.user
        if user is None:
            user = User(username=email[:150], email=email, first_name=d.get("first_name", ""),
                        last_name=d.get("last_name", ""), phone=d.get("phone", ""))
            user.set_password(d["password"])
            user.save()
        return StaffAssignment.objects.create(user=user, property=d["property"], role=d["role"])


class StaffRoleForm(forms.ModelForm):
    class Meta:
        model = StaffAssignment
        fields = ["role"]


class RoomBlockForm(forms.ModelForm):
    class Meta:
        model = RoomBlock
        fields = ["room", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
        help_texts = {"end_date": "The room is free again on this date (the last blocked night is the day before)."}

    def __init__(self, *args, rooms=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = rooms if rooms is not None else Room.objects.none()
        self.fields["room"].queryset = qs.select_related("property").order_by("property__name", "number")

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end <= start:
            self.add_error("end_date", "The end date must be after the start date.")
        return data