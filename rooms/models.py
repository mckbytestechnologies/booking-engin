from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from core.models import TimeStampedModel
from properties.models import Amenity, Property, room_image_path


class RoomType(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)  # Deluxe, Suite, Standard...
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BedType(TimeStampedModel):
    """A table (not hard-coded choices) so admins can add types without a deploy."""

    name = models.CharField(max_length=50, unique=True)  # Single, Double, Queen, King, Twin

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Room(TimeStampedModel):
    class OperationalStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        OUT_OF_SERVICE = "OUT_OF_SERVICE", "Out of service"  # long-term; short blocks use RoomBlock

    class HousekeepingStatus(models.TextChoices):
        CLEAN = "CLEAN", "Clean"
        DIRTY = "DIRTY", "Dirty"
        INSPECTING = "INSPECTING", "Inspecting"

    class SizeUnit(models.TextChoices):
        SQFT = "SQFT", "sq ft"
        SQM = "SQM", "sq m"

    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="rooms")
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    number = models.CharField(max_length=20)
    floor = models.SmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)

    max_guests = models.PositiveSmallIntegerField(default=2)
    base_occupancy = models.PositiveSmallIntegerField(default=2)
    bed_count = models.PositiveSmallIntegerField(default=1)
    bed_type = models.ForeignKey(BedType, on_delete=models.PROTECT, related_name="rooms")
    size = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    size_unit = models.CharField(max_length=4, choices=SizeUnit.choices, default=SizeUnit.SQFT)

    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    extra_guest_charge = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    monthly_only = models.BooleanField(default=False, help_text="Bookable in whole months only")

    amenities = models.ManyToManyField(Amenity, blank=True, related_name="rooms")

    operational_status = models.CharField(
        max_length=20, choices=OperationalStatus.choices, default=OperationalStatus.ACTIVE, db_index=True
    )
    housekeeping_status = models.CharField(
        max_length=20, choices=HousekeepingStatus.choices, default=HousekeepingStatus.CLEAN
    )

    class Meta:
        ordering = ["property", "number"]
        constraints = [
            models.UniqueConstraint(fields=["property", "number"], name="uniq_room_number_per_property"),
            models.CheckConstraint(condition=Q(price_per_night__gte=0), name="room_price_non_negative"),
            models.CheckConstraint(condition=Q(extra_guest_charge__gte=0), name="room_extra_charge_non_negative"),
            models.CheckConstraint(condition=Q(max_guests__gte=1), name="room_max_guests_min_1"),
            models.CheckConstraint(condition=Q(base_occupancy__gte=1), name="room_base_occupancy_min_1"),
            models.CheckConstraint(
                condition=Q(base_occupancy__lte=F("max_guests")), name="room_base_occupancy_lte_max"
            ),
        ]
        indexes = [models.Index(fields=["property", "operational_status"])]

    def __str__(self):
        return f"{self.property.name} - Room {self.number}"


class RoomImage(TimeStampedModel):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=room_image_path)
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]