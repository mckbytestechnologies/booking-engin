from datetime import timedelta

from django.test import TestCase

from bookings.models import ExtensionRequest
from bookings.tests import make_booking, make_room
from properties.tests import make_property

from .test_auth import make_user


class CustomerExtendTests(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.room = make_room(self.prop, "101")
        self.user = make_user("asha@example.com")
        self.ci = self.prop.local_today() + timedelta(days=10)
        self.co = self.ci + timedelta(days=3)
        self.booking = make_booking(self.room, self.ci, self.co, customer=self.user, payment_status="PAID")
        self.url = f"/account/bookings/{self.booking.reference}/extend/"

    def test_owner_requests_an_extension(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {"new_check_out": str(self.co + timedelta(days=1))})
        self.assertRedirects(resp, "/account/")
        self.assertEqual(ExtensionRequest.objects.get().status, "REQUESTED")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.check_out, self.co)             # unchanged until staff approve

    def test_someone_elses_booking_is_404(self):
        self.client.force_login(make_user("other@example.com"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"new_check_out": str(self.co + timedelta(days=1))}).status_code, 404)

    def test_invalid_date_shows_an_error_and_creates_nothing(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {"new_check_out": str(self.co)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "must be after")
        self.assertEqual(ExtensionRequest.objects.count(), 0)