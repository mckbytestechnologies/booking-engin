from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from .models import Booking, EmailOTP
from .services.maintenance import auto_no_shows, cleanup_otps, expire_holds
from .test_lifecycle import LifecycleBase
from .tests import make_booking

DAY = timedelta(days=1)


class MaintenanceTests(LifecycleBase):
    def test_expired_hold_becomes_expired_with_history(self):
        b = make_booking(self.room, self.today + 5 * DAY, self.today + 7 * DAY, status="PENDING",
                         expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(expire_holds(), 1)
        b.refresh_from_db()
        self.assertEqual(b.status, "EXPIRED")
        self.assertEqual(b.history.get(to_status="EXPIRED").actor_label, "system")

    def test_live_holds_and_confirmed_bookings_are_untouched(self):
        live = make_booking(self.room, self.today + 5 * DAY, self.today + 7 * DAY, status="PENDING",
                            expires_at=timezone.now() + timedelta(minutes=10))
        make_booking(self.room, self.today + 10 * DAY, self.today + 12 * DAY)
        self.assertEqual(expire_holds(), 0)
        live.refresh_from_db()
        self.assertEqual(live.status, "PENDING")

    def test_jobs_are_idempotent(self):
        make_booking(self.room, self.today - DAY, self.today + 2 * DAY)
        self.assertEqual(auto_no_shows(), 1)
        self.assertEqual(auto_no_shows(), 0)

    def test_no_show_only_after_arrival_day_ends(self):
        past = make_booking(self.room, self.today - DAY, self.today + DAY)
        make_booking(self.room, self.today + 3 * DAY, self.today + 5 * DAY)
        make_booking(self.room, self.today + DAY * 10, self.today + DAY * 12, status="CHECKED_IN")
        self.assertEqual(auto_no_shows(), 1)
        past.refresh_from_db()
        self.assertEqual(past.status, "NO_SHOW")
        self.assertEqual(Booking.objects.filter(status="NO_SHOW").count(), 1)

    def test_old_otps_are_deleted(self):
        old = EmailOTP.objects.create(email="a@example.com", code_hash="x" * 64, expires_at=timezone.now())
        EmailOTP.objects.filter(pk=old.pk).update(created_at=timezone.now() - 2 * DAY)
        EmailOTP.objects.create(email="b@example.com", code_hash="y" * 64, expires_at=timezone.now())
        self.assertEqual(cleanup_otps(), 1)
        self.assertEqual(EmailOTP.objects.count(), 1)

    def test_command_runs_and_reports(self):
        out = StringIO()
        call_command("run_maintenance", stdout=out)
        self.assertIn("expired_holds=0", out.getvalue())