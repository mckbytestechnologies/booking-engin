from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from properties.tests import make_property
from rooms.models import BedType, Room, RoomType


class RoomModelTests(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.rtype = RoomType.objects.create(name="Deluxe")
        self.bed = BedType.objects.create(name="King")

    def make_room(self, **kw):
        defaults = dict(
            property=self.prop, room_type=self.rtype, bed_type=self.bed,
            number="101", price_per_night=Decimal("2500.00"),
        )
        defaults.update(kw)
        return Room.objects.create(**defaults)

    def test_room_number_unique_within_property_only(self):
        self.make_room()
        other = make_property(slug="other", name="Other")
        self.make_room(property=other)  # same number, different property: allowed
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_room()            # same property: blocked

    def test_negative_price_blocked(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_room(price_per_night=Decimal("-1"))

    def test_base_occupancy_cannot_exceed_max_guests(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_room(max_guests=2, base_occupancy=4)

    def test_property_with_rooms_cannot_be_deleted(self):
        self.make_room()
        with self.assertRaises(ProtectedError):
            self.prop.delete()

    def test_default_statuses(self):
        room = self.make_room()
        self.assertEqual(room.operational_status, "ACTIVE")
        self.assertEqual(room.housekeeping_status, "CLEAN")