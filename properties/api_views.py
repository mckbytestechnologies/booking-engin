# properties/api_views.py
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from .filters import PropertyFilter
from .models import Property
from .serializers import PropertyDetailSerializer, PropertyListSerializer


class PropertyViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]          # public catalogue, read-only
    lookup_field = "slug"
    filterset_class = PropertyFilter
    search_fields = ["name", "city"]
    ordering_fields = ["name", "city"]
    ordering = ["name"]

    def get_queryset(self):
        return (
            Property.objects.filter(is_active=True)
            .prefetch_related("amenities", "images")
            .distinct()
        )

    def get_serializer_class(self):
        return PropertyDetailSerializer if self.action == "retrieve" else PropertyListSerializer