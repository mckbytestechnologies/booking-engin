import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from rooms.models import Room

from ..models import Booking, RoomBlock, generate_reference
from .availability import validate_stay
from .errors import InvalidSelection, RoomUnavailable
from .pricing import money, quote_room
from .selection import candidate_rooms, parse_key
from ..models import Booking, BookingHistory, RoomBlock, generate_reference
from .history import record

HOLD_MINUTES = 30
MAX_ROOMS_PER_BOOKING = 10


@dataclass(frozen=True)
class Selection:
    key: str
    quantity: int = 1
    guests: Optional[int] = None      # per room; defaults to the room's base occupancy


def _unavailable_ids(room_ids, check_in, check_out, now):
    booked = Booking.objects.filter(room_id__in=room_ids).overlapping(check_in, check_out) \
        .blocking(now).values_list("room_id", flat=True)
    blocked = RoomBlock.objects.filter(
        room_id__in=room_ids, start_date__lt=check_out, end_date__gt=check_in
    ).values_list("room_id", flat=True)
    return set(booked) | set(blocked)


def _check_selections(selections):
    if not selections:
        raise InvalidSelection("Select at least one room.")
    if sum(s.quantity for s in selections) > MAX_ROOMS_PER_BOOKING:
        raise InvalidSelection(f"At most {MAX_ROOMS_PER_BOOKING} rooms per booking.")


def quote_selections(selections, check_in, check_out, now=None):
    """Read-only price preview. Not a reservation: availability may change after this."""
    now = now or timezone.now()
    validate_stay(check_in, check_out)
    _check_selections(selections)

    lines, used = [], set()
    for sel in selections:
        rooms = list(candidate_rooms(parse_key(sel.key)))
        gone = _unavailable_ids([r.id for r in rooms], check_in, check_out, now) | used
        free = [r for r in rooms if r.id not in gone]
        if len(free) < sel.quantity:
            raise RoomUnavailable("Not enough rooms are free for these dates.")
        chosen = free[: sel.quantity]
        used.update(r.id for r in chosen)
        for room in chosen:
            q = quote_room(room, check_in, check_out, sel.guests or room.base_occupancy)
            lines.append({"key": sel.key, "room_type": room.room_type.name, "quote": q})

    return {
        "nights": (check_out - check_in).days,
        "count": len(lines),
        "guests": sum(l["quote"].guests for l in lines),
        "subtotal": sum((l["quote"].subtotal for l in lines), Decimal("0")),
        "tax": sum((l["quote"].tax for l in lines), Decimal("0")),
        "total": sum((l["quote"].total for l in lines), Decimal("0")),
        "lines": lines,
    }


def _unique_reference():
    while True:
        ref = generate_reference()
        if not Booking.objects.filter(reference=ref).exists():
            return ref

def create_hold(*, selections, check_in, check_out, guest, user=None,
                source=Booking.Source.ONLINE, created_by=None, now=None,
                today=None, confirmed=False):
    """Reserve rooms. Online: PENDING for HOLD_MINUTES. Staff (confirmed=True): CONFIRMED, no expiry.

    The only place that creates bookings. Availability is re-checked here while the
    candidate room rows are locked, so simultaneous requests are serialised by the database.
    """
    now = now or timezone.now()
    validate_stay(check_in, check_out, today)
    _check_selections(selections)

    group_ref = "G-" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(8))
    status = Booking.Status.CONFIRMED if confirmed else Booking.Status.PENDING
    expires_at = None if confirmed else now + timedelta(minutes=HOLD_MINUTES)

    with transaction.atomic():
        plans = [(sel, [r.id for r in candidate_rooms(parse_key(sel.key))]) for sel in selections]
        all_ids = sorted({rid for _, ids in plans for rid in ids})

        # Lock in ascending id order so concurrent multi-room requests cannot deadlock.
        locked = {
            r.id: r
            for r in Room.objects.select_for_update().select_related("property")
            .filter(pk__in=all_ids, operational_status=Room.OperationalStatus.ACTIVE,
                    property__is_active=True)
            .order_by("id")
        }
        gone = _unavailable_ids(list(locked), check_in, check_out, now)

        used, bookings = set(), []
        for sel, ids in plans:
            free = [locked[i] for i in ids if i in locked and i not in gone and i not in used]
            if len(free) < sel.quantity:
                raise RoomUnavailable("Sorry, those rooms were just taken. Please search again.")
            for room in free[: sel.quantity]:
                used.add(room.id)
                q = quote_room(room, check_in, check_out, sel.guests or room.base_occupancy)
                booking = Booking.objects.create(
                    reference=_unique_reference(), group_ref=group_ref,
                    property=room.property, room=room, customer=user,
                    customer_name=f"{guest['first_name']} {guest['last_name']}".strip(),
                    customer_email=guest["email"], customer_phone=guest["phone"],
                    check_in=check_in, check_out=check_out, guests=q.guests,
                    price_per_night=q.price_per_night, additional_charges=q.extra_guest_charge,
                    tax_amount=q.tax, total_amount=q.total,
                    status=status, payment_status=Booking.PaymentStatus.UNPAID,
                    source=source, expires_at=expires_at,
                    special_requests=guest.get("special_request", ""),
                    internal_notes=guest.get("internal_notes", ""), created_by=created_by,
                )
                record(booking, BookingHistory.Action.CREATED, to_status=status, actor=created_by,
                       actor_label=None if created_by else "guest",
                       details={"source": source, "group_ref": group_ref})
                bookings.append(booking)

    return {
        "group_ref": group_ref,
        "bookings": bookings,
        "total": money(sum((b.total_amount for b in bookings), Decimal("0"))),
        "expires_at": expires_at,
    }