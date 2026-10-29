from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from bookings.models import Booking
from bookings.tests import make_booking
from properties.models import StaffAssignment
from properties.tests import make_property

from .test_access import PW, AccessTestBase

DAY = timedelta(days=1)


class StaffLoginTests(AccessTestBase):
    def login(self, email):
        return self.client.post("/staff/login/", {"username": email, "password": PW})

    def test_login_page_renders(self):
        self.assertContains(self.client.get("/staff/login/"), "Staff sign in")

    def test_staff_signs_in_to_the_dashboard(self):
        self.assertRedirects(self.login("rec_a@example.com"), "/staff/")

    def test_customer_is_refused_and_not_logged_in(self):
        resp = self.login("cust@example.com")
        self.assertContains(resp, "does not have staff access")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_anonymous_is_sent_to_the_staff_login(self):
        resp = self.client.get("/staff/bookings/")
        self.assertRedirects(resp, "/staff/login/?next=/staff/bookings/", fetch_redirect_response=False)


class BookingListTests(AccessTestBase):
    def test_list_is_scoped_to_the_staff_members_property(self):
        self.client.force_login(self.rec_a)
        html = self.client.get("/staff/bookings/").content.decode()
        self.assertIn(self.bk_a.reference, html)
        self.assertNotIn(self.bk_b.reference, html)

    def test_search_and_status_filter(self):
        other = make_booking(self.room_a, self.d + 10 * DAY, self.d + 12 * DAY,
                             status="CANCELLED", customer_name="Zed Zimmer")
        self.client.force_login(self.rec_a)
        for query in ("?q=Zimmer", "?status=CANCELLED"):
            html = self.client.get("/staff/bookings/" + query).content.decode()
            self.assertIn(other.reference, html)
            self.assertNotIn(self.bk_a.reference, html)

    def test_pagination_is_25_per_page(self):
        for i in range(30):
            make_booking(self.room_a, self.d + (10 + 3 * i) * DAY, self.d + (12 + 3 * i) * DAY)
        self.client.force_login(self.rec_a)
        self.assertEqual(len(self.client.get("/staff/bookings/").context["bookings"]), 25)
        self.assertEqual(len(self.client.get("/staff/bookings/?page=2").context["bookings"]), 6)

    def test_invalid_filters_do_not_crash(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get("/staff/bookings/?date_from=garbage&status=NOPE").status_code, 200)

    def test_customer_is_forbidden(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get("/staff/bookings/").status_code, 403)


class BookingDetailTests(AccessTestBase):
    def action_url(self, b, name):
        return f"/staff/bookings/{b.reference}/{name}/"

    def test_other_propertys_booking_is_404(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get(f"/staff/bookings/{self.bk_b.reference}/").status_code, 404)

    def test_buttons_follow_the_booking_state(self):
        t = self.a.local_today()
        today_b = make_booking(self.room_a, t, t + 2 * DAY)
        self.client.force_login(self.rec_a)
        future = self.client.get(f"/staff/bookings/{self.bk_a.reference}/").content.decode()
        self.assertNotIn(self.action_url(self.bk_a, "check-in"), future)
        self.assertIn(self.action_url(self.bk_a, "cancel"), future)
        now = self.client.get(f"/staff/bookings/{today_b.reference}/").content.decode()
        self.assertIn(self.action_url(today_b, "check-in"), now)

    def test_waive_option_is_for_managers_only(self):
        self.client.force_login(self.rec_a)
        self.assertNotContains(self.client.get(f"/staff/bookings/{self.bk_a.reference}/"), "waive_penalty")
        self.client.force_login(self.mgr_a)
        self.assertContains(self.client.get(f"/staff/bookings/{self.bk_a.reference}/"), "waive_penalty")

    def test_dashboard_lists_todays_arrivals(self):
        t = self.a.local_today()
        arrival = make_booking(self.room_a, t, t + 2 * DAY)
        self.client.force_login(self.rec_a)
        self.assertContains(self.client.get("/staff/"), arrival.reference)


class BookingActionTests(AccessTestBase):
    def url(self, b, name):
        return f"/staff/bookings/{b.reference}/{name}/"

    def test_cancel_works_and_reports_the_outcome(self):
        self.client.force_login(self.rec_a)
        resp = self.client.post(self.url(self.bk_a, "cancel"), {"reason": "Guest called"}, follow=True)
        self.assertContains(resp, "Booking cancelled")
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.status, "CANCELLED")

    def test_other_property_is_404(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.post(self.url(self.bk_b, "cancel")).status_code, 404)
        self.bk_b.refresh_from_db()
        self.assertEqual(self.bk_b.status, "CONFIRMED")

    def test_customer_is_forbidden(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(self.url(self.bk_a, "cancel")).status_code, 403)

    def test_get_never_changes_anything(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get(self.url(self.bk_a, "cancel")).status_code, 405)
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.status, "CONFIRMED")

    def test_unpaid_checkout_is_blocked_with_a_message(self):
        t = self.a.local_today()
        b = make_booking(self.room_a, t - DAY, t + DAY, status="CHECKED_IN")
        self.client.force_login(self.rec_a)
        resp = self.client.post(self.url(b, "check-out"), follow=True)
        self.assertContains(resp, "is still due")
        b.refresh_from_db()
        self.assertEqual(b.status, "CHECKED_IN")

    def test_receptionist_cannot_waive_the_fee(self):
        t = self.a.local_today()
        b = make_booking(self.room_a, t, t + 2 * DAY, payment_status="PAID")
        self.client.force_login(self.rec_a)
        resp = self.client.post(self.url(b, "cancel"), {"waive_penalty": "on", "reason": "x"}, follow=True)
        self.assertContains(resp, "Only a manager")
        b.refresh_from_db()
        self.assertEqual(b.status, "CONFIRMED")

    def test_desk_payment_can_be_recorded(self):
        b = make_booking(self.room_a, self.d + 10 * DAY, self.d + 12 * DAY, source="WALK_IN")
        self.client.force_login(self.rec_a)
        self.assertContains(self.client.post(self.url(b, "mark-paid"), {"method": "CASH"}, follow=True),
                            "Payment recorded")
        b.refresh_from_db()
        self.assertEqual(b.payment_status, "PAID")

    def test_extend_updates_the_stay(self):
        self.client.force_login(self.rec_a)
        resp = self.client.post(self.url(self.bk_a, "extend"),
                                {"new_check_out": str(self.d + 4 * DAY)}, follow=True)
        self.assertContains(resp, "Stay extended")
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.check_out, self.d + 4 * DAY)


class CreateStaffCommandTests(TestCase):
    PW = "Tr1cky-Horse-Battery"

    def run_cmd(self, *args):
        call_command("create_staff", *args, stdout=StringIO())

    def test_creates_a_user_with_the_role(self):
        prop = make_property()
        self.run_cmd("Desk@Example.com", "--property", prop.slug, "--role", "MANAGER", "--password", self.PW)
        a = StaffAssignment.objects.get()
        self.assertEqual((a.user.email, a.role, a.user.is_staff), ("desk@example.com", "MANAGER", False))
        self.assertTrue(a.user.check_password(self.PW))

    def test_running_again_updates_instead_of_duplicating(self):
        prop = make_property()
        self.run_cmd("d@example.com", "--property", prop.slug, "--password", self.PW)
        self.run_cmd("d@example.com", "--property", prop.slug, "--role", "MANAGER", "--password", self.PW)
        self.assertEqual(StaffAssignment.objects.count(), 1)
        self.assertEqual(StaffAssignment.objects.get().role, "MANAGER")

    def test_weak_password_is_rejected(self):
        prop = make_property()
        with self.assertRaises(CommandError):
            self.run_cmd("d@example.com", "--property", prop.slug, "--password", "12345678")

    def test_unknown_property_is_rejected(self):
        with self.assertRaises(CommandError):
            self.run_cmd("d@example.com", "--property", "nope", "--password", self.PW)