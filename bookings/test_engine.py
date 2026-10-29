from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from properties.tests import make_property

from .test_services import GUEST, key_for
from .tests import make_room


class EnginePageTests(TestCase):
    def setUp(self):
        self.room = make_room(make_property(), "101")

    def test_card_is_keyed_and_people_tag_is_hidden_without_holds(self):
        html = self.client.get("/book/").content.decode()
        self.assertIn(f'data-key="{key_for(self.room)}"', html)
        self.assertIn("data-holding hidden", html)
        self.assertNotIn("booking now", html)

    def test_people_tag_shows_a_real_count_after_a_hold(self):
        ci = timezone.localdate() + timedelta(days=5)
        body = {"check_in": str(ci), "check_out": str(ci + timedelta(days=2)),
                "items": [{"key": key_for(self.room), "quantity": 1}], **GUEST}
        self.client.post("/api/v1/holds/", body, content_type="application/json")
        html = self.client.get("/book/").content.decode()
        self.assertIn("1 person is booking now", html)
        self.assertNotIn("data-holding hidden", html)

    def test_room_details_come_from_the_database(self):
        html = self.client.get("/book/").content.decode()
        self.assertIn('id="room-data"', html)
        self.assertIn("Free cancellation up to 24 hours", html)