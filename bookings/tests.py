from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from properties.tests import make_property
from rooms.models import BedType, Room, RoomType

from .models import Booking, RoomBlock
from .services.availability import InvalidDates, availability_groups, free_room_ids, validate_stay


def make_room(prop, number, **kw):
    rtype, _ = RoomType.objects.get_or_create(name=kw.pop("type_name", "Deluxe"))
    bed, _ = BedType.objects.get_or_create(name="King")
    defaults = dict(property=prop, room_type=rtype, bed_type=bed, number=number,
                    price_per_night=Decimal("2500.00"))
    defaults.update(kw)
    return Room.objects.create(**defaults)


def make_booking(room, check_in, check_out, **kw):
    defaults = dict(property=room.property, room=room, customer_name="Asha", customer_email="a@example.com",
                    customer_phone="9999999999", check_in=check_in, check_out=check_out, guests=2,
                    price_per_night=room.price_per_night, total_amount=Decimal("7500.00"),
                    status=Booking.Status.CONFIRMED)
    defaults.update(kw)
    return Booking.objects.create(**defaults)


D = lambda day: date(2026, 11, day)


class OverlapTests(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.room = make_room(self.prop, "101")
        make_booking(self.room, D(10), D(13))

    def free(self, ci, co):
        return self.room.id in free_room_ids(ci, co)

    def test_back_to_back_allowed(self):
        self.assertTrue(self.free(D(13), D(15)))   # starts on the existing check-out day
        self.assertTrue(self.free(D(8), D(10)))    # ends on the existing check-in day

    def test_overlaps_rejected(self):
        cases = {"inside": (D(11), D(12)), "starts_during": (D(12), D(14)),
                 "ends_during": (D(8), D(11)), "contains": (D(9), D(14)), "identical": (D(10), D(13))}
        for name, (ci, co) in cases.items():
            with self.subTest(name):
                self.assertFalse(self.free(ci, co))

    def test_cancelled_and_no_show_release_the_room(self):
        for status in (Booking.Status.CANCELLED, Booking.Status.NO_SHOW, Booking.Status.EXPIRED):
            with self.subTest(status):
                Booking.objects.update(status=status)
                self.assertTrue(self.free(D(10), D(13)))

    def test_pending_hold_blocks_until_expiry(self):
        Booking.objects.update(status=Booking.Status.PENDING, expires_at=timezone.now() + timedelta(minutes=30))
        self.assertFalse(self.free(D(10), D(13)))
        Booking.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertTrue(self.free(D(10), D(13)))

    def test_checked_out_still_blocks_reserved_nights(self):
        Booking.objects.update(status=Booking.Status.CHECKED_OUT)    # decision 8
        self.assertFalse(self.free(D(11), D(12)))

    def test_room_block_blocks_and_adjacent_dates_are_free(self):
        RoomBlock.objects.create(room=self.room, start_date=D(20), end_date=D(23), reason="Repainting")
        self.assertFalse(self.free(D(21), D(22)))
        self.assertTrue(self.free(D(23), D(25)))

    def test_out_of_service_and_inactive_property_excluded(self):
        down = make_room(self.prop, "102", operational_status="OUT_OF_SERVICE")
        closed = make_property(slug="closed", name="Closed", is_active=False)
        shut = make_room(closed, "1")
        ids = free_room_ids(D(20), D(22))
        self.assertIn(self.room.id, ids)
        self.assertNotIn(down.id, ids)
        self.assertNotIn(shut.id, ids)


class DateValidationTests(TestCase):
    today = date(2026, 11, 1)

    def test_checkout_must_follow_checkin(self):
        with self.assertRaises(InvalidDates):
            validate_stay(D(5), D(5), self.today)
        with self.assertRaises(InvalidDates):
            validate_stay(D(6), D(5), self.today)

    def test_past_checkin_rejected(self):
        with self.assertRaises(InvalidDates):
            validate_stay(date(2026, 10, 30), D(5), self.today)

    def test_overlong_stay_rejected(self):
        with self.assertRaises(InvalidDates):
            validate_stay(D(5), D(5) + timedelta(days=400), self.today)

    def test_valid_stay_accepted(self):
        validate_stay(D(5), D(8), self.today)


class GroupingTests(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.rooms = [make_room(self.prop, str(100 + i)) for i in range(3)]

    def test_count_drops_when_one_room_is_booked(self):
        make_booking(self.rooms[0], D(10), D(13))
        items = availability_groups(D(11), D(12))[0]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["available_count"], 2)

    def test_sold_out_type_is_still_listed_with_zero(self):
        for r in self.rooms:
            make_booking(r, D(10), D(13))
        items = availability_groups(D(11), D(12))[0]["items"]
        self.assertEqual(items[0]["available_count"], 0)


class ConstraintTests(TestCase):
    def setUp(self):
        self.room = make_room(make_property(), "101")

    def test_database_rejects_checkout_not_after_checkin(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_booking(self.room, D(10), D(10))

    def test_references_are_generated_and_unique(self):
        a = make_booking(self.room, D(1), D(2))
        b = make_booking(self.room, D(3), D(4))
        self.assertRegex(a.reference, r"^HB-[A-Z2-9]{8}$")
        self.assertNotEqual(a.reference, b.reference)


class AvailabilityApiTests(TestCase):
    def setUp(self):
        make_room(make_property(), "101")
        self.in_ = timezone.localdate() + timedelta(days=5)
        self.out = self.in_ + timedelta(days=2)

    def test_valid_search_returns_counts_without_internal_ids(self):
        resp = self.client.get(f"/api/v1/availability/?check_in={self.in_}&check_out={self.out}")
        self.assertEqual(resp.status_code, 200)
        rt = resp.json()["properties"][0]["room_types"][0]
        self.assertEqual(rt["available_count"], 1)
        self.assertNotIn("free_room_ids", rt)

    def test_invalid_dates_return_400(self):
        resp = self.client.get(f"/api/v1/availability/?check_in={self.out}&check_out={self.in_}")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get("/api/v1/availability/")
        self.assertEqual(resp.status_code, 400)