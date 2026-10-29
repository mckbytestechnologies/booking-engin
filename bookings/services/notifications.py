# import logging
# from datetime import timedelta

# from django.conf import settings
# from django.core.mail import EmailMultiAlternatives
# from django.db import IntegrityError, transaction
# from django.db.models import F
# from django.template.loader import render_to_string
# from django.utils import timezone

# from ..models import Booking, EmailNotification

# log = logging.getLogger(__name__)

# N = EmailNotification
# K = EmailNotification.Kind
# MAX_ATTEMPTS = 5
# STUCK_AFTER = timedelta(minutes=10)

# # kind -> (subject, heading, lead sentence)
# COPY = {
#     K.BOOKING_CONFIRMED: ("Booking confirmed: {ref}", "Your booking is confirmed",
#                           "Thank you for booking with us. Your stay details are below."),
#     K.BOOKING_CANCELLED: ("Booking cancelled: {ref}", "Your booking was cancelled",
#                           "We have cancelled this booking. Any refund due is shown below."),
#     K.CHECKED_IN: ("Welcome: {ref}", "You are checked in",
#                    "Welcome. We hope you enjoy your stay."),
#     K.CHECKED_OUT: ("Thank you for staying: {ref}", "You are checked out",
#                     "Thank you for staying with us. We hope to see you again."),
#     K.EXTENSION_REQUESTED: ("Extension request received: {ref}", "We received your extension request",
#                             "The hotel will confirm it soon. Your booking does not change until then."),
#     K.EXTENSION_APPROVED: ("Extension approved: {ref}", "Your stay is extended",
#                            "Your extension was approved. The added nights are due at the front desk."),
#     K.EXTENSION_REJECTED: ("Extension not available: {ref}", "We could not extend your stay",
#                            "Your original booking is unchanged."),
# }


# def inr(value):
#     return f"INR {value:,.2f}"


# def _rows(b):
#     nights = (b.check_out - b.check_in).days
#     return [
#         ("Reference", b.reference),
#         ("Property", b.property.name),
#         ("Room", b.room.number),
#         ("Check-in", f"{b.check_in:%d %b %Y}"),
#         ("Check-out", f"{b.check_out:%d %b %Y}"),
#         ("Nights", nights),
#         ("Guests", b.guests),
#         ("Total", inr(b.total_amount)),
#     ]


# def queue_email(kind, booking, *, key="", rows=None, note=""):
#     """Writes the outbox row in the caller's transaction and sends after commit.
#     Never raises: a failure here is logged and must not break the booking."""
#     if not booking.customer_email:
#         return None
#     subject, heading, lead = COPY[kind]
#     ctx = {
#         "site_name": settings.SITE_NAME, "heading": heading, "lead": lead,
#         "name": booking.customer_name, "rows": _rows(booking) + list(rows or []), "note": note,
#     }
#     dedupe = f"{kind}:{booking.reference}" + (f":{key}" if key else "")
#     try:
#         text = render_to_string("emails/booking_event.txt", ctx)
#         html = render_to_string("emails/booking_event.html", ctx)
#         with transaction.atomic():                       # savepoint: a duplicate cannot poison the caller
#             mail = N.objects.create(
#                 booking=booking, kind=kind, to_email=booking.customer_email,
#                 subject=subject.format(ref=booking.reference),
#                 body_text=text, body_html=html, dedupe_key=dedupe)
#     except IntegrityError:
#         return None                                      # already queued: this is the dedupe working
#     except Exception:
#         log.exception("Could not queue %s for %s", kind, booking.reference)
#         return None
#     transaction.on_commit(lambda: deliver(mail.pk), robust=True)
#     return mail


# def deliver(pk):
#     """Sends one row. Returns True if sent. Never raises on a send failure."""
#     claimed = (N.objects.filter(pk=pk, status__in=[N.Status.PENDING, N.Status.FAILED],
#                                 attempts__lt=MAX_ATTEMPTS)
#                .update(status=N.Status.SENDING, attempts=F("attempts") + 1))
#     if not claimed:                                      # someone else has it, or it is done
#         return False
#     mail = N.objects.get(pk=pk)
#     try:
#         msg = EmailMultiAlternatives(mail.subject, mail.body_text, settings.DEFAULT_FROM_EMAIL,
#                                      [mail.to_email])
#         msg.attach_alternative(mail.body_html, "text/html")
#         msg.send()
#     except Exception as exc:
#         N.objects.filter(pk=pk).update(status=N.Status.FAILED, last_error=str(exc)[:500])
#         log.warning("Email %s failed (attempt %s): %s", pk, mail.attempts, exc)
#         return False
#     N.objects.filter(pk=pk).update(status=N.Status.SENT, sent_at=timezone.now(), last_error="")
#     return True


# def retry_pending(limit=100):
#     """For the command / scheduler. Also frees rows stuck in SENDING after a crash."""
#     N.objects.filter(status=N.Status.SENDING, updated_at__lt=timezone.now() - STUCK_AFTER) \
#         .update(status=N.Status.FAILED)
#     ids = list(N.objects.filter(status__in=[N.Status.PENDING, N.Status.FAILED],
#                                 attempts__lt=MAX_ATTEMPTS)
#                .order_by("created_at").values_list("pk", flat=True)[:limit])
#     return sum(1 for pk in ids if deliver(pk))


# def notify_group_confirmed(group_ref):
#     """Call once a payment confirms a group. Safe to call twice (dedupe)."""
#     for b in Booking.objects.filter(group_ref=group_ref, status=Booking.Status.CONFIRMED) \
#             .select_related("property", "room"):
#         queue_email(K.BOOKING_CONFIRMED, b)

import hashlib
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from properties.models import StaffAssignment

from ..models import Booking, EmailNotification

log = logging.getLogger(__name__)

N = EmailNotification
K = EmailNotification.Kind
MAX_ATTEMPTS = 5
STUCK_AFTER = timedelta(minutes=10)

# kind -> (subject, heading, lead sentence)
COPY = {
    K.BOOKING_CONFIRMED: ("Booking confirmed: {ref}", "Your booking is confirmed",
                          "Thank you for booking with us. Your stay details are below."),
    K.BOOKING_CANCELLED: ("Booking cancelled: {ref}", "Your booking was cancelled",
                          "We have cancelled this booking. Any refund due is shown below."),
    K.CHECKED_IN: ("Welcome: {ref}", "You are checked in",
                   "Welcome. We hope you enjoy your stay."),
    K.CHECKED_OUT: ("Thank you for staying: {ref}", "You are checked out",
                    "Thank you for staying with us. We hope to see you again."),
    K.EXTENSION_REQUESTED: ("Extension request received: {ref}", "We received your extension request",
                            "The hotel will confirm it soon. Your booking does not change until then."),
    K.EXTENSION_APPROVED: ("Extension approved: {ref}", "Your stay is extended",
                           "Your extension was approved. The added nights are due at the front desk."),
    K.EXTENSION_REJECTED: ("Extension not available: {ref}", "We could not extend your stay",
                           "Your original booking is unchanged."),
}


def inr(value):
    return f"INR {value:,.2f}"


def _rows(b):
    nights = (b.check_out - b.check_in).days
    return [
        ("Reference", b.reference),
        ("Property", b.property.name),
        ("Room", b.room.number),
        ("Check-in", f"{b.check_in:%d %b %Y}"),
        ("Check-out", f"{b.check_out:%d %b %Y}"),
        ("Nights", nights),
        ("Guests", b.guests),
        ("Total", inr(b.total_amount)),
    ]


def queue_email(kind, booking, *, key="", rows=None, note=""):
    """Writes the outbox row in the caller's transaction and sends after commit.
    Never raises: a failure here is logged and must not break the booking."""
    if not booking.customer_email:
        return None
    subject, heading, lead = COPY[kind]
    ctx = {
        "site_name": settings.SITE_NAME, "heading": heading, "lead": lead,
        "name": booking.customer_name, "rows": _rows(booking) + list(rows or []), "note": note,
    }
    dedupe = f"{kind}:{booking.reference}" + (f":{key}" if key else "")
    try:
        text = render_to_string("emails/booking_event.txt", ctx)
        html = render_to_string("emails/booking_event.html", ctx)
        with transaction.atomic():                       # savepoint: a duplicate cannot poison the caller
            mail = N.objects.create(
                booking=booking, kind=kind, to_email=booking.customer_email,
                subject=subject.format(ref=booking.reference),
                body_text=text, body_html=html, dedupe_key=dedupe)
    except IntegrityError:
        return None                                      # already queued: this is the dedupe working
    except Exception:
        log.exception("Could not queue %s for %s", kind, booking.reference)
        return None
    transaction.on_commit(lambda: deliver(mail.pk), robust=True)
    return mail


def deliver(pk):
    """Sends one row. Returns True if sent. Never raises on a send failure."""
    claimed = (N.objects.filter(pk=pk, status__in=[N.Status.PENDING, N.Status.FAILED],
                                attempts__lt=MAX_ATTEMPTS)
               .update(status=N.Status.SENDING, attempts=F("attempts") + 1))
    if not claimed:                                      # someone else has it, or it is done
        return False
    mail = N.objects.get(pk=pk)
    try:
        msg = EmailMultiAlternatives(mail.subject, mail.body_text, settings.DEFAULT_FROM_EMAIL,
                                     [mail.to_email])
        msg.attach_alternative(mail.body_html, "text/html")
        msg.send()
    except Exception as exc:
        N.objects.filter(pk=pk).update(status=N.Status.FAILED, last_error=str(exc)[:500])
        log.warning("Email %s failed (attempt %s): %s", pk, mail.attempts, exc)
        return False
    N.objects.filter(pk=pk).update(status=N.Status.SENT, sent_at=timezone.now(), last_error="")
    return True


def retry_pending(limit=100):
    """For the command / scheduler. Also frees rows stuck in SENDING after a crash."""
    N.objects.filter(status=N.Status.SENDING, updated_at__lt=timezone.now() - STUCK_AFTER) \
        .update(status=N.Status.FAILED)
    ids = list(N.objects.filter(status__in=[N.Status.PENDING, N.Status.FAILED],
                                attempts__lt=MAX_ATTEMPTS)
               .order_by("created_at").values_list("pk", flat=True)[:limit])
    return sum(1 for pk in ids if deliver(pk))


# ================================================================== admin / staff notifications
def admin_recipients(prop, exclude=()):
    """Who hears about a new booking: the property's managers, the property's own email
    address, and any extra addresses in settings.BOOKING_NOTIFY_EMAILS. Lower-cased, no duplicates."""
    emails = set(
        StaffAssignment.objects
        .filter(property=prop, role=StaffAssignment.Role.MANAGER, user__is_active=True)
        .exclude(user__email="").values_list("user__email", flat=True))
    emails.update(getattr(settings, "BOOKING_NOTIFY_EMAILS", None) or [])
    if getattr(settings, "BOOKING_NOTIFY_PROPERTY_EMAIL", True) and prop.email:
        emails.add(prop.email)
    skip = {e.strip().lower() for e in exclude if e}
    return sorted({e.strip().lower() for e in emails if e and e.strip()} - skip)


def _staff_link(booking):
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    try:
        return base + reverse("staff_booking_detail", args=[booking.reference])
    except NoReverseMatch:
        return ""


def notify_admins_group(group_ref, *, exclude=()):
    """One email per recipient for a whole confirmed group (a 3-room booking is ONE email).
    Queued in the caller's transaction, sent after commit. Safe to call twice: the outbox
    dedupe key blocks repeats. Never raises. Returns how many emails were queued."""
    bookings = list(Booking.objects.filter(group_ref=group_ref, status=Booking.Status.CONFIRMED)
                    .select_related("property", "room").order_by("id"))
    if not bookings:
        return 0
    first = bookings[0]
    prop = first.property
    recipients = admin_recipients(prop, exclude)
    if not recipients:
        return 0

    total = sum((b.total_amount for b in bookings), Decimal("0"))
    rows = [
        ("Reference", ", ".join(b.reference for b in bookings)),
        ("Property", prop.name),
        ("Rooms", ", ".join(b.room.number for b in bookings)),
        ("Check-in", f"{first.check_in:%d %b %Y}"),
        ("Check-out", f"{first.check_out:%d %b %Y}"),
        ("Nights", (first.check_out - first.check_in).days),
        ("Guests", sum(b.guests for b in bookings)),
        ("Total", inr(total)),
        ("Guest", first.customer_name),
        ("Guest email", first.customer_email),
        ("Guest phone", first.customer_phone),
        ("Source", first.get_source_display()),
        ("Payment", first.get_payment_status_display()),
    ]
    if first.special_requests:
        rows.append(("Guest request", first.special_requests))

    ctx = {
        "site_name": settings.SITE_NAME, "heading": "New booking confirmed",
        "lead": f"A booking was just confirmed at {prop.name}. The details are below.",
        "name": "team", "rows": rows, "note": "",
        "action_url": _staff_link(first), "action_label": "Open booking",
    }
    subject = (f"New booking {first.reference}: {prop.name}, "
               f"{first.check_in:%d %b} to {first.check_out:%d %b %Y}")[:200]
    try:
        text = render_to_string("emails/booking_event.txt", ctx)
        html = render_to_string("emails/booking_event.html", ctx)
    except Exception:
        log.exception("Could not render the admin email for group %s", group_ref)
        return 0

    queued = 0
    for to in recipients:
        key = f"{K.ADMIN_NEW_BOOKING}:{group_ref}:{hashlib.sha1(to.encode()).hexdigest()[:12]}"
        try:
            with transaction.atomic():
                mail = N.objects.create(booking=first, kind=K.ADMIN_NEW_BOOKING, to_email=to,
                                        subject=subject, body_text=text, body_html=html,
                                        dedupe_key=key)
        except IntegrityError:
            continue                                     # already queued for this person
        except Exception:
            log.exception("Could not queue the admin email for group %s", group_ref)
            continue
        transaction.on_commit(lambda pk=mail.pk: deliver(pk), robust=True)
        queued += 1
    return queued


def notify_group_confirmed(group_ref):
    """Call once a payment confirms a group. Safe to call twice (dedupe)."""
    for b in Booking.objects.filter(group_ref=group_ref, status=Booking.Status.CONFIRMED) \
            .select_related("property", "room"):
        queue_email(K.BOOKING_CONFIRMED, b)
    notify_admins_group(group_ref)