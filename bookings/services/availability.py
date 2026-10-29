from django.db.models import Exists, OuterRef
from django.utils import timezone

from rooms.models import Room

from ..models import Booking, RoomBlock
from .errors import InvalidDates

MAX_STAY_DAYS = 365


def validate_stay(check_in, check_out, today=None):
    """Business rules for dates. Called by every entry point (API, forms, staff)."""
    today = today or timezone.localdate()
    if check_in >= check_out:
        raise InvalidDates("Check-out must be after check-in.")
    if check_in < today:
        raise InvalidDates("Check-in cannot be in the past.")
    if (check_out - check_in).days > MAX_STAY_DAYS:
        raise InvalidDates(f"Stays are limited to {MAX_STAY_DAYS} nights.")


def rooms_with_availability(check_in, check_out, now=None):
    """Every bookable room, annotated with is_booked / is_blocked for the range."""
    booked = Booking.objects.filter(room=OuterRef("pk")).overlapping(check_in, check_out).blocking(now)
    blocked = RoomBlock.objects.filter(
        room=OuterRef("pk"), start_date__lt=check_out, end_date__gt=check_in
    )
    return (
        Room.objects.filter(operational_status=Room.OperationalStatus.ACTIVE, property__is_active=True)
        .annotate(is_booked=Exists(booked), is_blocked=Exists(blocked))
    )


def free_room_ids(check_in, check_out, now=None):
    qs = rooms_with_availability(check_in, check_out, now).filter(is_booked=False, is_blocked=False)
    return list(qs.values_list("id", flat=True))


def availability_groups(check_in, check_out, property_slug=None, now=None):
    """Rooms grouped by property, then by (room type, price, capacity, monthly flag)."""
    now = now or timezone.now()

    # Rooms with an unexpired PENDING hold: powers the "N people are booking now" tag.
    held_room_ids = set(
        Booking.objects.filter(status=Booking.Status.PENDING, expires_at__gt=now)
        .values_list("room_id", flat=True)
    )

    rooms = (
        rooms_with_availability(check_in, check_out, now)
        .select_related("property", "room_type", "bed_type")
        .prefetch_related("amenities", "images")
        .order_by("property__name", "room_type__name", "price_per_night", "number")
    )
    if property_slug:
        rooms = rooms.filter(property__slug=property_slug)

    by_property = {}
    for room in rooms:
        group = by_property.setdefault(room.property_id, {"property": room.property, "items": {}})
        key = f"{room.property_id}:{room.room_type_id}:{room.price_per_night}:{room.max_guests}:{int(room.monthly_only)}"
        item = group["items"].get(key)
        if item is None:
            images = list(room.images.all())
            item = group["items"][key] = {
                "key": key,
                "room_type": room.room_type.name,
                "price": room.price_per_night,
                "max_guests": room.max_guests,
                "bed_type": room.bed_type.name,
                "bed_count": room.bed_count,
                "monthly_only": room.monthly_only,
                "amenity_names": [a.name for a in room.amenities.all()],
                "cover_url": images[0].image.url if images else None,
                "image_urls": [i.image.url for i in images],
                "description": room.description,
                "free_room_ids": [],          # internal: never sent to clients
                "room_ids": [],               # internal: never sent to clients
            }
        item["room_ids"].append(room.id)
        if not room.is_booked and not room.is_blocked:
            item["free_room_ids"].append(room.id)

    result = []
    for group in by_property.values():
        items = list(group["items"].values())
        for item in items:
            item["available_count"] = len(item["free_room_ids"])
            item["holding_count"] = len(held_room_ids.intersection(item["room_ids"]))
        result.append({"property": group["property"], "items": items})
    return result

