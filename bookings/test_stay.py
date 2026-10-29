from datetime import timedelta
from decimal import Decimal

from rooms.models import Room

from .models import ExtensionRequest, RefundTask
from .services.availability import free_room_ids
from .services.balance import outstanding
from .services.errors import (ExtensionConflict, InvalidDates, InvalidTransition, NotPermitted,
                              PaymentOutstanding, PricingError, ReasonRequired)
from .services.lifecycle import cancel_booking, record_payment
from .services.stay import (approve_extension, check_in, check_out, extend_now, mark_no_show,
                            reject_extension, request_extension)
from .test_lifecycle import LifecycleBase, make_user
from .tests import make_booking

DAY = timedelta(days=1)


class CheckInTests(LifecycleBase):
    def test_check_in_records_actor_time_and_history(self):
        b = make_booking(self.room, self.today, self.today + 3 * DAY)
        check_in(b.pk, actor=self.rec)
        b.refresh_from_db()
        self.assertEqual((b.status, b.checked_in_by), ("CHECKED_IN", self.rec))
        self.assertIsNotNone(b.actual_check_in)
        self.assertEqual(b.history.get(to_status="CHECKED_IN").actor, self.rec)

    def test_too_early_is_refused(self):
        b = make_booking(self.room, self.today + 2 * DAY, self.today + 4 * DAY)
        with self.assertRaises(InvalidTransition):
            check_in(b.pk, actor=self.rec)
        b.refresh_from_db()
        self.assertEqual(b.status, "CONFIRMED")

    def test_stay_that_already_ended_is_refused(self):
        b = make_booking(self.room, self.today - 5 * DAY, self.today - 2 * DAY)
        with self.assertRaises(InvalidTransition):
            check_in(b.pk, actor=self.rec)

    def test_only_confirmed_bookings_can_check_in(self):
        for status in ("PENDING", "CANCELLED", "CHECKED_IN"):
            with self.subTest(status):
                b = make_booking(self.room, self.today, self.today + 2 * DAY, status=status)
                with self.assertRaises(InvalidTransition):
                    check_in(b.pk, actor=self.rec)

    def test_guest_cannot_check_in(self):
        b = make_booking(self.room, self.today, self.today + 2 * DAY, customer=self.guest)
        with self.assertRaises(NotPermitted):
            check_in(b.pk, actor=self.guest)

    def test_dirty_room_warns_but_does_not_block(self):
        Room.objects.filter(pk=self.room.pk).update(housekeeping_status="DIRTY")
        b = make_booking(self.room, self.today, self.today + 2 * DAY)
        check_in(b.pk, actor=self.rec)
        self.assertEqual(b.history.get(to_status="CHECKED_IN").details["housekeeping"], "DIRTY")


class CheckOutTests(LifecycleBase):
    def in_house(self, ci=-1, co=2, **kw):
        return make_booking(self.room, self.today + ci * DAY, self.today + co * DAY,
                            status="CHECKED_IN", **kw)

    def test_paid_checkout_marks_room_dirty(self):
        b = self.in_house(payment_status="PAID")
        check_out(b.pk, actor=self.rec)
        b.refresh_from_db()
        self.room.refresh_from_db()
        self.assertEqual((b.status, b.checked_out_by, self.room.housekeeping_status),
                         ("CHECKED_OUT", self.rec, "DIRTY"))
        self.assertIsNotNone(b.actual_check_out)
        self.assertEqual(b.history.get(to_status="CHECKED_OUT").details["unused_nights"], 2)

    def test_unpaid_checkout_is_blocked(self):
        b = self.in_house()
        with self.assertRaises(PaymentOutstanding):
            check_out(b.pk, actor=self.rec)
        b.refresh_from_db()
        self.assertEqual(b.status, "CHECKED_IN")

    def test_manager_override_needs_role_and_reason(self):
        b = self.in_house()
        with self.assertRaises(NotPermitted):
            check_out(b.pk, actor=self.rec, override_unpaid=True, reason="x")
        with self.assertRaises(ReasonRequired):
            check_out(b.pk, actor=self.mgr, override_unpaid=True)
        check_out(b.pk, actor=self.mgr, override_unpaid=True, reason="Bank transfer pending")
        h = b.history.get(to_status="CHECKED_OUT")
        self.assertEqual((h.details["unpaid_override"], h.reason), ("7500.00", "Bank transfer pending"))

    def test_early_checkout_keeps_the_reserved_nights_by_default(self):
        b = self.in_house(payment_status="PAID")
        check_out(b.pk, actor=self.rec)
        b.refresh_from_db()
        self.assertEqual(b.check_out, self.today + 2 * DAY)
        self.assertEqual(RefundTask.objects.count(), 0)
        self.assertNotIn(self.room.id, free_room_ids(self.today + DAY, self.today + 2 * DAY))

    def test_manager_can_release_unused_nights_pro_rata(self):
        b = self.in_house(payment_status="PAID")            # 3 nights, 7500
        check_out(b.pk, actor=self.mgr, release_unused_nights=True, reason="Guest left early")
        b.refresh_from_db()
        self.assertEqual((b.check_out, b.total_amount, b.payment_status),
                         (self.today, Decimal("2500.00"), "PAID"))
        self.assertEqual(RefundTask.objects.get().amount, Decimal("5000.00"))
        self.assertTrue(b.history.filter(action="ADJUSTMENT").exists())
        self.assertIn(self.room.id, free_room_ids(self.today, self.today + 2 * DAY))

    def test_release_needs_a_manager(self):
        b = self.in_house(payment_status="PAID")
        with self.assertRaises(NotPermitted):
            check_out(b.pk, actor=self.rec, release_unused_nights=True, reason="x")
        b.refresh_from_db()
        self.assertEqual(b.status, "CHECKED_IN")

    def test_nothing_to_release_is_refused(self):
        b = self.in_house(ci=-3, co=0, payment_status="PAID")
        with self.assertRaises(InvalidTransition):
            check_out(b.pk, actor=self.mgr, release_unused_nights=True, reason="x")

    def test_only_checked_in_can_check_out(self):
        b = make_booking(self.room, self.today, self.today + 2 * DAY)       # CONFIRMED
        with self.assertRaises(InvalidTransition):
            check_out(b.pk, actor=self.rec)


class NoShowTests(LifecycleBase):
    def missed(self, **kw):
        return make_booking(self.room, self.today - DAY, self.today + 2 * DAY, **kw)

    def test_no_show_applies_first_night_fee(self):
        b = self.missed(payment_status="PAID")
        outcome = mark_no_show(b.pk, actor=self.rec)
        b.refresh_from_db()
        self.assertEqual(b.status, "NO_SHOW")
        self.assertEqual((outcome.penalty, outcome.refund), (Decimal("2500.00"), Decimal("5000.00")))
        self.assertEqual(RefundTask.objects.get().amount, Decimal("5000.00"))

    def test_same_day_is_too_early(self):
        b = make_booking(self.room, self.today, self.today + 2 * DAY)
        with self.assertRaises(InvalidTransition):
            mark_no_show(b.pk, actor=self.rec)

    def test_system_job_can_mark_no_show(self):
        b = self.missed()
        mark_no_show(b.pk)                                    # actor=None means the system
        b.refresh_from_db()
        self.assertEqual(b.status, "NO_SHOW")
        self.assertEqual(b.history.get(to_status="NO_SHOW").actor_label, "system")

    def test_guest_cannot_mark_no_show(self):
        b = self.missed(customer=self.guest)
        with self.assertRaises(NotPermitted):
            mark_no_show(b.pk, actor=self.guest)


class ExtensionTests(LifecycleBase):
    def setUp(self):
        super().setUp()
        self.ci = self.today + 5 * DAY
        self.co = self.ci + 3 * DAY
        self.new_out = self.co + 2 * DAY
        self.b = make_booking(self.room, self.ci, self.co, customer=self.guest, payment_status="PAID")

    def test_owner_can_request_without_changing_the_booking(self):
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        self.b.refresh_from_db()
        self.assertEqual((ext.status, self.b.check_out, ext.original_check_out),
                         ("REQUESTED", self.co, self.co))
        self.assertEqual(self.b.history.get(action="EXTENSION").details["event"], "requested")

    def test_approval_extends_and_prices_only_added_nights(self):
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        approve_extension(ext.pk, actor=self.rec)
        self.b.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual((self.b.check_out, self.b.total_amount), (self.new_out, Decimal("12500.00")))
        self.assertEqual((self.b.payment_status, self.b.amount_paid), ("PARTIALLY_PAID", Decimal("7500.00")))
        self.assertEqual(outstanding(self.b), Decimal("5000.00"))
        self.assertEqual((ext.status, ext.added_nights, ext.added_amount, ext.decided_by),
                         ("APPROVED", 2, Decimal("5000.00"), self.rec))

    def test_added_nights_use_current_rate_and_tax(self):
        Room.objects.filter(pk=self.room.pk).update(price_per_night=Decimal("3000.00"))
        type(self.prop).objects.filter(pk=self.prop.pk).update(tax_percent=Decimal("10"))
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        approve_extension(ext.pk, actor=self.rec)
        self.b.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual(ext.added_amount, Decimal("6600.00"))                 # 2 x 3000 + 10% tax
        self.assertEqual((self.b.total_amount, self.b.tax_amount), (Decimal("14100.00"), Decimal("600.00")))
        self.assertEqual(self.b.price_per_night, Decimal("2500.00"))          # snapshot kept

    def test_conflict_at_request_time(self):
        make_booking(self.room, self.co, self.co + 3 * DAY)
        with self.assertRaises(ExtensionConflict):
            request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        self.assertEqual(ExtensionRequest.objects.count(), 0)

    def test_conflict_at_approval_time_changes_nothing(self):
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        make_booking(self.room, self.co + DAY, self.co + 4 * DAY)             # booked in between
        with self.assertRaises(ExtensionConflict):
            approve_extension(ext.pk, actor=self.rec)
        self.b.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual((self.b.check_out, ext.status), (self.co, "REQUESTED"))

    def test_back_to_back_with_the_next_guest_is_allowed(self):
        make_booking(self.room, self.new_out, self.new_out + 2 * DAY)
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        approve_extension(ext.pk, actor=self.rec)
        self.b.refresh_from_db()
        self.assertEqual(self.b.check_out, self.new_out)

    def test_only_one_open_request(self):
        request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        with self.assertRaises(InvalidTransition):
            request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out + DAY)

    def test_rejected_request_cannot_be_approved_later(self):
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        reject_extension(ext.pk, actor=self.rec, note="No capacity")
        with self.assertRaises(InvalidTransition):
            approve_extension(ext.pk, actor=self.rec)
        self.b.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual((self.b.check_out, ext.status), (self.co, "REJECTED"))

    def test_stranger_cannot_request(self):
        with self.assertRaises(NotPermitted):
            request_extension(self.b.pk, actor=make_user("x@example.com"), new_check_out=self.new_out)

    def test_staff_can_extend_directly_but_a_guest_cannot(self):
        with self.assertRaises(NotPermitted):
            extend_now(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        self.assertEqual(ExtensionRequest.objects.count(), 0)                  # rolled back with it
        extend_now(self.b.pk, actor=self.rec, new_check_out=self.new_out)
        self.b.refresh_from_db()
        self.assertEqual(self.b.check_out, self.new_out)
        self.assertEqual(ExtensionRequest.objects.get().status, "APPROVED")

    def test_monthly_rooms_need_whole_months(self):
        Room.objects.filter(pk=self.room.pk).update(monthly_only=True)
        with self.assertRaises(PricingError):
            request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)

    def test_new_checkout_must_be_later(self):
        with self.assertRaises(InvalidDates):
            request_extension(self.b.pk, actor=self.guest, new_check_out=self.co)

    def test_cancelling_closes_open_requests(self):
        ext = request_extension(self.b.pk, actor=self.guest, new_check_out=self.new_out)
        cancel_booking(self.b.pk, actor=self.guest)
        ext.refresh_from_db()
        self.assertEqual(ext.status, "CANCELLED")

    def test_desk_payment_collects_the_extension_balance(self):
        extend_now(self.b.pk, actor=self.rec, new_check_out=self.new_out)
        record_payment(self.b.pk, actor=self.rec, method="CASH")
        self.b.refresh_from_db()
        self.assertEqual((self.b.payment_status, self.b.amount_paid), ("PAID", self.b.total_amount))
        self.assertEqual(self.b.history.get(action="PAYMENT").details["amount"], "5000.00")

    def test_cancel_refunds_only_what_was_paid(self):
        extend_now(self.b.pk, actor=self.rec, new_check_out=self.new_out)       # total 12500, paid 7500
        cancel_booking(self.b.pk, actor=self.guest)
        self.assertEqual(RefundTask.objects.get().amount, Decimal("7500.00"))