from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.permissions import HasPropertyRole
from bookings.models import Booking, Payment
from bookings.tests import make_booking, make_room
from properties.models import StaffAssignment
from properties.tests import make_property

User = get_user_model()
PW = "Tr1cky-Horse-Battery"


def make_user(email, **kw):
    return User.objects.create_user(username=email, email=email, password=PW, **kw)


def assign(user, prop, role):
    return StaffAssignment.objects.create(user=user, property=prop, role=role)


class AccessTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.a = make_property(slug="a", name="Alpha")
        self.b = make_property(slug="b", name="Bravo")
        self.room_a = make_room(self.a, "101")
        self.room_b = make_room(self.b, "201")
        d = timezone.localdate() + timedelta(days=10)
        self.d = d
        self.bk_a = make_booking(self.room_a, d, d + timedelta(days=2), group_ref="G-AAAAAAAA")
        self.bk_b = make_booking(self.room_b, d, d + timedelta(days=2), group_ref="G-BBBBBBBB")
        self.customer = make_user("cust@example.com")
        self.rec_a = make_user("rec_a@example.com")
        self.mgr_a = make_user("mgr_a@example.com")
        self.rec_b = make_user("rec_b@example.com")
        self.boss = make_user("boss@example.com", is_superuser=True)
        assign(self.rec_a, self.a, "RECEPTIONIST")
        assign(self.mgr_a, self.a, "MANAGER")
        assign(self.rec_b, self.b, "RECEPTIONIST")

    def refs(self, user, url="/api/v1/staff/bookings/"):
        self.client.force_login(user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return {r["reference"] for r in resp.json()["results"]}


class PermissionMatrixTests(AccessTestBase):
    def test_anonymous_is_blocked_everywhere(self):
        for url in ("/api/v1/staff/bookings/", f"/api/v1/staff/bookings/{self.bk_a.reference}/",
                    "/api/v1/staff/payments/refunds/", "/api/v1/me/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        resp = self.client.get("/staff/")
        self.assertRedirects(resp, "/staff/login/?next=/staff/", fetch_redirect_response=False)

    def test_customer_is_blocked_from_staff_areas(self):
        self.client.force_login(self.customer)
        for url in ("/api/v1/staff/bookings/", "/api/v1/staff/payments/refunds/", "/staff/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual((me["roles"], me["is_superuser"]), ([], False))

    def test_receptionist_sees_only_own_property(self):
        self.assertEqual(self.refs(self.rec_a), {self.bk_a.reference})
        self.assertEqual(self.refs(self.rec_b), {self.bk_b.reference})

    def test_other_propertys_booking_is_404_not_403(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get(f"/api/v1/staff/bookings/{self.bk_a.reference}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/staff/bookings/{self.bk_b.reference}/").status_code, 404)

    def test_receptionist_cannot_open_refund_queue(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get("/api/v1/staff/payments/refunds/").status_code, 403)

    def test_manager_sees_only_own_propertys_refunds(self):
        for order, group in (("order_A", "G-AAAAAAAA"), ("order_B", "G-BBBBBBBB")):
            Payment.objects.create(group_ref=group, razorpay_order_id=order, amount=100,
                                   status=Payment.Status.REFUND_REQUIRED)
        self.client.force_login(self.mgr_a)
        rows = self.client.get("/api/v1/staff/payments/refunds/").json()["results"]
        self.assertEqual([r["razorpay_order_id"] for r in rows], ["order_A"])

    def test_superuser_sees_everything(self):
        self.assertEqual(self.refs(self.boss), {self.bk_a.reference, self.bk_b.reference})

    def test_inactive_staff_account_is_blocked(self):
        self.rec_a.is_active = False
        self.rec_a.save()
        self.client.force_login(self.rec_a)               # inactive users are rejected on load
        self.assertEqual(self.client.get("/api/v1/staff/bookings/").status_code, 403)

    def test_assignment_at_two_properties_gives_both(self):
        assign(self.rec_a, self.b, "RECEPTIONIST")
        self.assertEqual(self.refs(self.rec_a), {self.bk_a.reference, self.bk_b.reference})

    def test_staff_endpoints_are_read_only(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.post("/api/v1/staff/bookings/", {}).status_code, 405)
        url = f"/api/v1/staff/bookings/{self.bk_a.reference}/"
        self.assertEqual(self.client.patch(url, {"status": "CANCELLED"}, content_type="application/json").status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_object_permission_class_denies_other_property_directly(self):
        perm = HasPropertyRole()
        self.assertTrue(perm.has_object_permission(SimpleNamespace(user=self.rec_a), None, self.bk_a))
        self.assertFalse(perm.has_object_permission(SimpleNamespace(user=self.rec_a), None, self.bk_b))


class StaffApiBehaviourTests(AccessTestBase):
    def test_list_query_count_does_not_grow(self):
        self.client.force_login(self.rec_a)
        with CaptureQueriesContext(connection) as few:
            self.client.get("/api/v1/staff/bookings/")
        for i in range(6):
            make_booking(self.room_a, self.d + timedelta(days=10 + 3 * i), self.d + timedelta(days=12 + 3 * i))
        with CaptureQueriesContext(connection) as many:
            self.client.get("/api/v1/staff/bookings/")
        self.assertEqual(len(few), len(many))

    def test_filter_and_money_format(self):
        make_booking(self.room_a, self.d + timedelta(days=20), self.d + timedelta(days=22),
                     status=Booking.Status.CANCELLED)
        self.client.force_login(self.rec_a)
        data = self.client.get("/api/v1/staff/bookings/?status=CANCELLED").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["total_amount"], "7500.00")      # string, not float

    def test_me_lists_roles(self):
        self.client.force_login(self.mgr_a)
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual(me["roles"], [{"property": "a", "role": "MANAGER"}])

    def test_dashboard_counts_are_scoped_and_property_local(self):
        today = self.a.local_today()
        make_booking(self.room_a, today, today + timedelta(days=1))            # arrival today
        self.client.force_login(self.rec_a)
        resp = self.client.get("/staff/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.context["rows"]
        self.assertEqual([r["property"].slug for r in rows], ["a"])
        self.assertEqual(rows[0]["arrivals"], 1)
        self.assertIsNone(rows[0]["refunds"])                                  # receptionist: hidden