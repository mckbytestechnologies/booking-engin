from django.core.management.base import BaseCommand

from bookings.services.notifications import retry_pending


class Command(BaseCommand):
    help = "Send pending and failed emails from the outbox."

    def handle(self, *args, **options):
        self.stdout.write(f"Sent {retry_pending()} email(s).")