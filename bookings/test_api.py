from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from properties.tests import make_property

from .test_services import GUEST, key_for
from .tests import make_room


class BookingApiTests(TestCase):
    def setUp(self):
        self.room = make_room(make_property(), "101")
        self.ci = timezone.localdate() + timedelta(days=5)
        self.body = {"check_in": str(self.ci), "check_out": str(self.ci + timedelta(days=2)),
                     "items": [{"key": key_for(self.room), "quantity": 1}]}

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")

    def test_quote_is_server_calculated(self):
        resp = self.post("/api/v1/quotes/", {**self.body, "total": "1.00"})   # forged total ignored
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], "5000.00")

    def test_hold_then_second_hold_conflicts(self):
        self.assertEqual(self.post("/api/v1/holds/", {**self.body, **GUEST}).status_code, 201)
        second = self.post("/api/v1/holds/", {**self.body, **GUEST})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "room_unavailable")

    def test_guest_details_validated_by_the_form(self):
        resp = self.post("/api/v1/holds/", {**self.body, **GUEST, "email": "nope", "phone": "12"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("email", resp.json())
        self.assertIn("phone", resp.json())

    def test_confirmation_page_is_private_to_the_session(self):
        ref = self.post("/api/v1/holds/", {**self.body, **GUEST}).json()["group_ref"]
        self.assertEqual(self.client.get(f"/book/success/?ref={ref}").status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(f"/book/success/?ref={ref}").status_code, 404)

    def test_engine_page_renders(self):
        self.assertEqual(self.client.get("/book/").status_code, 200)
        self.assertEqual(self.client.get("/book/?check_in=2020-01-01&check_out=2020-01-02").status_code, 200)