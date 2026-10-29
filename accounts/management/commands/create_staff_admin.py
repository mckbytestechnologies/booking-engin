from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or reset the staff admin account (local development)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default="dashboard123")
        parser.add_argument("--email", default="admin@example.com")

    def handle(self, *args, **opts):
        User = get_user_model()
        user = User.objects.filter(username=opts["username"]).first() or User(username=opts["username"])
        user.email = opts["email"]
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(opts["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(
            f"Staff account ready: username={opts['username']} email={opts['email']}"))