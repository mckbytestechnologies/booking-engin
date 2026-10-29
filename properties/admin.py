from django.contrib import admin

from .models import Amenity, Property, PropertyImage, StaffAssignment


class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 1


class StaffAssignmentInline(admin.TabularInline):
    model = StaffAssignment
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name", "scope", "is_active")
    list_filter = ("scope", "is_active")
    search_fields = ("name",)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "is_active")
    list_filter = ("is_active", "city")
    search_fields = ("name", "city")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("amenities",)
    inlines = [PropertyImageInline, StaffAssignmentInline]