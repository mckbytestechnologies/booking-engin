import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from properties.models import Property, StaffAssignment

User = get_user_model()


class Command(BaseCommand):
    help = "Create (or update) a staff account and assign it to a property."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--property", required=True, help="Property slug")
        parser.add_argument("--role", choices=["MANAGER", "RECEPTIONIST"], default="RECEPTIONIST")
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument("--password", help="Omit this to be prompted (safer: not saved in shell history)")

    def handle(self, *args, **o):
        email = o["email"].strip().lower()
        try:
            prop = Property.objects.get(slug=o["property"])
        except Property.DoesNotExist:
            raise CommandError(f"No property with slug '{o['property']}'.")

        password = o["password"]
        if not password:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("Passwords do not match.")
        user = User.objects.filter(email__iexact=email).first()
        try:
            validate_password(password, user or User(username=email, email=email))
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))

        if user is None:
            user = User.objects.create_user(username=email, email=email, password=password,
                                            first_name=o["first_name"], last_name=o["last_name"])
            action = "Created"
        else:
            user.set_password(password)
            user.save()
            action = "Updated"
        StaffAssignment.objects.update_or_create(user=user, property=prop, defaults={"role": o["role"]})
        self.stdout.write(f"{action} {email} as {o['role']} at {prop.name}.")