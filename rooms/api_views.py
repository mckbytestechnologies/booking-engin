# rooms/api_views.py
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from .filters import RoomFilter
from .models import Room
from .serializers import RoomSerializer


class RoomViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = RoomSerializer
    filterset_class = RoomFilter
    search_fields = ["number", "description", "property__name"]
    ordering_fields = ["price_per_night", "max_guests", "number"]
    ordering = ["property__name", "number"]

    def get_queryset(self):
        return (
            Room.objects.filter(
                operational_status=Room.OperationalStatus.ACTIVE,
                property__is_active=True,
            )
            .select_related("property", "room_type", "bed_type")
            .prefetch_related("amenities", "images")
            .distinct()
        )