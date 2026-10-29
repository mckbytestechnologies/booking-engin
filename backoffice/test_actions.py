from datetime import timedelta

from bookings.models import Booking, RefundTask
from bookings.services.lifecycle import cancel_booking
from bookings.test_services import GUEST, key_for
from bookings.tests import make_booking

from .test_access import AccessTestBase


class StaffActionTests(AccessTestBase):
    def post(self, url, data=None):
        return self.client.post(url, data or {}, content_type="application/json")

    def url(self, booking, action):
        return f"/api/v1/staff/bookings/{booking.reference}/{action}/"

    def manual_body(self, **over):
        t = self.a.local_today()
        body = {"property": "a", "source": "WALK_IN", "check_in": str(t),
                "check_out": str(t + timedelta(days=2)),
                "items": [{"key": key_for(self.room_a), "quantity": 1}], **GUEST}
        body.update(over)
        return body

    def test_receptionist_cancels_own_property_booking(self):
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(self.bk_a, "cancel"), {"reason": "Guest called"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()["status"], resp.json()["penalty"]), ("CANCELLED", "0.00"))
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.status, "CANCELLED")

    def test_other_property_cancel_is_404(self):
        self.client.force_login(self.rec_a)
        self.assertEqual(self.post(self.url(self.bk_b, "cancel")).status_code, 404)
        self.bk_b.refresh_from_db()
        self.assertEqual(self.bk_b.status, "CONFIRMED")

    def test_customer_cannot_use_the_staff_cancel(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.post(self.url(self.bk_a, "cancel")).status_code, 403)

    def test_receptionist_cannot_waive_but_manager_can(self):
        t = self.a.local_today()
        late = make_booking(self.room_a, t, t + timedelta(days=2), payment_status="PAID")
        body = {"waive_penalty": True, "reason": "Guest ill"}
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(late, "cancel"), body)
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (403, "not_permitted"))
        self.client.force_login(self.mgr_a)
        resp = self.post(self.url(late, "cancel"), body)
        self.assertEqual((resp.status_code, resp.json()["penalty"]), (200, "0.00"))

    def test_manual_booking_uses_server_price_and_records_staff(self):
        self.client.force_login(self.rec_a)
        resp = self.post("/api/v1/staff/manual-bookings/", self.manual_body(total="1.00"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["bookings"][0]["total"], "5000.00")     # forged total ignored
        b = Booking.objects.get(reference=resp.json()["bookings"][0]["reference"])
        self.assertEqual((b.status, b.payment_status, b.source, b.created_by),
                         ("CONFIRMED", "UNPAID", "WALK_IN", self.rec_a))

    def test_manual_booking_for_unassigned_property_is_404(self):
        self.client.force_login(self.rec_a)
        resp = self.post("/api/v1/staff/manual-bookings/", self.manual_body(property="b"))
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (404, "unknown_property"))

    def test_customer_cannot_create_manual_bookings(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.post("/api/v1/staff/manual-bookings/", self.manual_body()).status_code, 403)

    def test_manual_booking_validates_guest_details(self):
        self.client.force_login(self.rec_a)
        resp = self.post("/api/v1/staff/manual-bookings/", self.manual_body(phone="12"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("phone", resp.json())

    def test_mark_paid_only_for_staff_created_bookings(self):
        t = self.a.local_today()
        desk = make_booking(self.room_a, t + timedelta(days=30), t + timedelta(days=32), source="WALK_IN")
        self.client.force_login(self.rec_a)
        resp = self.post(self.url(desk, "mark-paid"), {"method": "UPI"})
        self.assertEqual((resp.status_code, resp.json()["payment_status"]), (200, "PAID"))
        self.assertEqual(self.post(self.url(self.bk_a, "mark-paid"), {"method": "UPI"}).status_code, 409)

    def _refund_tasks(self):
        pa = make_booking(self.room_a, self.d + timedelta(days=5), self.d + timedelta(days=7), payment_status="PAID")
        pb = make_booking(self.room_b, self.d + timedelta(days=5), self.d + timedelta(days=7), payment_status="PAID")
        cancel_booking(pa.pk, actor=self.boss)
        cancel_booking(pb.pk, actor=self.boss)
        return RefundTask.objects.get(booking=pa), RefundTask.objects.get(booking=pb)

    def test_refund_tasks_are_scoped_to_managers_of_that_property(self):
        task_a, _ = self._refund_tasks()
        self.client.force_login(self.mgr_a)
        rows = self.client.get("/api/v1/staff/refund-tasks/").json()["results"]
        self.assertEqual([r["id"] for r in rows], [task_a.id])
        self.client.force_login(self.rec_a)
        self.assertEqual(self.client.get("/api/v1/staff/refund-tasks/").status_code, 403)

    def test_refund_task_completion(self):
        task_a, task_b = self._refund_tasks()
        url = "/api/v1/staff/refund-tasks/{}/complete/"
        self.client.force_login(self.rec_a)
        self.assertEqual(self.post(url.format(task_a.id)).status_code, 403)
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.post(url.format(task_b.id)).status_code, 404)     # other property
        self.assertEqual(self.post(url.format(task_a.id)).status_code, 200)
        self.assertEqual(self.post(url.format(task_a.id)).status_code, 409)     # only once