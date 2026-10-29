from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from properties.models import Amenity
from properties.tests import make_property
from rooms.models import BedType, Room, RoomType


class RoomApiTests(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.rtype = RoomType.objects.create(name="Deluxe")
        self.bed = BedType.objects.create(name="King")
        self.wifi = Amenity.objects.create(name="Wi-Fi")

    def room(self, number, **kw):
        defaults = dict(property=self.prop, room_type=self.rtype, bed_type=self.bed,
                        number=number, price_per_night=Decimal("2500.00"))
        defaults.update(kw)
        r = Room.objects.create(**defaults)
        r.amenities.add(self.wifi)
        return r

    def test_anonymous_can_list_rooms(self):
        self.room("101")
        resp = self.client.get("/api/v1/rooms/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_internal_fields_not_exposed(self):
        self.room("101")
        data = self.client.get("/api/v1/rooms/").json()["results"][0]
        self.assertNotIn("housekeeping_status", data)
        self.assertNotIn("operational_status", data)

    def test_inactive_property_and_out_of_service_rooms_hidden(self):
        self.room("101")
        self.room("102", operational_status="OUT_OF_SERVICE")
        hidden = make_property(slug="closed", name="Closed", is_active=False)
        Room.objects.create(property=hidden, room_type=self.rtype, bed_type=self.bed,
                            number="1", price_per_night=1000)
        self.assertEqual(self.client.get("/api/v1/rooms/").json()["count"], 1)
        self.assertEqual(self.client.get("/api/v1/properties/closed/").status_code, 404)

    def test_price_filter(self):
        self.room("101", price_per_night=Decimal("1500"))
        self.room("102", price_per_night=Decimal("4000"))
        data = self.client.get("/api/v1/rooms/?max_price=2000").json()
        self.assertEqual([r["number"] for r in data["results"]], ["101"])

    def test_pagination_and_page_size(self):
        for i in range(15):
            self.room(str(200 + i))
        data = self.client.get("/api/v1/rooms/").json()
        self.assertEqual(len(data["results"]), 12)
        self.assertIsNotNone(data["next"])

    def test_write_methods_not_allowed(self):
        self.assertEqual(self.client.post("/api/v1/rooms/", {}).status_code, 405)

    def test_query_count_does_not_grow_with_rooms(self):
        for i in range(2):
            self.room(f"A{i}")
        with CaptureQueriesContext(connection) as few:
            self.client.get("/api/v1/rooms/")
        for i in range(8):
            self.room(f"B{i}")
        with CaptureQueriesContext(connection) as many:
            self.client.get("/api/v1/rooms/")
        self.assertEqual(len(few), len(many))   # no N+1


class PublicPageTests(TestCase):
    def test_pages_render(self):
        make_property()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/properties/").status_code, 200)
        self.assertEqual(self.client.get("/properties/sea-view/").status_code, 200)

    def test_inactive_property_page_is_404(self):
        make_property(slug="closed", name="Closed", is_active=False)
        self.assertEqual(self.client.get("/properties/closed/").status_code, 404)