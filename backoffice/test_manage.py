import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from bookings.models import Booking
from bookings.test_services import GUEST, key_for
from properties.models import Property
from rooms.models import Room, RoomImage

from .test_access import AccessTestBase

DAY = timedelta(days=1)
MEDIA = tempfile.mkdtemp()


class ManualBookingScreenTests(AccessTestBase):
    def body(self, **over):
        t = self.a.local_today()
        data = {"property": "a", "check_in": str(t + DAY), "check_out": str(t + 3 * DAY),
                "source": "WALK_IN", **GUEST, "qty__" + key_for(self.room_a): "1"}
        data.update(over)
        return data

    def test_search_shows_the_available_room_type(self):
        t = self.a.local_today()
        self.client.force_login(self.rec_a)
        resp = self.client.get(f"/staff/bookings/new/?property=a&check_in={t + DAY}&check_out={t + 3 * DAY}")
        self.assertContains(resp, f'name="qty__{key_for(self.room_a)}"')

    def test_creates_a_confirmed_unpaid_booking_and_opens_it(self):
        self.client.force_login(self.rec_a)
        resp = self.client.post("/staff/bookings/new/", self.body())
        b = Booking.objects.get(source="WALK_IN")
        self.assertRedirects(resp, f"/staff/bookings/{b.reference}/", fetch_redirect_response=False)
        self.assertEqual((b.status, b.payment_status, b.created_by, b.total_amount),
                         ("CONFIRMED", "UNPAID", self.rec_a, Decimal_5000()))

    def test_property_outside_the_staff_members_scope_is_refused(self):
        self.client.force_login(self.rec_a)
        resp = self.client.post("/staff/bookings/new/", self.body(property="b"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Booking.objects.filter(source="WALK_IN").exists())

    def test_room_key_from_another_property_is_refused(self):
        self.client.force_login(self.rec_a)
        data = self.body()
        del data["qty__" + key_for(self.room_a)]
        data["qty__" + key_for(self.room_b)] = "1"
        resp = self.client.post("/staff/bookings/new/", data)
        self.assertContains(resp, "does not belong to this property")
        self.assertFalse(Booking.objects.filter(source="WALK_IN").exists())

    def test_second_booking_for_the_same_room_is_refused(self):
        self.client.force_login(self.rec_a)
        self.client.post("/staff/bookings/new/", self.body())
        resp = self.client.post("/staff/bookings/new/", self.body())
        self.assertContains(resp, "just taken")
        self.assertEqual(Booking.objects.filter(source="WALK_IN").count(), 1)

    def test_customer_is_forbidden(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get("/staff/bookings/new/").status_code, 403)
        self.assertEqual(self.client.post("/staff/bookings/new/", self.body()).status_code, 403)

    def test_past_dates_are_refused(self):
        t = self.a.local_today()
        self.client.force_login(self.rec_a)
        resp = self.client.post("/staff/bookings/new/",
                                self.body(check_in=str(t - 2 * DAY), check_out=str(t - DAY)))
        self.assertContains(resp, "cannot be in the past")
        self.assertFalse(Booking.objects.filter(source="WALK_IN").exists())


def Decimal_5000():
    from decimal import Decimal
    return Decimal("5000.00")


class PropertyScreenTests(AccessTestBase):
    def data(self, **over):
        d = dict(name="Alpha", description="d", address_line="1 Rd", city="Chennai", state="TN",
                 country="India", phone="9999999999", email="a@example.com", timezone="Asia/Kolkata",
                 check_in_time="14:00", check_out_time="11:00", free_cancellation_hours=24, tax_percent="12")
        d.update(over)
        return d

    def test_list_is_scoped_to_managed_properties(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual([p.pk for p in self.client.get("/staff/properties/").context["properties"]], [self.a.pk])

    def test_manager_edits_their_property(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post(f"/staff/properties/{self.a.pk}/", self.data(name="Alpha Renamed"))
        self.assertRedirects(resp, "/staff/properties/", fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertEqual((self.a.name, str(self.a.tax_percent), self.a.is_active), ("Alpha Renamed", "12.00", True))

    def test_other_property_is_404_and_receptionist_is_403(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get(f"/staff/properties/{self.b.pk}/").status_code, 404)
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get("/staff/properties/").status_code, 403)

    def test_invalid_timezone_is_rejected(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post(f"/staff/properties/{self.a.pk}/", self.data(timezone="Mars/Olympus"))
        self.assertEqual(resp.status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual(self.a.timezone, "Asia/Kolkata")

    def test_only_a_superuser_creates_properties_and_slugs_stay_unique(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get("/staff/properties/new/").status_code, 403)
        self.assertEqual(self.client.post("/staff/properties/new/", self.data(name="Gamma Stay")).status_code, 403)
        self.client.force_login(self.boss)
        for _ in range(2):
            self.client.post("/staff/properties/new/", self.data(name="Gamma Stay", is_active="on"))
        slugs = set(Property.objects.filter(name="Gamma Stay").values_list("slug", flat=True))
        self.assertEqual(slugs, {"gamma-stay", "gamma-stay-2"})

    def test_only_a_superuser_sees_the_active_toggle(self):
        self.client.force_login(self.mgr_a)
        self.assertNotContains(self.client.get(f"/staff/properties/{self.a.pk}/"), 'name="is_active"')
        self.client.force_login(self.boss)
        self.assertContains(self.client.get(f"/staff/properties/{self.a.pk}/"), 'name="is_active"')


class RoomScreenTests(AccessTestBase):
    def data(self, **over):
        d = dict(property=self.a.pk, room_type=self.room_a.room_type.pk, bed_type=self.room_a.bed_type.pk,
                 number="102", max_guests=2, base_occupancy=2, bed_count=1, size_unit="SQFT",
                 price_per_night="2800", extra_guest_charge="0", operational_status="ACTIVE")
        d.update(over)
        return d

    def test_manager_creates_a_room(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post("/staff/rooms/new/", self.data())
        room = Room.objects.get(property=self.a, number="102")
        self.assertRedirects(resp, f"/staff/rooms/{room.pk}/", fetch_redirect_response=False)

    def test_duplicate_room_number_gets_a_friendly_error(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post("/staff/rooms/new/", self.data(number="101"))
        self.assertContains(resp, "already exists")
        self.assertEqual(Room.objects.filter(property=self.a).count(), 1)

    def test_cannot_create_a_room_at_an_unmanaged_property(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post("/staff/rooms/new/", self.data(property=self.b.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Room.objects.filter(number="102").exists())

    def test_price_change_does_not_touch_existing_bookings(self):
        self.client.force_login(self.mgr_a)
        self.client.post(f"/staff/rooms/{self.room_a.pk}/", self.data(number="101", price_per_night="3000"))
        self.room_a.refresh_from_db()
        self.bk_a.refresh_from_db()
        self.assertEqual((str(self.room_a.price_per_night), str(self.bk_a.price_per_night)), ("3000.00", "2500.00"))

    def test_a_room_cannot_be_moved_to_another_property(self):
        self.client.force_login(self.boss)
        self.client.post(f"/staff/rooms/{self.room_a.pk}/", self.data(number="101", property=self.b.pk))
        self.room_a.refresh_from_db()
        self.assertEqual(self.room_a.property_id, self.a.pk)

    def test_cannot_take_a_room_with_bookings_out_of_service(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post(f"/staff/rooms/{self.room_a.pk}/",
                                self.data(number="101", operational_status="OUT_OF_SERVICE"))
        self.assertContains(resp, "upcoming")
        self.room_a.refresh_from_db()
        self.assertEqual(self.room_a.operational_status, "ACTIVE")

    def test_a_free_room_can_be_taken_out_of_service(self):
        from bookings.tests import make_room
        free = make_room(self.a, "150")
        self.client.force_login(self.mgr_a)
        self.client.post(f"/staff/rooms/{free.pk}/", self.data(number="150", operational_status="OUT_OF_SERVICE"))
        free.refresh_from_db()
        self.assertEqual(free.operational_status, "OUT_OF_SERVICE")

    def test_receptionist_is_forbidden(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get("/staff/rooms/").status_code, 403)
        self.assertEqual(self.client.get("/staff/rooms/new/").status_code, 403)

    def test_list_is_scoped(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual({r.pk for r in self.client.get("/staff/rooms/").context["rooms"]}, {self.room_a.pk})

    def test_other_propertys_room_is_404(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get(f"/staff/rooms/{self.room_b.pk}/").status_code, 404)


@override_settings(MEDIA_ROOT=MEDIA)
class ImageScreenTests(AccessTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA, ignore_errors=True)

    @staticmethod
    def png():
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(buf, "PNG")
        return SimpleUploadedFile("a.png", buf.getvalue(), content_type="image/png")

    def add(self, room, **files):
        return self.client.post(f"/staff/rooms/{room.pk}/images/add/",
                                {"image": files.get("image") or self.png(), "caption": "x", "sort_order": 0})

    def test_manager_adds_a_photo(self):
        self.client.force_login(self.mgr_a)
        self.add(self.room_a)
        self.assertEqual(RoomImage.objects.filter(room=self.room_a).count(), 1)

    def test_a_non_image_is_rejected(self):
        self.client.force_login(self.mgr_a)
        self.add(self.room_a, image=SimpleUploadedFile("a.png", b"not an image", content_type="image/png"))
        self.assertEqual(RoomImage.objects.count(), 0)

    def test_other_propertys_room_is_404(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.add(self.room_b).status_code, 404)
        self.assertEqual(RoomImage.objects.count(), 0)

    def test_manager_removes_a_photo(self):
        self.client.force_login(self.mgr_a)
        self.add(self.room_a)
        img = RoomImage.objects.get()
        self.client.post(f"/staff/rooms/{self.room_a.pk}/images/{img.pk}/delete/")
        self.assertEqual(RoomImage.objects.count(), 0)