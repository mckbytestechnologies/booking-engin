from django.contrib import admin

from .models import BedType, Room, RoomImage, RoomType


class RoomImageInline(admin.TabularInline):
    model = RoomImage
    extra = 1


admin.site.register(RoomType)
admin.site.register(BedType)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("number", "property", "room_type", "price_per_night", "max_guests", "operational_status")
    list_filter = ("property", "room_type", "operational_status", "housekeeping_status")
    search_fields = ("number", "property__name")
    filter_horizontal = ("amenities",)
    inlines = [RoomImageInline]