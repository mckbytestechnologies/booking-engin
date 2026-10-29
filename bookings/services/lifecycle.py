from dataclasses import replace

from django.db import transaction
from django.utils import timezone

from accounts.access import Role, has_role_at

from ..models import Booking, BookingHistory, ExtensionRequest, RefundTask
from .balance import outstanding, paid_amount
from .booking import create_hold
from .cancellation import ZERO, assess
from .errors import InvalidSelection, InvalidTransition, NotPermitted, ReasonRequired, UnknownBooking
from .history import record
from .selection import parse_key
from .transitions import actor_kinds, apply_transition
from ..models import EmailNotification            # merge into the existing models import
from .notifications import inr, queue_email

S = Booking.Status


def _lock(booking_id):
    try:
        return Booking.objects.select_for_update().get(pk=booking_id)
    except Booking.DoesNotExist:
        raise UnknownBooking("Unknown booking.")


def create_manual_booking(*, actor, property, selections, check_in, check_out, guest, source, now=None):
    """Staff booking (phone / walk-in). Same creation path as online, but confirmed and unpaid."""
    if source not in (Booking.Source.ADMIN_MANUAL, Booking.Source.WALK_IN):
        raise InvalidSelection("Manual bookings must be ADMIN_MANUAL or WALK_IN.")
    if not has_role_at(actor, property.id, Role.RECEPTIONIST):
        raise NotPermitted("You cannot book for this property.")
    for sel in selections:
        if parse_key(sel.key)["property_id"] != property.id:
            raise InvalidSelection("That room does not belong to this property.")
    with transaction.atomic():
        result = create_hold(
            selections=selections, check_in=check_in, check_out=check_out, guest=guest,
            source=source, created_by=actor, now=now,
            today=property.local_today(),            # the property's "today", not the server's
            confirmed=True,
        )
        for b in result["bookings"]:
            queue_email(EmailNotification.Kind.BOOKING_CONFIRMED, b)
    return result


def cancel_booking(booking_id, *, actor, reason="", waive_penalty=False, now=None):
    now = now or timezone.now()
    reason = (reason or "").strip()
    with transaction.atomic():
        booking = _lock(booking_id)
        if waive_penalty:
            if "manager" not in actor_kinds(actor, booking):
                raise NotPermitted("Only a manager can waive the cancellation fee.")
            if not reason:
                raise ReasonRequired("A reason is required to waive the fee.")

        outcome = assess(booking, now)
        if waive_penalty:
            outcome = replace(outcome, penalty=ZERO, waived=True, refund=paid_amount(booking))

        was_hold = booking.status == S.PENDING          # an unpaid hold sends no email

        apply_transition(booking, S.CANCELLED, actor=actor, reason=reason, details={
            "free": outcome.free, "waived": outcome.waived,
            "penalty": str(outcome.penalty), "refund": str(outcome.refund),
        })
        booking.extensions.filter(status=ExtensionRequest.Status.REQUESTED) \
            .update(status=ExtensionRequest.Status.CANCELLED)
        if outcome.refund > 0:
            RefundTask.objects.create(booking=booking, amount=outcome.refund,
                                      reason=f"Cancellation of {booking.reference}")

        if not was_hold:
            queue_email(EmailNotification.Kind.BOOKING_CANCELLED, booking, rows=[
                ("Cancellation fee", inr(outcome.penalty)),
                ("Refund due", inr(outcome.refund)),
            ])
    return outcome
    

def record_payment(booking_id, *, actor, method, note=""):
    """Desk payment: the whole outstanding balance (cash / card / UPI)."""
    P = Booking.PaymentStatus
    with transaction.atomic():
        booking = _lock(booking_id)
        if "receptionist" not in actor_kinds(actor, booking):
            raise NotPermitted("You are not allowed to record payments here.")
        if booking.status not in (S.CONFIRMED, S.CHECKED_IN):
            raise InvalidTransition("Payment can only be recorded for confirmed or checked-in bookings.")
        if booking.payment_status == P.PAID:
            raise InvalidTransition("Payment is already recorded.")
        if booking.payment_status == P.UNPAID and booking.source == Booking.Source.ONLINE:
            raise InvalidTransition("Online bookings are paid through Razorpay.")
        due = outstanding(booking)
        booking.payment_status = P.PAID
        booking.amount_paid = booking.total_amount
        booking.save(update_fields=["payment_status", "amount_paid", "updated_at"])
        record(booking, BookingHistory.Action.PAYMENT, actor=actor, reason=note,
               details={"method": method, "amount": str(due)})
    return booking


def complete_refund(task_id, *, actor, now=None):
    """Manager confirms the money was returned (done by hand in the Razorpay dashboard)."""
    now = now or timezone.now()
    with transaction.atomic():
        try:
            task = RefundTask.objects.select_for_update().get(pk=task_id)
        except RefundTask.DoesNotExist:
            raise UnknownBooking("Unknown refund task.")
        booking = _lock(task.booking_id)
        if "manager" not in actor_kinds(actor, booking):
            raise NotPermitted("Only a manager can complete refunds.")
        if task.status != RefundTask.Status.PENDING:
            raise InvalidTransition("This refund is already completed.")
        task.status = RefundTask.Status.DONE
        task.completed_by = actor
        task.completed_at = now
        task.save()
        if booking.status == S.CANCELLED:        # a partial refund on a live stay is not "REFUNDED"
            booking.payment_status = Booking.PaymentStatus.REFUNDED
            booking.save(update_fields=["payment_status", "updated_at"])
        record(booking, BookingHistory.Action.REFUND, actor=actor, details={"amount": str(task.amount)})
    return task

def create_manual_booking(*, actor, property, selections, check_in, check_out, guest, source, now=None):
    """Staff booking (phone / walk-in). Same creation path as online, but confirmed and unpaid."""
    if source not in (Booking.Source.ADMIN_MANUAL, Booking.Source.WALK_IN):
        raise InvalidSelection("Manual bookings must be ADMIN_MANUAL or WALK_IN.")
    if not has_role_at(actor, property.id, Role.RECEPTIONIST):
        raise NotPermitted("You cannot book for this property.")
    for sel in selections:
        if parse_key(sel.key)["property_id"] != property.id:
            raise InvalidSelection("That room does not belong to this property.")
    with transaction.atomic():
        result = create_hold(
            selections=selections, check_in=check_in, check_out=check_out, guest=guest,
            source=source, created_by=actor, now=now,
            today=property.local_today(),            # the property's "today", not the server's
            confirmed=True,
        )
        for b in result["bookings"]:
            queue_email(EmailNotification.Kind.BOOKING_CONFIRMED, b)
    return result