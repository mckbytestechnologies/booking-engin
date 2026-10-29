from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from properties.models import StaffAssignment
from properties.tests import make_property

from .models import Booking, BookingHistory, RefundTask
from .services.availability import free_room_ids
from .services.booking import Selection
from .services.errors import (InvalidDates, InvalidSelection, InvalidTransition, NotPermitted,
                              ReasonRequired, RoomUnavailable)
from .services.lifecycle import cancel_booking, complete_refund, create_manual_booking, record_payment
from .test_services import GUEST, key_for
from .tests import make_booking, make_room

User = get_user_model()
PW = "Tr1cky-Horse-Battery"


def make_user(email):
    return User.objects.create_user(username=email, email=email, password=PW)


def assign(user, prop, role):
    return StaffAssignment.objects.create(user=user, property=prop, role=role)


class LifecycleBase(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.room = make_room(self.prop, "101")
        self.today = self.prop.local_today()
        self.rec = make_user("rec@example.com")
        assign(self.rec, self.prop, "RECEPTIONIST")
        self.mgr = make_user("mgr@example.com")
        assign(self.mgr, self.prop, "MANAGER")
        self.guest = make_user("guest@example.com")

    def far(self):                       # well before the free-cancellation deadline
        ci = self.today + timedelta(days=10)
        return ci, ci + timedelta(days=3)

    def late(self):                      # deadline (yesterday 14:00 local) has certainly passed
        return self.today, self.today + timedelta(days=3)


class CancelTests(LifecycleBase):
    def test_free_cancellation_refunds_everything(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co, customer=self.guest, payment_status="PAID")
        outcome = cancel_booking(b.pk, actor=self.guest)
        b.refresh_from_db()
        self.assertEqual(b.status, "CANCELLED")
        self.assertTrue(outcome.free)
        self.assertEqual((outcome.penalty, outcome.refund), (Decimal("0.00"), Decimal("7500.00")))
        self.assertEqual(RefundTask.objects.get().amount, Decimal("7500.00"))
        h = b.history.get()
        self.assertEqual((h.from_status, h.to_status, h.actor), ("CONFIRMED", "CANCELLED", self.guest))

    def test_late_cancellation_keeps_the_first_night(self):
        ci, co = self.late()
        b = make_booking(self.room, ci, co, customer=self.guest, payment_status="PAID")
        outcome = cancel_booking(b.pk, actor=self.guest)
        self.assertFalse(outcome.free)
        self.assertEqual((outcome.penalty, outcome.refund), (Decimal("2500.00"), Decimal("5000.00")))
        self.assertEqual(RefundTask.objects.get().amount, Decimal("5000.00"))

    def test_pending_hold_cancels_free_and_creates_no_refund(self):
        ci, co = self.late()
        b = make_booking(self.room, ci, co, customer=self.guest, status="PENDING",
                         expires_at=timezone.now() + timedelta(minutes=30))
        outcome = cancel_booking(b.pk, actor=self.guest)
        self.assertTrue(outcome.free)
        self.assertEqual(RefundTask.objects.count(), 0)

    def test_waiver_needs_manager_and_reason(self):
        ci, co = self.late()
        b = make_booking(self.room, ci, co, customer=self.guest, payment_status="PAID")
        with self.assertRaises(NotPermitted):
            cancel_booking(b.pk, actor=self.rec, waive_penalty=True, reason="goodwill")
        with self.assertRaises(ReasonRequired):
            cancel_booking(b.pk, actor=self.mgr, waive_penalty=True)
        b.refresh_from_db()
        self.assertEqual(b.status, "CONFIRMED")                       # failed attempts changed nothing
        outcome = cancel_booking(b.pk, actor=self.mgr, waive_penalty=True, reason="Guest ill")
        self.assertEqual((outcome.penalty, outcome.refund), (Decimal("0.00"), Decimal("7500.00")))
        self.assertTrue(outcome.waived)

    def test_terminal_and_checked_in_bookings_cannot_be_cancelled(self):
        ci, co = self.far()
        for i, status in enumerate(("CHECKED_IN", "CHECKED_OUT", "CANCELLED", "NO_SHOW")):
            with self.subTest(status):
                off = timedelta(days=5 * i)
                b = make_booking(self.room, ci + off, co + off, status=status)
                with self.assertRaises(InvalidTransition):
                    cancel_booking(b.pk, actor=self.rec)

    def test_owner_can_cancel_but_strangers_cannot(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co, customer=self.guest)
        with self.assertRaises(NotPermitted):
            cancel_booking(b.pk, actor=make_user("x@example.com"))
        cancel_booking(b.pk, actor=self.guest)
        b.refresh_from_db()
        self.assertEqual(b.status, "CANCELLED")

    def test_cancelled_room_is_bookable_again(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co)
        self.assertNotIn(self.room.id, free_room_ids(ci, co))
        cancel_booking(b.pk, actor=self.rec)
        self.assertIn(self.room.id, free_room_ids(ci, co))


class ManualBookingTests(LifecycleBase):
    def manual(self, actor=None, prop=None, key=None, ci=None, source="WALK_IN"):
        ci = ci or self.today + timedelta(days=3)
        return create_manual_booking(
            actor=actor or self.rec, property=prop or self.prop,
            selections=[Selection(key or key_for(self.room), 1)],
            check_in=ci, check_out=ci + timedelta(days=2),
            guest={**GUEST, "internal_notes": "Paid cash"}, source=source)

    def test_creates_confirmed_unpaid_booking_with_history(self):
        b = self.manual()["bookings"][0]
        self.assertEqual((b.status, b.payment_status, b.source, b.created_by, b.expires_at),
                         ("CONFIRMED", "UNPAID", "WALK_IN", self.rec, None))
        self.assertEqual(b.internal_notes, "Paid cash")
        h = b.history.get()
        self.assertEqual((h.action, h.to_status, h.actor_label), ("CREATED", "CONFIRMED", "rec@example.com"))

    def test_staff_of_another_property_refused(self):
        other = make_property(slug="other", name="Other")
        outsider = make_user("out@example.com")
        assign(outsider, other, "RECEPTIONIST")
        with self.assertRaises(NotPermitted):
            self.manual(actor=outsider)

    def test_room_key_from_another_property_refused(self):
        other = make_property(slug="other", name="Other")
        with self.assertRaises(InvalidSelection):
            self.manual(key=key_for(make_room(other, "1")))

    def test_double_booking_refused(self):
        self.manual()
        with self.assertRaises(RoomUnavailable):
            self.manual()

    def test_past_dates_refused_but_the_propertys_today_is_allowed(self):
        with self.assertRaises(InvalidDates):
            self.manual(ci=self.today - timedelta(days=1))
        self.assertEqual(self.manual(ci=self.today)["bookings"][0].check_in, self.today)

    def test_user_without_a_role_refused(self):
        with self.assertRaises(NotPermitted):
            self.manual(actor=self.guest)


class PaymentAndRefundTests(LifecycleBase):
    def test_record_payment_on_a_manual_booking(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co, source="WALK_IN")
        record_payment(b.pk, actor=self.rec, method="CASH")
        b.refresh_from_db()
        self.assertEqual(b.payment_status, "PAID")
        self.assertEqual(b.history.get(action="PAYMENT").details["method"], "CASH")
        with self.assertRaises(InvalidTransition):
            record_payment(b.pk, actor=self.rec, method="CASH")        # already paid

    def test_online_booking_payment_cannot_be_recorded_by_hand(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co)                            # source defaults to ONLINE
        with self.assertRaises(InvalidTransition):
            record_payment(b.pk, actor=self.rec, method="CASH")

    def test_refund_completion_is_manager_only_and_happens_once(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co, customer=self.guest, payment_status="PAID")
        cancel_booking(b.pk, actor=self.guest)
        task = RefundTask.objects.get()
        with self.assertRaises(NotPermitted):
            complete_refund(task.pk, actor=self.rec)
        complete_refund(task.pk, actor=self.mgr)
        task.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((task.status, task.completed_by, b.payment_status), ("DONE", self.mgr, "REFUNDED"))
        with self.assertRaises(InvalidTransition):
            complete_refund(task.pk, actor=self.mgr)

    def test_history_is_append_only(self):
        ci, co = self.far()
        b = make_booking(self.room, ci, co)
        h = BookingHistory.objects.create(booking=b, action="CREATED", actor_label="system")
        h.reason = "tampered"
        with self.assertRaises(RuntimeError):
            h.save()