from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Contact", {"fields": ("phone",)}),)
    list_display = ("username", "email", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")