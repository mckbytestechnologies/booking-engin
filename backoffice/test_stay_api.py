from datetime import timedelta

from bookings.models import Booking
from bookings.services.lifecycle import cancel_booking
from bookings.services.stay import request_extension
from bookings.tests import make_booking
from rooms.models import Room

from .test_access import AccessTestBase

DAY = timedelta(days=1)


class StaffStayApiTests(AccessTestBase):
    def post(self, url, data=None):
        return self.client.post(url, data or {}, content_type="application/json")

    def url(self, booking, action):
        return f"/api/v1/staff/bookings/{booking.reference}/{action}/"

    def test_check_in(self):
        t = self.a.local_today()
        b = make_booking(self.room_a, t, t + 2 * DAY)
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(b, "check-in"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()["status"], resp.json()["housekeeping_warning"]), ("CHECKED_IN", False))

    def test_other_property_is_404_and_customers_are_403(self):
        t = self.a.local_today()
        b = make_booking(self.room_b, t, t + 2 * DAY)
        self.client.force_login(self.rec_a)
        self.assertEqual(self.post(self.url(b, "check-in")).status_code, 404)
        self.client.force_login(self.customer)
        self.assertEqual(self.post(self.url(b, "check-in")).status_code, 403)

    def test_checkout_blocked_until_paid_then_room_is_dirty(self):
        t = self.a.local_today()
        b = make_booking(self.room_a, t - DAY, t + DAY, status="CHECKED_IN")
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(b, "check-out"))
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "payment_outstanding"))
        Booking.objects.filter(pk=b.pk).update(payment_status="PAID")
        resp = self.post(self.url(b, "check-out"))
        self.assertEqual((resp.status_code, resp.json()["status"]), (200, "CHECKED_OUT"))
        self.room_a.refresh_from_db()
        self.assertEqual(self.room_a.housekeeping_status, "DIRTY")

    def test_no_show(self):
        t = self.a.local_today()
        b = make_booking(self.room_a, t - DAY, t + DAY, payment_status="PAID")
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(b, "no-show"))
        self.assertEqual((resp.status_code, resp.json()["penalty"], resp.json()["refund_due"]),
                         (200, "2500.00", "5000.00"))

    def test_staff_extend_and_balance(self):
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(self.bk_a, "extend"), {"new_check_out": str(self.d + 4 * DAY)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()["total"], resp.json()["balance_due"]), ("12500.00", "12500.00"))

    def test_extension_decisions_are_scoped(self):
        ext = request_extension(self.bk_a.pk, actor=self.rec_a, new_check_out=self.d + 4 * DAY)
        approve = f"/api/v1/staff/extensions/{ext.id}/approve/"
        self.client.force_login(self.rec_b)
        self.assertEqual(self.post(approve).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/staff/extensions/").json()["count"], 0)
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get("/api/v1/staff/extensions/").json()["count"], 1)
        self.assertEqual(self.post(approve).status_code, 200)
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.check_out, self.d + 4 * DAY)

    def test_reject_extension(self):
        ext = request_extension(self.bk_a.pk, actor=self.rec_a, new_check_out=self.d + 4 * DAY)
        self.client.force_login(self.rec_a)
        resp = self.post(f"/api/v1/staff/extensions/{ext.id}/reject/", {"note": "Full"})
        self.assertEqual((resp.status_code, resp.json()["status"]), (200, "REJECTED"))

    def test_housekeeping(self):
        url = "/api/v1/staff/rooms/{}/housekeeping/"
        self.client.force_login(self.rec_a)
        self.assertEqual(self.post(url.format(self.room_a.pk), {"status": "DIRTY"}).status_code, 200)
        self.room_a.refresh_from_db()
        self.assertEqual(self.room_a.housekeeping_status, "DIRTY")
        self.assertEqual(self.post(url.format(self.room_b.pk), {"status": "CLEAN"}).status_code, 404)
        self.assertEqual(self.post(url.format(self.room_a.pk), {"status": "BOGUS"}).status_code, 400)
        self.client.force_login(self.customer)
        self.assertEqual(self.post(url.format(self.room_a.pk), {"status": "CLEAN"}).status_code, 403)

    def test_history_endpoint_is_scoped(self):
        cancel_booking(self.bk_a.pk, actor=self.boss)
        self.client.force_login(self.rec_a)
        rows = self.client.get(f"/api/v1/staff/bookings/{self.bk_a.reference}/history/").json()
        self.assertEqual(rows[-1]["to_status"], "CANCELLED")
        self.client.force_login(self.rec_b)
        self.assertEqual(self.client.get(f"/api/v1/staff/bookings/{self.bk_a.reference}/history/").status_code, 404)

    def test_detail_shows_balance_and_actual_times(self):
        self.client.force_login(self.rec_a)
        data = self.client.get(f"/api/v1/staff/bookings/{self.bk_a.reference}/").json()
        self.assertEqual((data["balance_due"], data["actual_check_in"]), ("7500.00", None))