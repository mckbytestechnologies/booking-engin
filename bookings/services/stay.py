from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from rooms.models import Room

from ..models import (Booking, BookingHistory, EmailNotification, ExtensionRequest,
                      RefundTask, RoomBlock)
from .availability import MAX_STAY_DAYS
from .balance import ZERO, outstanding, paid_amount
from .cancellation import assess
from .errors import (ExtensionConflict, InvalidDates, InvalidTransition, NotPermitted,
                     PaymentOutstanding, PricingError, ReasonRequired, UnknownBooking)
from .history import record
from .notifications import inr, queue_email
from .pricing import money, whole_months
from .transitions import actor_kinds, apply_transition

S = Booking.Status
P = Booking.PaymentStatus
H = BookingHistory.Action
E = ExtensionRequest.Status
K = EmailNotification.Kind


# ---------------------------------------------------------------- helpers
def _lock_booking(booking_id):
    try:
        return Booking.objects.select_for_update().get(pk=booking_id)
    except Booking.DoesNotExist:
        raise UnknownBooking("Unknown booking.")


def _lock_extension(ext_id):
    try:
        return ExtensionRequest.objects.select_for_update().get(pk=ext_id)
    except ExtensionRequest.DoesNotExist:
        raise UnknownBooking("Unknown extension request.")


def _require(actor, booking, kind):
    if kind not in actor_kinds(actor, booking):
        raise NotPermitted("You are not allowed to do this.")


def _local_today(prop, now):
    return now.astimezone(ZoneInfo(prop.timezone)).date()


# ---------------------------------------------------------------- check-in
def check_in(booking_id, *, actor, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        b = _lock_booking(booking_id)
        _require(actor, b, "receptionist")
        if b.status != S.CONFIRMED:
            raise InvalidTransition(f"A {b.get_status_display().lower()} booking cannot be checked in.")
        today = _local_today(b.property, now)
        if today < b.check_in:
            raise InvalidTransition(f"Check-in opens on {b.check_in:%d %b %Y}.")
        if today >= b.check_out:
            raise InvalidTransition("This stay has already ended. Mark it as a no-show instead.")
        # Housekeeping only warns (decision 7); it never blocks an arrival.
        apply_transition(b, S.CHECKED_IN, actor=actor, details={"housekeeping": b.room.housekeeping_status})
        b.actual_check_in = now
        b.checked_in_by = actor
        b.save(update_fields=["actual_check_in", "checked_in_by", "updated_at"])
        queue_email(K.CHECKED_IN, b)
    return b


# ---------------------------------------------------------------- checkout
def _release_nights(b, new_out, actor, reason):
    """Pro-rata cut of the stay. Returns the paid amount above the new total (to be refunded)."""
    old_nights = (b.check_out - b.check_in).days
    new_nights = (new_out - b.check_in).days
    paid_before = paid_amount(b)
    old_total, previous_out = b.total_amount, b.check_out
    b.total_amount = money(old_total * new_nights / old_nights)
    b.tax_amount = money(b.tax_amount * new_nights / old_nights)
    b.additional_charges = money(b.additional_charges * new_nights / old_nights)
    b.check_out = new_out
    excess = max(ZERO, money(paid_before - b.total_amount))
    if excess > 0:
        b.payment_status = P.PAID
        b.amount_paid = b.total_amount
    b.save(update_fields=["check_out", "total_amount", "tax_amount", "additional_charges",
                          "payment_status", "amount_paid", "updated_at"])
    record(b, H.ADJUSTMENT, actor=actor, reason=reason, details={
        "event": "unused_nights_released", "from": str(previous_out), "to": str(new_out),
        "old_total": str(old_total), "new_total": str(b.total_amount), "refund": str(excess)})
    return excess


def check_out(booking_id, *, actor, override_unpaid=False, release_unused_nights=False,
              reason="", now=None):
    now = now or timezone.now()
    reason = (reason or "").strip()
    with transaction.atomic():
        b = _lock_booking(booking_id)
        _require(actor, b, "receptionist")
        if b.status != S.CHECKED_IN:
            raise InvalidTransition("Only a checked-in booking can be checked out.")
        if override_unpaid or release_unused_nights:
            _require(actor, b, "manager")
            if not reason:
                raise ReasonRequired("A reason is required for a manager adjustment.")

        today = _local_today(b.property, now)
        details = {"unused_nights": max(0, (b.check_out - today).days)}
        refund = ZERO
        if release_unused_nights:
            new_out = max(today, b.check_in + timedelta(days=1))
            if new_out >= b.check_out:
                raise InvalidTransition("There are no unused nights to release.")
            refund = _release_nights(b, new_out, actor, reason)
            details["released_to"] = str(new_out)

        due = outstanding(b)                       # after any release, so the new total counts
        if due > 0:
            if not override_unpaid:
                raise PaymentOutstanding(f"₹{due} is still due. Record the payment before checking out.")
            details["unpaid_override"] = str(due)

        apply_transition(b, S.CHECKED_OUT, actor=actor, reason=reason, details=details)
        b.actual_check_out = now
        b.checked_out_by = actor
        b.save(update_fields=["actual_check_out", "checked_out_by", "updated_at"])
        Room.objects.filter(pk=b.room_id).update(housekeeping_status=Room.HousekeepingStatus.DIRTY)
        if refund > 0:
            RefundTask.objects.create(booking=b, amount=refund, reason=f"Early checkout of {b.reference}")
        queue_email(K.CHECKED_OUT, b)
    return b


# ---------------------------------------------------------------- no-show
def mark_no_show(booking_id, *, actor=None, now=None):
    """actor=None means the system (the scheduled job in Module 11)."""
    now = now or timezone.now()
    with transaction.atomic():
        b = _lock_booking(booking_id)
        if actor is not None:
            _require(actor, b, "receptionist")
        if b.status != S.CONFIRMED:
            raise InvalidTransition("Only a confirmed booking can be marked as a no-show.")
        if _local_today(b.property, now) <= b.check_in:
            raise InvalidTransition("A no-show can only be recorded after the arrival day has ended.")
        outcome = assess(b, now)                   # the deadline has passed, so the fee applies
        apply_transition(b, S.NO_SHOW, actor=actor, details={
            "penalty": str(outcome.penalty), "refund": str(outcome.refund), "paid": outcome.paid})
        if outcome.refund > 0:
            RefundTask.objects.create(booking=b, amount=outcome.refund, reason=f"No-show {b.reference}")
    return outcome


# ---------------------------------------------------------------- extensions
@dataclass(frozen=True)
class ExtensionQuote:
    nights: int
    rate: Decimal
    extra: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def quote_extension(booking, new_check_out):
    """Added nights only, at today's rate and today's tax. Earlier nights keep their snapshot."""
    room = booking.room
    nights = (new_check_out - booking.check_out).days
    extra_guests = max(0, booking.guests - room.base_occupancy)
    extra = money(room.extra_guest_charge * extra_guests * nights)
    subtotal = money(room.price_per_night * nights) + extra
    tax = money(subtotal * booking.property.tax_percent / 100)
    return ExtensionQuote(nights, room.price_per_night, extra, subtotal, tax, subtotal + tax)


def _validate_extension(b, new_check_out):
    if b.status not in (S.CONFIRMED, S.CHECKED_IN):
        raise InvalidTransition("Only confirmed or checked-in stays can be extended.")
    if new_check_out <= b.check_out:
        raise InvalidDates("The new check-out must be after the current check-out.")
    if (new_check_out - b.check_in).days > MAX_STAY_DAYS:
        raise InvalidDates(f"Stays are limited to {MAX_STAY_DAYS} nights.")
    if b.room.monthly_only and not whole_months(b.check_in, new_check_out):
        raise PricingError("This room can only be booked for whole months.")


def _extension_conflict(b, new_check_out, now):
    """Same overlap rule as everywhere, on the added range [current check-out, new check-out)."""
    taken = (Booking.objects.filter(room_id=b.room_id).exclude(pk=b.pk)
             .overlapping(b.check_out, new_check_out).blocking(now).exists())
    blocked = RoomBlock.objects.filter(room_id=b.room_id, start_date__lt=new_check_out,
                                       end_date__gt=b.check_out).exists()
    return taken or blocked


def request_extension(booking_id, *, actor, new_check_out, now=None, notify=True):
    """Records the wish. Does not hold the room and does not change the booking."""
    now = now or timezone.now()
    with transaction.atomic():
        b = _lock_booking(booking_id)
        if not (actor_kinds(actor, b) & {"owner", "receptionist"}):
            raise NotPermitted("You are not allowed to extend this booking.")
        _validate_extension(b, new_check_out)
        if b.extensions.filter(status=E.REQUESTED).exists():
            raise InvalidTransition("There is already a pending extension request for this booking.")
        if _extension_conflict(b, new_check_out, now):          # early feedback only
            raise ExtensionConflict("The room is not available for those dates.")
        ext = ExtensionRequest.objects.create(
            booking=b, original_check_out=b.check_out, requested_check_out=new_check_out,
            requested_by=actor, requested_by_label=actor.email or actor.username)
        record(b, H.EXTENSION, actor=actor, details={
            "event": "requested", "from": str(b.check_out), "to": str(new_check_out)})
        if notify:
            queue_email(K.EXTENSION_REQUESTED, b, key=str(ext.pk),
                        rows=[("Requested check-out", f"{new_check_out:%d %b %Y}")])
    return ext


def approve_extension(ext_id, *, actor, note="", now=None):
    """Re-checks availability under the room lock, re-prices the added nights, updates the booking.
    Request, approval and the booking update are one transaction, so they cannot disagree."""
    now = now or timezone.now()
    note = (note or "").strip()
    with transaction.atomic():
        ext = _lock_extension(ext_id)               # lock order: extension -> booking -> room
        b = _lock_booking(ext.booking_id)
        _require(actor, b, "receptionist")
        if ext.status != E.REQUESTED:
            raise InvalidTransition("This request has already been decided.")
        if b.check_out != ext.original_check_out:
            raise InvalidTransition("The booking changed after this request. Ask for a new extension.")
        _validate_extension(b, ext.requested_check_out)
        room = Room.objects.select_for_update().get(pk=b.room_id)
        b.room = room
        if room.operational_status != Room.OperationalStatus.ACTIVE or \
                _extension_conflict(b, ext.requested_check_out, now):
            raise ExtensionConflict("The room is not available for the requested dates.")

        q = quote_extension(b, ext.requested_check_out)
        old_total, previous_out = b.total_amount, b.check_out
        if b.payment_status == P.PAID:                # what was paid stays; the added nights are due
            b.payment_status = P.PARTIALLY_PAID
            b.amount_paid = old_total
        b.check_out = ext.requested_check_out
        b.total_amount = money(old_total + q.total)
        b.tax_amount = money(b.tax_amount + q.tax)
        b.additional_charges = money(b.additional_charges + q.extra)
        b.save(update_fields=["check_out", "total_amount", "tax_amount", "additional_charges",
                              "payment_status", "amount_paid", "updated_at"])

        ext.status = E.APPROVED
        ext.decided_by, ext.decided_at, ext.decision_note = actor, now, note[:255]
        ext.added_nights, ext.rate_per_night, ext.added_amount = q.nights, q.rate, q.total
        ext.save()
        record(b, H.EXTENSION, actor=actor, reason=note, details={
            "event": "approved", "from": str(previous_out), "to": str(b.check_out),
            "added_nights": q.nights, "rate": str(q.rate), "added_amount": str(q.total),
            "new_total": str(b.total_amount)})
        queue_email(K.EXTENSION_APPROVED, b, key=str(ext.pk), rows=[
            ("Added nights", q.nights), ("Added amount", inr(q.total)),
            ("Balance due", inr(outstanding(b)))])
    return ext


def reject_extension(ext_id, *, actor, note="", now=None):
    now = now or timezone.now()
    note = (note or "").strip()
    with transaction.atomic():
        ext = _lock_extension(ext_id)
        b = _lock_booking(ext.booking_id)
        _require(actor, b, "receptionist")
        if ext.status != E.REQUESTED:
            raise InvalidTransition("This request has already been decided.")
        ext.status = E.REJECTED
        ext.decided_by, ext.decided_at, ext.decision_note = actor, now, note[:255]
        ext.save()
        record(b, H.EXTENSION, actor=actor, reason=note, details={
            "event": "rejected", "requested": str(ext.requested_check_out)})
        queue_email(K.EXTENSION_REJECTED, b, key=str(ext.pk), note=note)
    return ext


def extend_now(booking_id, *, actor, new_check_out, note="", now=None):
    """Staff shortcut: request + approve in one transaction. A guest calling this is refused
    at the approval step, which rolls the request back too. No 'request received' email is sent,
    only the approval."""
    with transaction.atomic():
        ext = request_extension(booking_id, actor=actor, new_check_out=new_check_out,
                                now=now, notify=False)
        return approve_extension(ext.pk, actor=actor, note=note or "Extended by staff", now=now)