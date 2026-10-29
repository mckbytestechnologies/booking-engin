import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bookings.tests import make_booking, make_room
from properties.tests import make_property

User = get_user_model()
PW = "Tr1cky-Horse-Battery"


def make_user(email="asha@example.com", **kw):
    return User.objects.create_user(username=email, email=email, password=PW, **kw)


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def register(self, **over):
        data = {"first_name": "Asha", "last_name": "K", "email": "new@example.com",
                "password1": PW, "password2": PW}
        data.update(over)
        return self.client.post("/account/register/", data)

    def code(self):
        return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

    def test_register_sends_code_and_creates_nothing_yet(self):
        self.assertRedirects(self.register(), "/account/register/verify/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())
        self.assertNotIn(PW, str(self.client.session["pending_registration"]))   # hash only

    def test_wrong_code_creates_no_account(self):
        self.register()
        wrong = "000000" if self.code() != "000000" else "111111"
        resp = self.client.post("/account/register/verify/", {"code": wrong})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_correct_code_creates_account_logs_in_and_hashes_password(self):
        self.register()
        resp = self.client.post("/account/register/verify/", {"code": self.code()})
        self.assertRedirects(resp, "/account/")
        user = User.objects.get(email="new@example.com")
        self.assertTrue(user.check_password(PW))
        self.assertNotEqual(user.password, PW)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

    def test_registration_links_only_matching_guest_bookings(self):
        room = make_room(make_property(), "101")
        ci = timezone.localdate() + timedelta(days=5)
        mine = make_booking(room, ci, ci + timedelta(days=2), customer_email="new@example.com")
        other = make_booking(room, ci + timedelta(days=3), ci + timedelta(days=5),
                             customer_email="someone@else.com")
        self.register()
        self.client.post("/account/register/verify/", {"code": self.code()})
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(mine.customer.email, "new@example.com")
        self.assertIsNone(other.customer)

    def test_duplicate_email_rejected(self):
        make_user("new@example.com")
        resp = self.register()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_weak_password_rejected(self):
        resp = self.register(password1="12345678", password2="12345678")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_requests_are_rate_limited(self):
        for i in range(10):
            self.assertEqual(self.register(email=f"u{i}@example.com").status_code, 302)
        self.assertEqual(self.register(email="u99@example.com").status_code, 200)
        self.assertEqual(len(mail.outbox), 10)


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def login(self, email="asha@example.com", password=PW, **extra):
        return self.client.post("/account/login/", {"username": email, "password": password, **extra})

    def test_login_is_case_insensitive_on_email(self):
        self.assertRedirects(self.login("ASHA@Example.COM"), "/account/")

    def test_wrong_password_gives_generic_error(self):
        resp = self.login(password="nope")
        self.assertContains(resp, "Incorrect email or password")
        resp = self.login(email="ghost@example.com")
        self.assertContains(resp, "Incorrect email or password")     # same message: no enumeration

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            self.assertEqual(self.login(password="nope").status_code, 200)
        self.assertEqual(self.login().status_code, 429)               # right password, still locked
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_external_next_url_is_ignored(self):
        resp = self.login(next="https://evil.example/")
        self.assertEqual(resp["Location"], "/account/")

    def test_account_page_requires_login(self):
        resp = self.client.get("/account/")
        self.assertRedirects(resp, "/account/login/?next=/account/", fetch_redirect_response=False)

    def test_account_shows_only_own_bookings(self):
        room = make_room(make_property(), "101")
        ci = timezone.localdate() + timedelta(days=5)
        mine = make_booking(room, ci, ci + timedelta(days=2), customer=self.user)
        other = make_booking(room, ci + timedelta(days=3), ci + timedelta(days=5))
        self.client.force_login(self.user)
        html = self.client.get("/account/").content.decode()
        self.assertIn(mine.reference, html)
        self.assertNotIn(other.reference, html)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/account/logout/").status_code, 405)
        self.assertEqual(self.client.post("/account/logout/").status_code, 302)
        self.assertEqual(self.client.get("/account/").status_code, 302)