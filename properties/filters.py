# properties/filters.py
import django_filters

from .models import Property


class PropertyFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(field_name="city", lookup_expr="iexact")
    amenity = django_filters.NumberFilter(field_name="amenities__id")

    class Meta:
        model = Property
        fields = ["city", "amenity"]