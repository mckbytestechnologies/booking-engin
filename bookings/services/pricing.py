from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .errors import PricingError

CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(d, months):
    """31 Jan + 1 month = 28/29 Feb. Same rule as the page's JavaScript."""
    year, month0 = divmod(d.month - 1 + months, 12)
    year += d.year
    month = month0 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def whole_months(check_in, check_out):
    for m in range(1, 25):
        if add_months(check_in, m) == check_out:
            return m
    return 0


@dataclass(frozen=True)
class RoomQuote:
    nights: int
    guests: int
    price_per_night: Decimal
    room_charge: Decimal
    extra_guest_charge: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def quote_room(room, check_in, check_out, guests):
    """Price one room for a stay. Pure function: no database writes."""
    nights = (check_out - check_in).days
    if nights < 1:
        raise PricingError("Stay must be at least one night.")
    if room.monthly_only and not whole_months(check_in, check_out):
        raise PricingError("This room can only be booked for whole months.")
    if not 1 <= guests <= room.max_guests:
        raise PricingError(f"This room sleeps at most {room.max_guests} guests.")

    room_charge = money(room.price_per_night * nights)
    extra_guests = max(0, guests - room.base_occupancy)
    extra = money(room.extra_guest_charge * extra_guests * nights)
    subtotal = room_charge + extra
    tax = money(subtotal * room.property.tax_percent / 100)
    return RoomQuote(nights, guests, room.price_per_night, room_charge, extra,
                     subtotal, tax, subtotal + tax)