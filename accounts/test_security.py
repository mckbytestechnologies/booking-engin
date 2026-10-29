import io
import re
import tempfile
import time
from datetime import timedelta
from importlib import import_module

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone
from PIL import Image

from backoffice.test_access import PW, AccessTestBase, make_user
from bookings.test_services import GUEST, key_for
from bookings.tests import make_room
from config.net import client_ip
from properties.tests import make_property
from rooms.models import RoomImage


class CsrfTests(AccessTestBase):
    def test_staff_page_action_needs_a_csrf_token(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.rec_a)
        self.assertEqual(c.post(f"/staff/bookings/{self.bk_a.reference}/cancel/").status_code, 403)
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.status, "CONFIRMED")

    def test_staff_api_action_needs_csrf_for_session_users(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.rec_a)
        resp = c.post(f"/api/v1/staff/bookings/{self.bk_a.reference}/cancel/", {}, content_type="application/json")
        self.assertEqual(resp.status_code, 403)
        self.bk_a.refresh_from_db()
        self.assertEqual(self.bk_a.status, "CONFIRMED")


class ClientIpTests(TestCase):
    def req(self):
        return RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 1.2.3.4")

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_no_proxy_ignores_the_forwarded_header(self):
        self.assertEqual(client_ip(self.req()), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_one_proxy_trusts_only_its_own_entry_not_the_forged_one(self):
        self.assertEqual(client_ip(self.req()), "1.2.3.4")

    @override_settings(TRUSTED_PROXY_COUNT=3)
    def test_too_few_entries_falls_back_to_the_socket_address(self):
        self.assertEqual(client_ip(self.req()), "10.0.0.1")


@override_settings(BOOKING_REQUIRE_EMAIL_VERIFICATION=True)
class VerifiedWindowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room = make_room(make_property(), "101")
        ci = timezone.localdate() + timedelta(days=5)
        self.body = {"check_in": str(ci), "check_out": str(ci + timedelta(days=2)),
                     "items": [{"key": key_for(self.room), "quantity": 1}], **GUEST}

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")

    def verify(self):
        self.post("/api/v1/otp/send/", {"email": GUEST["email"]})
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        self.assertEqual(self.post("/api/v1/otp/verify/", {"email": GUEST["email"], "otp": code}).status_code, 200)

    def test_fresh_verification_allows_exactly_one_hold(self):
        self.verify()
        self.assertEqual(self.post("/api/v1/holds/", self.body).status_code, 201)
        self.assertEqual(self.post("/api/v1/holds/", self.body).status_code, 403)

    def test_stale_verification_is_refused(self):
        self.verify()
        s = self.client.session
        s["verified_at"] = time.time() - 3600
        s.save()
        resp = self.post("/api/v1/holds/", self.body)
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (403, "email_not_verified"))

    def test_session_without_a_timestamp_is_refused(self):
        s = self.client.session
        s["verified_email"] = GUEST["email"]
        s.save()
        self.assertEqual(self.post("/api/v1/holds/", self.body).status_code, 403)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadHardeningTests(AccessTestBase):
    def upload(self, fmt, name, mime):
        buf = io.BytesIO()
        Image.new("RGB", (5, 5), "red").save(buf, fmt)
        self.client.force_login(self.mgr_a)
        self.client.post(f"/staff/rooms/{self.room_a.pk}/images/add/",
                         {"image": SimpleUploadedFile(name, buf.getvalue(), content_type=mime),
                          "caption": "", "sort_order": 0})

    def test_gif_is_rejected(self):
        self.upload("GIF", "a.gif", "image/gif")
        self.assertEqual(RoomImage.objects.count(), 0)

    def test_png_is_accepted(self):
        self.upload("PNG", "a.png", "image/png")
        self.assertEqual(RoomImage.objects.count(), 1)


class AuditLogTests(TestCase):
    def setUp(self):
        cache.clear()
        make_user("asha@example.com")

    def test_failed_login_is_logged_without_the_email(self):
        with self.assertLogs("app.audit", level="WARNING") as cm:
            self.client.post("/account/login/", {"username": "asha@example.com", "password": "wrong"})
        out = "\n".join(cm.output)
        self.assertIn("login failed", out)
        self.assertNotIn("asha@example.com", out)

    def test_successful_login_is_logged(self):
        with self.assertLogs("app.audit", level="INFO") as cm:
            self.client.post("/account/login/", {"username": "asha@example.com", "password": PW})
        self.assertIn("login ok", "\n".join(cm.output))


class PasswordResetTests(TestCase):
    NEW = "N3w-Horse-Battery-Staple"

    def setUp(self):
        cache.clear()
        self.user = make_user("asha@example.com")

    def ask(self, email):
        return self.client.post("/account/password-reset/", {"email": email})

    def test_known_email_gets_a_link(self):
        self.assertRedirects(self.ask("asha@example.com"), "/account/password-reset/done/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/account/reset/", mail.outbox[0].body)

    def test_unknown_email_looks_identical_and_sends_nothing(self):
        self.assertRedirects(self.ask("ghost@example.com"), "/account/password-reset/done/")
        self.assertEqual(len(mail.outbox), 0)

    def test_link_changes_the_password_and_works_once(self):
        self.ask("asha@example.com")
        path = re.search(r"http://testserver(/account/reset/\S+)", mail.outbox[0].body).group(1)
        set_url = self.client.get(path)["Location"]
        self.client.get(set_url)
        resp = self.client.post(set_url, {"new_password1": self.NEW, "new_password2": self.NEW})
        self.assertRedirects(resp, "/account/reset/done/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))
        self.assertContains(Client().get(path, follow=True), "no longer valid")

    def test_reset_requests_are_rate_limited(self):
        for _ in range(7):
            self.assertEqual(self.ask("asha@example.com").status_code, 302)
        self.assertEqual(len(mail.outbox), 5)


class ProdSettingsTests(TestCase):
    def test_production_settings_are_locked_down(self):
        prod = import_module("config.settings.prod")
        self.assertFalse(prod.DEBUG)
        self.assertTrue(prod.SECURE_SSL_REDIRECT)
        self.assertTrue(prod.SESSION_COOKIE_SECURE)
        self.assertTrue(prod.CSRF_COOKIE_SECURE)
        self.assertEqual(prod.X_FRAME_OPTIONS, "DENY")
        self.assertGreater(prod.SECURE_HSTS_SECONDS, 0)