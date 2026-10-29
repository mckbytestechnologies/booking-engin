import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from properties.tests import make_property

from .models import Booking, Payment
from .test_services import GUEST, key_for
from .tests import make_booking, make_room

SECRET, WH = "s3cr3t-value", "whsec-value"


def sign(order, pay, secret=SECRET):
    return hmac.new(secret.encode(), f"{order}|{pay}".encode(), hashlib.sha256).hexdigest()


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET=SECRET,
                   RAZORPAY_WEBHOOK_SECRET=WH, BOOKING_REQUIRE_EMAIL_VERIFICATION=False)
class PaymentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room = make_room(make_property(), "101")
        self.ci = timezone.localdate() + timedelta(days=5)
        self.co = self.ci + timedelta(days=2)
        body = {"check_in": str(self.ci), "check_out": str(self.co),
                "items": [{"key": key_for(self.room), "quantity": 1}], **GUEST}
        self.group = self.post("/api/v1/holds/", body).json()["group_ref"]
        patcher = patch("bookings.services.razorpay_client.create_order", return_value={"id": "order_T1"})
        self.create = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")

    def order(self):
        return self.post("/api/v1/payments/orders/", {"group_ref": self.group})

    def verify(self, order="order_T1", pay="pay_T1", sig=None):
        return self.post("/api/v1/payments/verify/", {
            "razorpay_order_id": order, "razorpay_payment_id": pay,
            "razorpay_signature": sig or sign(order, pay)})

    def webhook(self, event, amount=500000, sig=None, order="order_T1", pay="pay_T1"):
        raw = json.dumps({"event": event, "payload": {"payment": {"entity": {
            "id": pay, "order_id": order, "amount": amount}}}}).encode()
        sig = sig or hmac.new(WH.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post("/api/v1/payments/webhook/", raw, content_type="application/json",
                                HTTP_X_RAZORPAY_SIGNATURE=sig)

    def statuses(self):
        return set(Booking.objects.values_list("status", flat=True))

    def test_amount_is_server_calculated_and_secret_never_sent(self):
        resp = self.order()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["amount"], 500000)              # 2 nights x 2500 in paise
        self.assertEqual(self.create.call_args.args[0], 500000)
        self.assertNotIn(SECRET, resp.content.decode())

    def test_order_for_someone_elses_group_is_404(self):
        self.client.cookies.clear()
        self.assertEqual(self.order().status_code, 404)

    def test_repeated_order_requests_reuse_one_order(self):
        self.order(); self.order()
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual(Payment.objects.count(), 1)

    @override_settings(RAZORPAY_KEY_ID="")
    def test_unconfigured_payments_return_503(self):
        self.assertEqual(self.order().status_code, 503)

    def test_order_after_hold_expiry_is_409(self):
        Booking.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        resp = self.order()
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "hold_expired"))

    def test_bad_signature_does_not_confirm(self):
        self.order()
        self.assertEqual(self.verify(sig="0" * 64).status_code, 400)
        self.assertEqual(self.statuses(), {"PENDING"})

    def test_valid_signature_confirms_the_booking(self):
        self.order()
        self.assertEqual(self.verify().status_code, 200)
        b = Booking.objects.get()
        self.assertEqual((b.status, b.payment_status, b.expires_at), ("CONFIRMED", "PAID", None))
        self.assertEqual(Payment.objects.get().status, "PAID")

    def test_verify_twice_is_idempotent(self):
        self.order()
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(Payment.objects.filter(status="PAID").count(), 1)

    def test_webhook_rejects_bad_signature(self):
        self.order()
        self.assertEqual(self.webhook("payment.captured", sig="bad").status_code, 400)
        self.assertEqual(self.statuses(), {"PENDING"})

    def test_webhook_confirms_and_replays_safely(self):
        self.order()
        self.assertEqual(self.webhook("payment.captured").status_code, 200)
        self.assertEqual(self.webhook("payment.captured").status_code, 200)
        self.assertEqual(self.statuses(), {"CONFIRMED"})

    def test_webhook_amount_mismatch_does_not_confirm(self):
        self.order()
        self.assertEqual(self.webhook("payment.captured", amount=100).status_code, 200)
        self.assertEqual(self.statuses(), {"PENDING"})

    def test_payment_failed_webhook_marks_failed_but_keeps_the_hold(self):
        self.order()
        self.webhook("payment.failed")
        self.assertEqual(Payment.objects.get().status, "FAILED")
        self.assertEqual(self.statuses(), {"PENDING"})

    def test_late_payment_is_confirmed_if_rooms_are_still_free(self):
        self.order()
        Booking.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.statuses(), {"CONFIRMED"})

    def test_late_payment_for_a_taken_room_needs_a_refund(self):
        self.order()
        Booking.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        make_booking(self.room, self.ci, self.co)                    # someone else got the room
        resp = self.verify()
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "payment_conflict"))
        self.assertEqual(Payment.objects.get().status, "REFUND_REQUIRED")
        self.assertIn("EXPIRED", self.statuses())