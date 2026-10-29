from rest_framework import serializers

from properties.serializers import AmenitySerializer, PropertySummarySerializer

from .models import Room, RoomImage


class RoomImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomImage
        fields = ["image", "caption"]


class RoomSerializer(serializers.ModelSerializer):
    property = PropertySummarySerializer(read_only=True)
    room_type = serializers.CharField(source="room_type.name", read_only=True)
    bed_type = serializers.CharField(source="bed_type.name", read_only=True)
    amenities = AmenitySerializer(many=True, read_only=True)
    images = RoomImageSerializer(many=True, read_only=True)

    class Meta:
        model = Room
        # Explicit list. housekeeping_status / operational_status stay internal.
        fields = [
            "id", "number", "property", "room_type", "description", "floor",
            "max_guests", "base_occupancy", "bed_count", "bed_type",
            "size", "size_unit", "price_per_night", "extra_guest_charge",
            "amenities", "images",
        ]