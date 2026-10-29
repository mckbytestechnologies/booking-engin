from datetime import timedelta

from django.test import TestCase

from bookings.models import RefundTask
from bookings.tests import make_booking, make_room
from properties.tests import make_property

from .test_auth import make_user


class CustomerCancelTests(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.room = make_room(self.prop, "101")
        self.user = make_user("asha@example.com")
        ci = self.prop.local_today() + timedelta(days=10)
        self.booking = make_booking(self.room, ci, ci + timedelta(days=3),
                                    customer=self.user, payment_status="PAID")
        self.url = f"/account/bookings/{self.booking.reference}/cancel/"

    def test_owner_sees_the_policy_then_cancels_with_a_post(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url), "Free cancellation")
        self.assertRedirects(self.client.post(self.url), "/account/")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CANCELLED")
        self.assertEqual(RefundTask.objects.get().amount, self.booking.total_amount)

    def test_get_never_changes_state(self):
        self.client.force_login(self.user)
        self.client.get(self.url)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CONFIRMED")

    def test_someone_elses_booking_is_404(self):
        self.client.force_login(make_user("other@example.com"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)