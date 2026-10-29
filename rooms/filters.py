# rooms/filters.py
import django_filters

from .models import Room


class RoomFilter(django_filters.FilterSet):
    property = django_filters.CharFilter(field_name="property__slug")
    room_type = django_filters.NumberFilter(field_name="room_type_id")
    min_price = django_filters.NumberFilter(field_name="price_per_night", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price_per_night", lookup_expr="lte")
    min_guests = django_filters.NumberFilter(field_name="max_guests", lookup_expr="gte")
    amenity = django_filters.NumberFilter(field_name="amenities__id")

    class Meta:
        model = Room
        fields = ["property", "room_type", "min_price", "max_price", "min_guests", "amenity"]