from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.test_auth import make_user
from bookings.models import RoomBlock
from bookings.tests import make_booking, make_room
from properties.models import Amenity, StaffAssignment
from properties.tests import make_property
from rooms.models import RoomType

DAY = timedelta(days=1)
User = get_user_model()


class CatalogBase(TestCase):
    def setUp(self):
        self.prop = make_property()
        self.room = make_room(self.prop, "101")
        self.today = self.prop.local_today()
        self.root = make_user("root@example.com")
        self.root.is_superuser = True
        self.root.save()
        self.mgr = self.staff("mgr@example.com", "MANAGER")
        self.rec = self.staff("rec@example.com", "RECEPTIONIST")

    def staff(self, email, role):
        user = make_user(email)
        StaffAssignment.objects.create(user=user, property=self.prop, role=role)
        return user


class CatalogueTests(CatalogBase):
    amenity = {"name": "Wi-Fi", "scope": "BOTH", "icon": "", "is_active": "on"}

    def test_receptionist_cannot_open_the_catalogue(self):
        self.client.force_login(self.rec)
        self.assertEqual(self.client.get(reverse("staff_amenities")).status_code, 403)

    def test_manager_can_add_an_amenity(self):
        self.client.force_login(self.mgr)
        resp = self.client.post(reverse("staff_amenity_new"), self.amenity)
        self.assertRedirects(resp, reverse("staff_amenities"))
        self.assertTrue(Amenity.objects.filter(name="Wi-Fi").exists())

    def test_duplicate_name_is_refused_case_insensitively(self):
        Amenity.objects.create(name="Wi-Fi")
        self.client.force_login(self.mgr)
        resp = self.client.post(reverse("staff_amenity_new"), {**self.amenity, "name": "wi-fi"})
        self.assertContains(resp, "already exists")
        self.assertEqual(Amenity.objects.count(), 1)

    def test_only_a_superuser_can_delete(self):
        a = Amenity.objects.create(name="Parking")
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.post(reverse("staff_amenity_delete", args=[a.pk])).status_code, 403)
        self.assertTrue(Amenity.objects.filter(pk=a.pk).exists())
        self.client.force_login(self.root)
        self.client.post(reverse("staff_amenity_delete", args=[a.pk]))
        self.assertFalse(Amenity.objects.filter(pk=a.pk).exists())

    def test_a_room_type_in_use_cannot_be_deleted(self):
        self.client.force_login(self.root)
        resp = self.client.post(reverse("staff_roomtype_delete", args=[self.room.room_type.pk]), follow=True)
        self.assertContains(resp, "still in use")
        self.assertTrue(RoomType.objects.filter(pk=self.room.room_type.pk).exists())


class TeamTests(CatalogBase):
    def form(self, **extra):
        return {"email": "new@example.com", "first_name": "Nina", "last_name": "Shah",
                "password": "Str0ng-Passw0rd-92", "property": self.prop.pk,
                "role": "RECEPTIONIST", **extra}

    def test_team_page_is_superuser_only(self):
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("staff_team")).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse("staff_team")).status_code, 200)

    def test_superuser_adds_a_new_staff_member_without_admin_access(self):
        self.client.force_login(self.root)
        resp = self.client.post(reverse("staff_team_new"), self.form())
        self.assertRedirects(resp, reverse("staff_team"))
        user = User.objects.get(email="new@example.com")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("Str0ng-Passw0rd-92"))
        self.assertEqual(StaffAssignment.objects.get(user=user).role, "RECEPTIONIST")

    def test_a_new_account_needs_a_password(self):
        self.client.force_login(self.root)
        resp = self.client.post(reverse("staff_team_new"), self.form(password=""))
        self.assertContains(resp, "password is required")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())


class RoomBlockTests(CatalogBase):
    def form(self, start, end):
        return {"room": self.room.pk, "start_date": str(start), "end_date": str(end), "reason": "Repairs"}

    def test_manager_can_block_a_free_room(self):
        self.client.force_login(self.mgr)
        resp = self.client.post(reverse("staff_block_new"),
                                self.form(self.today + 20 * DAY, self.today + 22 * DAY))
        self.assertRedirects(resp, reverse("staff_blocks"))
        self.assertEqual(RoomBlock.objects.get().created_by, self.mgr)

    def test_blocking_over_a_booking_is_refused(self):
        b = make_booking(self.room, self.today + 5 * DAY, self.today + 8 * DAY)
        self.client.force_login(self.mgr)
        resp = self.client.post(reverse("staff_block_new"),
                                self.form(self.today + 6 * DAY, self.today + 7 * DAY))
        self.assertContains(resp, b.reference)
        self.assertEqual(RoomBlock.objects.count(), 0)

    def test_receptionist_cannot_block_rooms(self):
        self.client.force_login(self.rec)
        self.assertEqual(self.client.get(reverse("staff_block_new")).status_code, 403)