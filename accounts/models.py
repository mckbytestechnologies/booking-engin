from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Customers, staff, and admins are all Users.

    Role is determined by is_superuser and StaffAssignment rows, never by a
    free-form field a client could tamper with.
    """

    email = models.EmailField("email address", unique=True)
    phone = models.CharField(max_length=20, blank=True)

    def save(self, *args, **kwargs):
        # Normalise so "A@x.com" and "a@x.com" can't be two accounts.
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username