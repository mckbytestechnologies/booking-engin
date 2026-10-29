from django.views.generic import DetailView

from .models import Room


class RoomDetailView(DetailView):
    template_name = "rooms/room_detail.html"
    context_object_name = "room"

    def get_queryset(self):
        return (
            Room.objects.filter(operational_status=Room.OperationalStatus.ACTIVE, property__is_active=True)
            .select_related("property", "room_type", "bed_type")
            .prefetch_related("amenities", "images")
        )