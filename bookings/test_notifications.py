from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.db import transaction

from .models import Booking, EmailNotification
from .services.lifecycle import cancel_booking
from .services.notifications import MAX_ATTEMPTS, deliver, queue_email, retry_pending
from .services.stay import (approve_extension, check_in, check_out, extend_now,
                            request_extension)
from .test_lifecycle import LifecycleBase
from .tests import make_booking

DAY = timedelta(days=1)
N = EmailNotification
K = EmailNotification.Kind


class OutboxBase(LifecycleBase):
    def booking(self, ci, co, **kw):
        b = make_booking(self.room, self.today + ci * DAY, self.today + co * DAY, **kw)
        Booking.objects.filter(pk=b.pk).update(customer_email="asha@example.com", customer_name="Asha")
        b.refresh_from_db()
        return b


class OutboxTests(OutboxBase):
    def test_email_is_sent_after_commit(self):
        b = self.booking(5, 8)
        with self.captureOnCommitCallbacks(execute=True):
            queue_email(K.BOOKING_CONFIRMED, b)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn(b.reference, msg.subject)
        self.assertEqual(msg.to, ["asha@example.com"])
        self.assertEqual(msg.alternatives[0][1], "text/html")
        self.assertEqual(N.objects.get().status, "SENT")

    def test_nothing_is_sent_before_commit(self):
        queue_email(K.BOOKING_CONFIRMED, self.booking(5, 8))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(N.objects.get().status, "PENDING")

    def test_duplicate_is_ignored(self):
        b = self.booking(5, 8)
        queue_email(K.BOOKING_CONFIRMED, b)
        self.assertIsNone(queue_email(K.BOOKING_CONFIRMED, b))
        self.assertEqual(N.objects.count(), 1)

    def test_no_address_means_no_email(self):
        b = self.booking(5, 8)
        Booking.objects.filter(pk=b.pk).update(customer_email="")
        b.refresh_from_db()
        self.assertIsNone(queue_email(K.BOOKING_CONFIRMED, b))
        self.assertEqual(N.objects.count(), 0)

    def test_rolled_back_transaction_leaves_no_email(self):
        b = self.booking(5, 8)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    queue_email(K.BOOKING_CONFIRMED, b)
                    raise RuntimeError("booking failed")
        self.assertEqual((N.objects.count(), len(callbacks), len(mail.outbox)), (0, 0, 0))

    def test_failed_send_is_kept_and_retried(self):
        queue_email(K.BOOKING_CONFIRMED, self.booking(5, 8))
        pk = N.objects.get().pk
        with mock.patch("bookings.services.notifications.EmailMultiAlternatives.send",
                        side_effect=OSError("smtp down")):
            self.assertFalse(deliver(pk))
        row = N.objects.get()
        self.assertEqual((row.status, row.attempts), ("FAILED", 1))
        self.assertIn("smtp down", row.last_error)
        self.assertEqual(retry_pending(), 1)
        self.assertEqual(N.objects.get().status, "SENT")

    def test_gives_up_after_max_attempts(self):
        queue_email(K.BOOKING_CONFIRMED, self.booking(5, 8))
        N.objects.update(status="FAILED", attempts=MAX_ATTEMPTS)
        self.assertEqual(retry_pending(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_command_sends_pending_rows(self):
        queue_email(K.BOOKING_CONFIRMED, self.booking(5, 8))
        call_command("send_pending_emails")
        self.assertEqual(len(mail.outbox), 1)


class EventEmailTests(OutboxBase):
    def kinds(self):
        return sorted(N.objects.values_list("kind", flat=True))

    def test_cancelling_a_confirmed_booking_sends_one_email_with_the_refund(self):
        b = self.booking(5, 8, customer=self.guest, payment_status="PAID")
        cancel_booking(b.pk, actor=self.guest)
        row = N.objects.get(kind=K.BOOKING_CANCELLED)
        self.assertIn("Refund due: INR 7,500.00", row.body_text)

    def test_cancelling_an_unpaid_hold_sends_nothing(self):
        b = self.booking(5, 8, customer=self.guest, status="PENDING")
        cancel_booking(b.pk, actor=self.guest)
        self.assertEqual(N.objects.count(), 0)

    def test_check_in_email(self):
        b = self.booking(0, 2)
        check_in(b.pk, actor=self.rec)
        self.assertEqual(self.kinds(), [K.CHECKED_IN])

    def test_check_out_email(self):
        b = self.booking(-1, 2, status="CHECKED_IN", payment_status="PAID")
        check_out(b.pk, actor=self.rec)
        self.assertEqual(self.kinds(), [K.CHECKED_OUT])

    def test_extension_request_email(self):
        b = self.booking(5, 8, customer=self.guest, payment_status="PAID")
        request_extension(b.pk, actor=self.guest, new_check_out=self.today + 10 * DAY)
        self.assertEqual(self.kinds(), [K.EXTENSION_REQUESTED])

    def test_extension_approval_email_shows_the_balance(self):
        b = self.booking(5, 8, customer=self.guest, payment_status="PAID")
        ext = request_extension(b.pk, actor=self.guest, new_check_out=self.today + 10 * DAY)
        approve_extension(ext.pk, actor=self.rec)
        self.assertEqual(self.kinds(), [K.EXTENSION_APPROVED, K.EXTENSION_REQUESTED])
        self.assertIn("Balance due: INR 5,000.00", N.objects.get(kind=K.EXTENSION_APPROVED).body_text)

    def test_staff_extension_sends_only_the_approval(self):
        b = self.booking(5, 8, customer=self.guest, payment_status="PAID")
        extend_now(b.pk, actor=self.rec, new_check_out=self.today + 10 * DAY)
        self.assertEqual(self.kinds(), [K.EXTENSION_APPROVED])