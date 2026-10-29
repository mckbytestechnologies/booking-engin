import uuid
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from django.utils import timezone
from core.models import TimeStampedModel


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(f"'{value}' is not a valid IANA time zone (e.g. Asia/Kolkata).")


def _random_name(folder, filename):
    ext = Path(filename).suffix.lower()
    return f"{folder}/{uuid.uuid4().hex}{ext}"


def property_image_path(instance, filename):
    return _random_name("properties", filename)



def room_image_path(instance, filename):
    return _random_name("rooms", filename)

class Amenity(TimeStampedModel):
    """Reusable across properties and rooms."""

    class Scope(models.TextChoices):
        PROPERTY = "PROPERTY", "Property"
        ROOM = "ROOM", "Room"
        BOTH = "BOTH", "Property and room"

    name = models.CharField(max_length=100, unique=True)
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.BOTH)
    icon = models.CharField(max_length=50, blank=True, help_text="CSS icon class, optional")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "amenities"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Property(TimeStampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)

    address_line = models.CharField(max_length=255)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default="India")
    phone = models.CharField(max_length=20)
    email = models.EmailField()

    # Decision 5: one time zone per property.
    timezone = models.CharField(max_length=64, default="Asia/Kolkata", validators=[validate_timezone])
    # Decision 6: per-property standard times.
    check_in_time = models.TimeField(default="14:00")
    check_out_time = models.TimeField(default="11:00")
    # Decision 3: cancellation window. Decision 9: one tax rate.
    free_cancellation_hours = models.PositiveIntegerField(default=24)
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    amenities = models.ManyToManyField(Amenity, blank=True, related_name="properties")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name_plural = "properties"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(tax_percent__gte=0) & Q(tax_percent__lte=100),
                name="property_tax_percent_0_100",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.city})"

    def clean(self):
        super().clean()
        # Amenities are many-to-many, so scope is checked in forms/services (Module 3).
    
    def local_today(self):
        return timezone.now().astimezone(ZoneInfo(self.timezone)).date()


class PropertyImage(TimeStampedModel):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=property_image_path)
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Image for {self.property.name}"


class StaffAssignment(TimeStampedModel):
    """Property-scoped staff role. Super Admin is is_superuser, not a row here."""

    class Role(models.TextChoices):
        MANAGER = "MANAGER", "Property Manager"
        RECEPTIONIST = "RECEPTIONIST", "Receptionist"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_assignments")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="staff_assignments")
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "property"], name="uniq_staff_per_property"),
        ]

    def __str__(self):
        return f"{self.user} - {self.get_role_display()} @ {self.property.name}"