import re
from datetime import timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdTests(TestCase):
    def test_every_response_has_a_request_id(self):
        resp = self.client.get(reverse("home"))
        self.assertRegex(resp["X-Request-ID"], RID)

    def test_a_valid_incoming_id_is_kept(self):
        resp = self.client.get(reverse("home"), HTTP_X_REQUEST_ID="trace-abc12345")
        self.assertEqual(resp["X-Request-ID"], "trace-abc12345")

    def test_a_bad_incoming_id_is_replaced(self):
        resp = self.client.get(reverse("home"), HTTP_X_REQUEST_ID="bad id with spaces")
        self.assertNotEqual(resp["X-Request-ID"], "bad id with spaces")
        self.assertRegex(resp["X-Request-ID"], RID)

    def test_request_is_logged_with_path_and_status(self):
        path = reverse("home")
        with self.assertLogs("app.request", level="INFO") as cm:
            self.client.get(path)
        self.assertIn(f"GET {path} 200 ", cm.output[0])


class ApiErrorTests(TestCase):
    def availability_url(self):
        today = timezone.localdate()
        return (reverse("booking_availability")
                + f"?check_in={today + timedelta(days=5)}&check_out={today + timedelta(days=7)}")

    def test_unhandled_error_becomes_a_safe_json_500(self):
        with mock.patch("bookings.api.availability_groups", side_effect=RuntimeError("secret boom")):
            with self.assertLogs("config.api_errors", level="ERROR"):
                resp = self.client.get(self.availability_url())
        self.assertEqual(resp.status_code, 500)
        err = resp.json()["error"]
        self.assertEqual(err["code"], "server_error")
        self.assertEqual(err["request_id"], resp["X-Request-ID"])
        self.assertNotIn("secret boom", resp.content.decode())

    def test_permission_error_uses_the_standard_shape(self):
        resp = self.client.get(reverse("api_me"))
        self.assertIn(resp.status_code, (401, 403))
        err = resp.json()["error"]
        self.assertIn(err["code"], ("not_authenticated", "permission_denied"))
        self.assertEqual(err["request_id"], resp["X-Request-ID"])

    def test_validation_errors_keep_their_shape_by_default(self):
        resp = self.client.get(reverse("booking_availability"))
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("error", resp.json())

    @override_settings(API_WRAP_VALIDATION=True)
    def test_validation_errors_can_be_wrapped(self):
        resp = self.client.get(reverse("booking_availability"))
        err = resp.json()["error"]
        self.assertEqual(err["code"], "validation_error")
        self.assertIn("check_in", err["fields"])


class HtmlErrorPageTests(TestCase):
    def test_404_page_is_friendly(self):
        resp = self.client.get("/definitely-not-a-page/")
        self.assertContains(resp, "Page not found", status_code=404)

    def test_500_page_shows_the_request_id_and_no_details(self):
        client = Client(raise_request_exception=False)
        with mock.patch("bookings.views.availability_groups", side_effect=RuntimeError("boom")):
            with self.assertLogs("django.request", level="ERROR"):
                resp = client.get(reverse("booking_engine"))
        self.assertEqual(resp.status_code, 500)
        self.assertContains(resp, resp["X-Request-ID"], status_code=500)
        self.assertNotContains(resp, "boom", status_code=500)