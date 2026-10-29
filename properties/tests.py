from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Property, StaffAssignment
from accounts.models import User


def make_property(**kw):
    defaults = dict(
        name="Sea View", slug="sea-view", address_line="1 Beach Rd", city="Chennai",
        state="Tamil Nadu", phone="9999999999", email="sv@example.com",
    )
    defaults.update(kw)
    return Property.objects.create(**defaults)


class PropertyTests(TestCase):
    def test_invalid_timezone_rejected(self):
        prop = make_property(timezone="Mars/Olympus")
        with self.assertRaises(ValidationError):
            prop.full_clean()

    def test_tax_percent_over_100_blocked_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_property(slug="x", tax_percent=150)

    def test_staff_assignment_unique_per_property(self):
        user = User.objects.create_user("rec", "rec@example.com", "pw-Str0ng-Pass!")
        prop = make_property()
        StaffAssignment.objects.create(user=user, property=prop, role="RECEPTIONIST")
        with self.assertRaises(IntegrityError), transaction.atomic():
            StaffAssignment.objects.create(user=user, property=prop, role="MANAGER")


class UserTests(TestCase):
    def test_email_normalised_and_unique(self):
        User.objects.create_user("a", "Guest@Example.com", "pw-Str0ng-Pass!")
        self.assertTrue(User.objects.filter(email="guest@example.com").exists())
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("b", "guest@example.com", "pw-Str0ng-Pass!")