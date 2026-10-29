from django.core.management.base import BaseCommand

from bookings.services import maintenance


class Command(BaseCommand):
    help = "Expire stale holds, mark no-shows, delete old OTP codes. Safe to run repeatedly."

    def handle(self, *args, **options):
        e = maintenance.expire_holds()
        n = maintenance.auto_no_shows()
        o = maintenance.cleanup_otps()
        self.stdout.write(f"expired_holds={e} no_shows={n} otp_deleted={o}")