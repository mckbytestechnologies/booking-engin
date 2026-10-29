from decimal import Decimal, InvalidOperation

from rooms.models import Room

from .errors import InvalidSelection


def parse_key(key):
    """Card key -> room attributes. The key is a *filter*, never a price source:
    prices always come from the Room rows themselves."""
    parts = str(key).split(":")
    if len(parts) != 5 or parts[4] not in ("0", "1"):
        raise InvalidSelection("Unknown room selection.")
    try:
        price = Decimal(parts[2])
        parsed = {
            "property_id": int(parts[0]),
            "room_type_id": int(parts[1]),
            "price_per_night": price,
            "max_guests": int(parts[3]),
            "monthly_only": parts[4] == "1",
        }
    except (ValueError, InvalidOperation):
        raise InvalidSelection("Unknown room selection.")
    if not price.is_finite():
        raise InvalidSelection("Unknown room selection.")
    return parsed


def candidate_rooms(parsed):
    return (
        Room.objects.filter(
            operational_status=Room.OperationalStatus.ACTIVE,
            property__is_active=True,
            **parsed,
        )
        .select_related("property")
        .order_by("id")
    )