from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from bookings.forms import GuestDetailsForm
from bookings.models import Booking
from bookings.services.availability import validate_stay
from bookings.services.errors import InvalidDates
from properties.models import Amenity, Property, PropertyImage
from rooms.models import Room, RoomImage
from PIL import Image

class BookingFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=100, label="Search")
    status = forms.ChoiceField(required=False, choices=[("", "All statuses")] + list(Booking.Status.choices))
    property = forms.ChoiceField(required=False)
    date_from = forms.DateField(required=False, input_formats=["%Y-%m-%d"],
                                widget=forms.DateInput(attrs={"type": "date"}), label="Check-in from")
    date_to = forms.DateField(required=False, input_formats=["%Y-%m-%d"],
                              widget=forms.DateInput(attrs={"type": "date"}), label="Check-in to")

    def __init__(self, *args, properties=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].choices = [("", "All properties")] + [(p.slug, p.name) for p in properties]


# ------------------------------------------------------------------ manual booking
DATE = dict(input_formats=["%Y-%m-%d"], widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))


class ManualSearchForm(forms.Form):
    property = forms.ChoiceField()
    check_in = forms.DateField(**DATE)
    check_out = forms.DateField(**DATE)

    def __init__(self, *args, properties=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.props = {p.slug: p for p in properties}
        self.fields["property"].choices = [(p.slug, p.name) for p in properties]
        if len(self.props) == 1:
            self.fields["property"].initial = next(iter(self.props))

    def clean(self):
        data = super().clean()
        prop = self.props.get(data.get("property"))
        if prop and data.get("check_in") and data.get("check_out"):
            try:                                   # the property's own "today", not the server's
                validate_stay(data["check_in"], data["check_out"], today=prop.local_today())
            except InvalidDates as exc:
                raise ValidationError(exc.message)
        return data


class ManualGuestForm(GuestDetailsForm):
    """Same guest rules as the public flow, plus the staff-only fields."""
    source = forms.ChoiceField(choices=[(Booking.Source.WALK_IN, "Walk-in"),
                                        (Booking.Source.ADMIN_MANUAL, "Phone / email")])
    internal_notes = forms.CharField(max_length=1000, required=False, label="Internal notes",
                                     widget=forms.Textarea(attrs={"rows": 2}))


# ------------------------------------------------------------------ properties and rooms
def unique_slug(name):
    base = slugify(name)[:200] or "property"
    slug, n = base, 2
    while Property.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ["name", "description", "address_line", "city", "state", "country", "phone", "email",
                  "timezone", "check_in_time", "check_out_time", "free_cancellation_hours",
                  "tax_percent", "amenities", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "check_in_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "check_out_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "amenities": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amenities"].queryset = Amenity.objects.filter(
            is_active=True, scope__in=[Amenity.Scope.PROPERTY, Amenity.Scope.BOTH])
        if not user.is_superuser:                       # only a superuser opens or closes a property
            del self.fields["is_active"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.pk:
            obj.slug = unique_slug(obj.name)            # the slug never changes later: it is in URLs
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["property", "room_type", "number", "floor", "description", "max_guests",
                  "base_occupancy", "bed_count", "bed_type", "size", "size_unit", "price_per_night",
                  "extra_guest_charge", "monthly_only", "amenities", "operational_status"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}),
                   "amenities": forms.CheckboxSelectMultiple}

    def __init__(self, *args, properties, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = properties            # only properties this user manages
        if self.instance.pk:
            self.fields["property"].disabled = True              # a room never moves: bookings reference it
        self.fields["amenities"].queryset = Amenity.objects.filter(
            is_active=True, scope__in=[Amenity.Scope.ROOM, Amenity.Scope.BOTH])

    def clean(self):
        data = super().clean()
        prop, number = data.get("property"), (data.get("number") or "").strip()
        if prop and number and Room.objects.filter(property=prop, number=number) \
                .exclude(pk=self.instance.pk).exists():
            self.add_error("number", f"Room {number} already exists at {prop.name}.")
        OOS = Room.OperationalStatus.OUT_OF_SERVICE
        if self.instance.pk and data.get("operational_status") == OOS and self.instance.operational_status != OOS:
            today = self.instance.property.local_today()
            n = Booking.objects.filter(
                room=self.instance, status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN],
                check_out__gt=today).count()
            if n:
                self.add_error("operational_status",
                               f"This room has {n} upcoming or current booking(s). Cancel or move them first.")
        return data


class _ImageForm(forms.ModelForm):
    MAX_BYTES = 5 * 1024 * 1024

    def clean_image(self):
        f = self.cleaned_data["image"]
        if f.size > self.MAX_BYTES:
            raise ValidationError("Image must be 5 MB or smaller.")
        return f                                        # ImageField already verified it is a real image


class PropertyImageForm(_ImageForm):
    class Meta:
        model = PropertyImage
        fields = ["image", "caption", "sort_order"]


class RoomImageForm(_ImageForm):
    class Meta:
        model = RoomImage
        fields = ["image", "caption", "sort_order"]

class _ImageForm(forms.ModelForm):
    MAX_BYTES = 5 * 1024 * 1024
    MAX_PIXELS = 25_000_000                 # blocks "decompression bomb" images
    FORMATS = {"JPEG", "PNG", "WEBP"}

    def clean_image(self):
        f = self.cleaned_data["image"]
        if f.size > self.MAX_BYTES:
            raise ValidationError("Image must be 5 MB or smaller.")
        f.seek(0)
        with Image.open(f) as im:
            if im.format not in self.FORMATS:
                raise ValidationError("Only JPEG, PNG or WebP images are allowed.")
            if im.width * im.height > self.MAX_PIXELS:
                raise ValidationError("Image dimensions are too large.")
        f.seek(0)
        return f