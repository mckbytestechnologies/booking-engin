import hashlib
import hmac
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rooms.models import Room

from ..models import Booking, BookingHistory, Payment, RoomBlock
from . import razorpay_client
from .errors import (AlreadyPaid, HoldExpired, PaymentAmountMismatch, PaymentNotConfigured,
                     PaymentNotFound, PaymentSignatureInvalid, UnknownGroup)
from .history import record
from .notifications import notify_group_confirmed

logger = logging.getLogger(__name__)


def _paise(amount):
    return int(Decimal(amount) * 100)


def _hmac(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_checkout_signature(order_id, payment_id, signature):
    if not settings.RAZORPAY_KEY_SECRET:
        raise PaymentNotConfigured("Payments are not configured.")
    expected = _hmac(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode())
    if not hmac.compare_digest(expected, signature or ""):
        raise PaymentSignatureInvalid("Payment could not be verified.")


def verify_webhook_signature(raw_body, signature):
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        return False                                  # no secret configured: accept nothing
    return hmac.compare_digest(_hmac(secret, raw_body), signature or "")


def create_order(group_ref, now=None):
    """Create (or reuse) the Razorpay order for a held group. Amount is computed here."""
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise PaymentNotConfigured("Payments are not configured.")
    now = now or timezone.now()

    with transaction.atomic():
        bookings = list(Booking.objects.select_for_update().filter(group_ref=group_ref).order_by("id"))
        if not bookings:
            raise UnknownGroup("Unknown booking.")
        if all(b.status == Booking.Status.CONFIRMED for b in bookings):
            raise AlreadyPaid("This booking is already paid.")
        if any(b.status != Booking.Status.PENDING or b.expires_at is None or b.expires_at <= now
               for b in bookings):
            raise HoldExpired("Your hold has expired. Please search again.")

        amount = _paise(sum(b.total_amount for b in bookings))
        payment = Payment.objects.filter(
            group_ref=group_ref, status=Payment.Status.CREATED, amount=amount).first()
        if payment is None:                           # reuse on double-click / retry
            order = razorpay_client.create_order(amount, "INR", receipt=group_ref,
                                                 notes={"group_ref": group_ref})
            payment = Payment.objects.create(group_ref=group_ref, razorpay_order_id=order["id"], amount=amount)
    return payment


def _rooms_still_free(bookings, now):
    for b in bookings:
        taken = (Booking.objects.filter(room_id=b.room_id).overlapping(b.check_in, b.check_out)
                 .blocking(now).exclude(group_ref=b.group_ref).exists())
        blocked = RoomBlock.objects.filter(room_id=b.room_id, start_date__lt=b.check_out,
                                           end_date__gt=b.check_in).exists()
        if taken or blocked:
            return False
    return True


def confirm_payment(order_id, payment_id, amount=None, now=None):
    """Idempotent. Safe to call from the checkout callback AND the webhook."""
    now = now or timezone.now()
    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(razorpay_order_id=order_id)
        except Payment.DoesNotExist:
            raise PaymentNotFound("Unknown payment order.")
        if payment.status in (Payment.Status.PAID, Payment.Status.REFUND_REQUIRED):
            return payment                            # already settled
        if amount is not None and amount != payment.amount:
            logger.error("Payment amount mismatch for order %s", order_id)
            raise PaymentAmountMismatch("Payment amount does not match the order.")

        bookings = list(Booking.objects.select_for_update().filter(group_ref=payment.group_ref).order_by("id"))
        list(Room.objects.select_for_update().filter(pk__in=sorted({b.room_id for b in bookings})).order_by("id"))
        payment.razorpay_payment_id = payment_id

        already_confirmed = bool(bookings) and all(b.status == Booking.Status.CONFIRMED for b in bookings)
        hold_valid = bool(bookings) and all(
            b.status == Booking.Status.PENDING and b.expires_at and b.expires_at > now for b in bookings)
        revivable = bool(bookings) and all(
            b.status in (Booking.Status.PENDING, Booking.Status.EXPIRED) for b in bookings)

        if not already_confirmed and (hold_valid or (revivable and _rooms_still_free(bookings, now))):
            for b in bookings:
                previous = b.status
                b.status = Booking.Status.CONFIRMED
                b.payment_status = Booking.PaymentStatus.PAID
                b.expires_at = None
                b.save(update_fields=["status", "payment_status", "expires_at", "updated_at"])
                record(b, BookingHistory.Action.STATUS_CHANGE, from_status=previous,
                       to_status=Booking.Status.CONFIRMED, reason="Online payment confirmed",
                       details={"payment_id": payment_id})
            payment.status = Payment.Status.PAID
            payment.paid_at = now
            # Queued inside this transaction, sent after it commits. Duplicates are blocked
            # by the outbox dedupe key, so verify + webhook cannot send two emails.
            notify_group_confirmed(payment.group_ref)
        else:
            logger.error("Payment %s needs a refund (group %s)", payment_id, payment.group_ref)
            payment.status = Payment.Status.REFUND_REQUIRED
            for b in bookings:
                if b.status == Booking.Status.PENDING:
                    b.status = Booking.Status.EXPIRED
                    b.save(update_fields=["status", "updated_at"])
        payment.save()
    return payment


def mark_failed(order_id):
    Payment.objects.filter(razorpay_order_id=order_id, status=Payment.Status.CREATED) \
        .update(status=Payment.Status.FAILED)