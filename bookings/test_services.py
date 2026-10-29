from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from properties.tests import make_property

from .models import Booking
from .services.booking import Selection, create_hold, quote_selections
from .services.errors import InvalidSelection, PricingError, RoomUnavailable
from .services.pricing import add_months, quote_room, whole_months
from .tests import make_room

GUEST = dict(first_name="Asha", last_name="K", email="a@example.com", phone="9999999999", special_request="")


def key_for(room):
    return f"{room.property_id}:{room.room_type_id}:{room.price_per_night}:{room.max_guests}:{int(room.monthly_only)}"


class PricingTests(TestCase):
    def setUp(self):
        self.prop = make_property(tax_percent=Decimal("12"))
        self.room = make_room(self.prop, "101", extra_guest_charge=Decimal("500"))
        self.d = timezone.localdate() + timedelta(days=10)

    def test_nights_tax_and_total(self):
        q = quote_room(self.room, self.d, self.d + timedelta(days=3), 2)
        self.assertEqual((q.room_charge, q.tax, q.total), (Decimal("7500.00"), Decimal("900.00"), Decimal("8400.00")))

    def test_extra_guest_charge_above_base_occupancy(self):
        self.room.max_guests = 3
        q = quote_room(self.room, self.d, self.d + timedelta(days=2), 3)
        self.assertEqual(q.extra_guest_charge, Decimal("1000.00"))      # 1 extra x 500 x 2 nights

    def test_too_many_guests_rejected(self):
        with self.assertRaises(PricingError):
            quote_room(self.room, self.d, self.d + timedelta(days=1), 5)

    def test_monthly_rooms_require_whole_months(self):
        self.room.monthly_only = True
        with self.assertRaises(PricingError):
            quote_room(self.room, self.d, self.d + timedelta(days=10), 2)

    def test_month_arithmetic_matches_the_page(self):
        from datetime import date
        self.assertEqual(add_months(date(2027, 1, 31), 1), date(2027, 2, 28))
        self.assertEqual(whole_months(date(2026, 10, 27), date(2026, 11, 27)), 1)
        self.assertEqual(whole_months(date(2026, 10, 27), date(2026, 11, 28)), 0)


class CreateHoldTests(TestCase):
    def setUp(self):
        self.prop = make_property(tax_percent=Decimal("5"))
        self.rooms = [make_room(self.prop, str(100 + i)) for i in range(2)]
        self.key = key_for(self.rooms[0])
        self.ci = timezone.localdate() + timedelta(days=5)
        self.co = self.ci + timedelta(days=2)

    def hold(self, qty=1):
        return create_hold(selections=[Selection(self.key, qty)], check_in=self.ci,
                           check_out=self.co, guest=GUEST)

    def test_two_rooms_are_two_different_physical_rooms(self):
        result = self.hold(qty=2)
        self.assertEqual(len({b.room_id for b in result["bookings"]}), 2)
        self.assertEqual(len({b.group_ref for b in result["bookings"]}), 1)

    def test_price_comes_from_database_with_tax(self):
        b = self.hold()["bookings"][0]
        self.assertEqual((b.price_per_night, b.tax_amount, b.total_amount),
                         (Decimal("2500.00"), Decimal("250.00"), Decimal("5250.00")))
        self.assertEqual(b.status, Booking.Status.PENDING)
        self.assertIsNotNone(b.expires_at)

    def test_sold_out_raises_and_creates_nothing_extra(self):
        self.hold(qty=2)
        before = Booking.objects.count()
        with self.assertRaises(RoomUnavailable):
            self.hold()
        self.assertEqual(Booking.objects.count(), before)

    def test_all_or_nothing_when_one_line_cannot_be_filled(self):
        other = make_room(self.prop, "201", type_name="Suite", price_per_night=Decimal("4000.00"))
        with self.assertRaises(RoomUnavailable):
            create_hold(selections=[Selection(self.key, 1), Selection(key_for(other), 2)],
                        check_in=self.ci, check_out=self.co, guest=GUEST)
        self.assertEqual(Booking.objects.count(), 0)         # first line rolled back too

    def test_forged_key_rejected(self):
        with self.assertRaises(InvalidSelection):
            quote_selections([Selection("garbage")], self.ci, self.co)