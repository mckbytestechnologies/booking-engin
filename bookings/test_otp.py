import re
from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from properties.tests import make_property

from .models import EmailOTP
from .test_services import GUEST, key_for
from .tests import make_room

EMAIL = "a@example.com"


class OtpApiTests(TestCase):
    def setUp(self):
        cache.clear()                                              # reset DRF throttle counters

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")

    def send(self, email=EMAIL):
        resp = self.post("/api/v1/otp/send/", {"email": email})
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1) if resp.status_code == 200 else None
        return resp, code

    def test_send_stores_only_a_hash_and_emails_the_code(self):
        resp, code = self.send()
        self.assertEqual(resp.status_code, 200)
        otp = EmailOTP.objects.get()
        self.assertNotIn(code, otp.code_hash)
        self.assertEqual(len(otp.code_hash), 64)
        self.assertEqual(mail.outbox[0].to, [EMAIL])

    def test_resend_within_a_minute_is_throttled(self):
        self.send()
        resp, _ = self.send()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["error"]["code"], "otp_throttled")
        self.assertEqual(len(mail.outbox), 1)

    def test_correct_code_verifies_and_marks_the_session(self):
        _, code = self.send()
        resp = self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": code})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session["verified_email"], EMAIL)

    def test_email_is_case_insensitive(self):
        _, code = self.send("A@Example.com")
        resp = self.post("/api/v1/otp/verify/", {"email": "a@EXAMPLE.com", "otp": code})
        self.assertEqual(resp.status_code, 200)

    def test_wrong_code_is_rejected_and_attempts_persist(self):
        _, code = self.send()
        wrong = "000000" if code != "000000" else "111111"
        resp = self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": wrong})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(EmailOTP.objects.get().attempts, 1)       # survived the failed request
        self.assertNotIn("verified_email", self.client.session)

    def test_five_wrong_guesses_lock_the_code_even_for_the_right_one(self):
        _, code = self.send()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": wrong})
        resp = self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": code})
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("verified_email", self.client.session)

    def test_expired_code_rejected(self):
        _, code = self.send()
        EmailOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        resp = self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": code})
        self.assertEqual(resp.status_code, 400)

    def test_code_is_single_use(self):
        _, code = self.send()
        self.assertEqual(self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": code}).status_code, 200)
        self.assertEqual(self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": code}).status_code, 400)

    def test_new_code_invalidates_the_old_one(self):
        _, old = self.send()
        EmailOTP.objects.update(created_at=timezone.now() - timedelta(minutes=2))   # skip cooldown
        _, new = self.send()
        if old != new:
            self.assertEqual(self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": old}).status_code, 400)

    def test_malformed_input_is_400(self):
        self.assertEqual(self.post("/api/v1/otp/send/", {"email": "nope"}).status_code, 400)
        self.assertEqual(self.post("/api/v1/otp/verify/", {"email": EMAIL, "otp": "12ab"}).status_code, 400)


@override_settings(BOOKING_REQUIRE_EMAIL_VERIFICATION=True)
class HoldGateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room = make_room(make_property(), "101")
        ci = timezone.localdate() + timedelta(days=5)
        self.body = {"check_in": str(ci), "check_out": str(ci + timedelta(days=2)),
                     "items": [{"key": key_for(self.room), "quantity": 1}], **GUEST}

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")

    def test_hold_refused_until_email_is_verified(self):
        resp = self.post("/api/v1/holds/", self.body)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "email_not_verified")

    def test_hold_allowed_after_verification(self):
        self.post("/api/v1/otp/send/", {"email": GUEST["email"]})
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        self.post("/api/v1/otp/verify/", {"email": GUEST["email"], "otp": code})
        self.assertEqual(self.post("/api/v1/holds/", self.body).status_code, 201)

    def test_verifying_one_email_does_not_unlock_another(self):
        self.post("/api/v1/otp/send/", {"email": "other@example.com"})
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        self.post("/api/v1/otp/verify/", {"email": "other@example.com", "otp": code})
        self.assertEqual(self.post("/api/v1/holds/", self.body).status_code, 403)